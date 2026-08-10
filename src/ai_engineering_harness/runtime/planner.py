"""Planner Module — Fase 3 do Ciclo Agentic."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ai_engineering_harness.runtime.context_assembler import ContextPackage


class InvalidPlanError(ValueError):
    """Exceção lançada quando um plano de execução não atende aos critérios mínimos de validação."""


@dataclass
class PlanDocument:
    goal: str
    scope: list[str] = field(default_factory=list)
    affected_modules: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    applicable_gates: list[str] = field(default_factory=list)
    rollback_strategy: str = "append_only_audit_compensation"
    completion_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Planner:
    """Gera e valida o plano de execução estruturado em plan.json."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.persona_file = project_root / "src" / "ai_engineering_harness" / "defaults" / "agents" / "architecture_analyst" / "system_prompt.md"

    def _load_winston_persona(self) -> str:
        if self.persona_file.exists():
            return self.persona_file.read_text(encoding="utf-8")
        return "System Architect (Winston)"

    def validate_plan(self, plan: PlanDocument) -> bool:
        if not plan.goal or not plan.goal.strip():
            return False
        if not plan.affected_modules:
            return False
        return bool(plan.applicable_gates)

    def create_plan(
        self,
        execution_id: str,
        context_package: ContextPackage,
        intent: str = "Implement user story"
    ) -> PlanDocument:
        exec_dir = self.project_root / ".harness" / "state" / "executions" / execution_id
        exec_dir.mkdir(parents=True, exist_ok=True)
        plan_file = exec_dir / "plan.json"

        goal = intent if intent else "Implement functionality with high quality"
        scope = ["src/ai_engineering_harness/"]
        affected_modules = list(context_package.relevant_symbols) or ["core", "runtime"]
        risks = ["potencial quebra de regressão", "violação de política de ferramentas"]
        applicable_gates = ["typecheck", "lint", "unit_test"]
        completion_criteria = ["100% dos testes unitários passando", "verificação de segurança e tipo ok"]

        plan = PlanDocument(
            goal=goal,
            scope=scope,
            affected_modules=affected_modules,
            risks=risks,
            applicable_gates=applicable_gates,
            rollback_strategy="append_only_audit_compensation",
            completion_criteria=completion_criteria,
        )

        if not self.validate_plan(plan):
            raise InvalidPlanError(f"O plano gerado para {execution_id} é inválido.")

        plan_file.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
        return plan
