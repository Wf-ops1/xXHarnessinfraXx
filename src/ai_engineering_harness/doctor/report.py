"""Text and deterministic JSON renderers for doctor results."""

from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.table import Table

from ai_engineering_harness.doctor.probes import DoctorResult, ProbeStatus

console = Console()


class DoctorReport:
    """Render the same typed report for humans and automation."""

    @classmethod
    def render(cls, report: DoctorResult) -> None:
        table = Table(title="AI-Engineering-Harness doctor (6 read-only stages)")
        table.add_column("Component", style="cyan", no_wrap=True)
        table.add_column("Status", style="bold", no_wrap=True)
        table.add_column("Stages", style="magenta")

        encoding = getattr(sys.stdout, "encoding", "") or ""
        supports_unicode = "utf" in encoding.lower()

        for component in report.components:
            if component.is_healthy:
                symbol = "✔ " if supports_unicode else "[OK] "
                status = f"[bold green]{symbol}HEALTHY[/bold green]"
            else:
                symbol = "✖ " if supports_unicode else "[FAIL] "
                status = f"[bold red]{symbol}UNHEALTHY[/bold red]"
            stages = " ".join(
                f"{stage.stage.value[0]}:{cls._status_token(stage.status)}"
                for stage in component.stages
            )
            table.add_row(component.component_name, status, stages)

        overall_symbol = (
            "✔ " if supports_unicode else "[OK] "
        ) if report.is_healthy else (
            "✖ " if supports_unicode else "[FAIL] "
        )
        overall_style = "green" if report.is_healthy else "red"
        console.print(table)
        console.print(
            f"[{overall_style}]{overall_symbol}{report.status.value}[/{overall_style}]"
        )

    @staticmethod
    def _status_token(status: ProbeStatus) -> str:
        return {
            ProbeStatus.PASS: "PASS",
            ProbeStatus.FAIL: "FAIL",
            ProbeStatus.SKIPPED: "SKIP",
            ProbeStatus.NOT_APPLICABLE: "N/A",
        }[status]

    @staticmethod
    def to_json(report: DoctorResult) -> str:
        return json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )


__all__ = ["DoctorReport"]
