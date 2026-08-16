"""Typed, fail-closed health-probe contracts for ``harness doctor``."""

from __future__ import annotations

import re
import time
from abc import ABC
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProbeStage(str, Enum):
    """The mandatory order of evidence collected for every component."""

    CONFIGURED = "Configured"
    INSTALLED = "Installed"
    REACHABLE = "Reachable"
    AUTHENTICATED = "Authenticated"
    CAPABLE = "Capable"
    HEALTHY = "Healthy"


class ProbeStatus(str, Enum):
    """Closed stage outcomes; success is never inferred from absence of an error."""

    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DoctorStatus(str, Enum):
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"


_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class ProbeStageResult(BaseModel):
    """One redaction-safe observation for a single stage."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    stage: ProbeStage
    status: ProbeStatus
    code: str = Field(min_length=3, max_length=64)
    message: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_code(self) -> ProbeStageResult:
        if _CODE_PATTERN.fullmatch(self.code) is None:
            raise ValueError("probe result code must be a canonical uppercase identifier")
        return self


class ComponentProbeResult(BaseModel):
    """Deterministic six-stage result for one component."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    component_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    component_name: str = Field(min_length=1, max_length=80)
    mandatory: bool
    is_healthy: bool
    duration_ms: int = Field(ge=0)
    stages: tuple[ProbeStageResult, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def validate_stage_sequence(self) -> ComponentProbeResult:
        if tuple(stage.stage for stage in self.stages) != tuple(ProbeStage):
            raise ValueError("component stages must use the canonical six-stage order")
        expected_health = not any(stage.status is ProbeStatus.FAIL for stage in self.stages)
        if self.is_healthy is not expected_health:
            raise ValueError("component health must be derived from stage failures")
        if self.mandatory and self.stages[0].status is ProbeStatus.NOT_APPLICABLE:
            raise ValueError("mandatory components cannot be not applicable")
        return self


class DoctorResult(BaseModel):
    """Versioned report shared by text, JSON, and process exit status."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    status: DoctorStatus
    workflow: str | None = None
    components: tuple[ComponentProbeResult, ...] = Field(min_length=1)

    @property
    def is_healthy(self) -> bool:
        return self.status is DoctorStatus.HEALTHY

    @classmethod
    def build(
        cls,
        components: tuple[ComponentProbeResult, ...],
        *,
        workflow: str | None,
    ) -> DoctorResult:
        healthy = all(component.is_healthy for component in components)
        return cls(
            status=DoctorStatus.HEALTHY if healthy else DoctorStatus.UNHEALTHY,
            workflow=workflow,
            components=components,
        )


class HealthProbe(ABC):
    """Run exactly six read-only stages and fail closed on unexpected errors."""

    component_id: str
    component_name: str
    mandatory: bool = True

    def probe(self) -> ComponentProbeResult:
        started = time.monotonic_ns()
        results: list[ProbeStageResult] = []
        blocked_by: ProbeStage | None = None
        component_not_applicable = False

        for stage in ProbeStage:
            if blocked_by is not None:
                results.append(
                    self._result(
                        stage,
                        ProbeStatus.SKIPPED,
                        "BLOCKED_BY_PREVIOUS_STAGE",
                        f"Skipped because {blocked_by.value} failed.",
                    )
                )
                continue
            if component_not_applicable:
                results.append(
                    self._result(
                        stage,
                        ProbeStatus.NOT_APPLICABLE,
                        "COMPONENT_NOT_APPLICABLE",
                        "Component is not enabled for this invocation.",
                    )
                )
                continue

            try:
                outcome = self._run_stage(stage)
            except Exception:  # noqa: BLE001 - the doctor must convert every probe exception
                outcome = self._result(
                    stage,
                    ProbeStatus.FAIL,
                    "UNEXPECTED_PROBE_ERROR",
                    "Probe failed safely without exposing exception details.",
                )
            if outcome.stage is not stage:
                outcome = self._result(
                    stage,
                    ProbeStatus.FAIL,
                    "INVALID_PROBE_RESULT",
                    "Probe returned evidence for the wrong stage.",
                )
            results.append(outcome)
            if outcome.status is ProbeStatus.FAIL:
                blocked_by = stage
            elif stage is ProbeStage.CONFIGURED and outcome.status is ProbeStatus.NOT_APPLICABLE:
                component_not_applicable = True

        duration_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
        stages = tuple(results)
        return ComponentProbeResult(
            component_id=self.component_id,
            component_name=self.component_name,
            mandatory=self.mandatory,
            is_healthy=not any(stage.status is ProbeStatus.FAIL for stage in stages),
            duration_ms=duration_ms,
            stages=stages,
        )

    def _run_stage(self, stage: ProbeStage) -> ProbeStageResult:
        method = {
            ProbeStage.CONFIGURED: self.configured,
            ProbeStage.INSTALLED: self.installed,
            ProbeStage.REACHABLE: self.reachable,
            ProbeStage.AUTHENTICATED: self.authenticated,
            ProbeStage.CAPABLE: self.capable,
            ProbeStage.HEALTHY: self.healthy,
        }[stage]
        return method()

    def configured(self) -> ProbeStageResult:
        raise NotImplementedError

    def installed(self) -> ProbeStageResult:
        raise NotImplementedError

    def reachable(self) -> ProbeStageResult:
        raise NotImplementedError

    def authenticated(self) -> ProbeStageResult:
        raise NotImplementedError

    def capable(self) -> ProbeStageResult:
        raise NotImplementedError

    def healthy(self) -> ProbeStageResult:
        raise NotImplementedError

    @staticmethod
    def _result(
        stage: ProbeStage,
        status: ProbeStatus,
        code: str,
        message: str,
    ) -> ProbeStageResult:
        return ProbeStageResult(stage=stage, status=status, code=code, message=message)

    @classmethod
    def passed(cls, stage: ProbeStage, code: str, message: str) -> ProbeStageResult:
        return cls._result(stage, ProbeStatus.PASS, code, message)

    @classmethod
    def failed(cls, stage: ProbeStage, code: str, message: str) -> ProbeStageResult:
        return cls._result(stage, ProbeStatus.FAIL, code, message)

    @classmethod
    def not_applicable(cls, stage: ProbeStage, code: str, message: str) -> ProbeStageResult:
        return cls._result(stage, ProbeStatus.NOT_APPLICABLE, code, message)


__all__ = [
    "ComponentProbeResult",
    "DoctorResult",
    "DoctorStatus",
    "HealthProbe",
    "ProbeStage",
    "ProbeStageResult",
    "ProbeStatus",
]
