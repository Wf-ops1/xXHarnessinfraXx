"""Structural regressions for the short task panel and archived dossiers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_PANEL = ROOT / "TASK.md"
AGENT_RULES = ROOT / ".agents" / "AGENTS.md"
IMPLEMENTATION_PLAN = ROOT / "docs" / "plano_implementacao_harness_operacional.md"
PHASE3_REALIGNMENT = ROOT / "docs" / "fase3_realignamento_operacional.md"
PHASE3_ORDER_DECISION = ROOT / "docs" / "decisions" / "DEC-013-fase3-ordem-operacional.md"
TASKS_ROOT = ROOT / "docs" / "tasks"
TASKS_INDEX = TASKS_ROOT / "README.md"
ACTIVE_ROOT = TASKS_ROOT / "active"
COMPLETED_ROOT = TASKS_ROOT / "completed"
MANIFEST_PATH = TASKS_ROOT / "migration-manifest.json"
EXPECTED_TASK_IDS = {
    "F0.0",
    "F0.1",
    "F0.2",
    "F0.3",
    "F0.4",
    "F0.5",
    "F0.6",
    "F1.1",
    "F1.2",
    "F1.3",
    "F1.4",
    "F1.5",
    "F2.1",
    "F2.2",
    "F2.3",
    "F2.4",
    "F2.5",
    "F2.6",
    "DOC-F2-STATUS",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_task_panel_is_a_bounded_current_control_plane() -> None:
    panel = _read(TASK_PANEL)
    lines = panel.splitlines()
    active_dossiers = sorted(
        path for path in ACTIVE_ROOT.glob("*.md") if path.name != "README.md"
    )

    assert len(lines) <= 300
    assert panel.count("## 7. Próxima ação exata") == 1
    assert panel.count("## 5. Tarefa ativa") == 1
    assert "defensibility:" not in panel
    assert re.search(r"(?m)^### F[0-9]+\.[0-9]+\b", panel) is None

    if active_dossiers:
        assert len(active_dossiers) == 1
        assert active_dossiers[0].relative_to(ROOT).as_posix() in panel
    else:
        assert "nenhuma tarefa ativa" in panel.casefold()


def test_there_is_at_most_one_active_dossier() -> None:
    active_dossiers = sorted(
        path for path in ACTIVE_ROOT.glob("*.md") if path.name != "README.md"
    )

    assert len(active_dossiers) <= 1


def test_ready_active_dossier_has_the_normative_gate_fields() -> None:
    active_dossiers = sorted(
        path for path in ACTIVE_ROOT.glob("*.md") if path.name != "README.md"
    )
    if not active_dossiers:
        return

    dossier = _read(active_dossiers[0])
    required_markers = (
        "> **Gate:**",
        "> **Executor:**",
        "> **Autorizado em:**",
        "## Problema comprovado",
        "## Baseline conhecido",
        "## Escopo congelado",
        "## Critérios de aceite congelados",
        "## Rollback",
        "## Checklist de liberação",
    )

    for marker in required_markers:
        assert marker in dossier

    if "> **Gate:** `READY`" in dossier:
        assert "[x] baseline Git" in dossier
        assert "[x] escopo" in dossier
        assert "[x] rollback" in dossier


def test_completed_dossiers_match_the_integrity_manifest() -> None:
    manifest = json.loads(_read(MANIFEST_PATH))
    entries = manifest["entries"]
    markers = manifest["payload_markers"]

    assert manifest["schema_version"] == "1.0"
    assert manifest["source"] == {
        "commit": "d48151b752aa373756c46bfee58932fa5abf4bf5",
        "normalization": "section payload rstrip followed by one LF",
        "path": "TASK.md",
        "sha256": "f0f1a18751c0e730f7e6c4b6335192e0a655e06bba88e6996f9419270112d309",
    }
    assert len(entries) == len(EXPECTED_TASK_IDS)
    assert {entry["task_id"] for entry in entries} == EXPECTED_TASK_IDS
    assert len({entry["path"] for entry in entries}) == len(entries)

    completed_paths = {
        path.relative_to(ROOT).as_posix() for path in COMPLETED_ROOT.glob("*.md")
    }
    assert {entry["path"] for entry in entries} <= completed_paths

    for entry in entries:
        dossier = _read(ROOT / entry["path"])
        start_marker = markers["start"] + "\n"
        end_marker = markers["end"]
        assert dossier.count(markers["start"]) == 1
        assert dossier.count(end_marker) == 1
        payload = dossier.split(start_marker, 1)[1].split(end_marker, 1)[0]
        assert payload.splitlines()[0] == entry["source_heading"]
        assert _sha256(payload) == entry["payload_sha256"]


def test_agent_rules_point_to_the_short_panel_and_active_dossier() -> None:
    rules = _read(AGENT_RULES)

    assert "TASK.md` — painel curto" in rules
    assert "dossiê ativo apontado por `TASK.md`" in rules
    assert "docs/tasks/README.md" in rules
    assert "no máximo 300 linhas" in rules


def test_normative_sources_agree_on_gate_and_single_pr_lifecycle() -> None:
    rules = _read(AGENT_RULES)
    plan = _read(IMPLEMENTATION_PLAN)
    task_index = _read(TASKS_INDEX)

    assert "### 1.2 Contrato normativo do dossiê e do gate `READY`" in plan
    assert "Atualizar o dossiê ativo com resultado, arquivos, comandos" in plan
    assert "Atualizar `TASK.md` com resultado, arquivos, comandos" not in plan

    for requirement in (
        "Problema comprovado",
        "Baseline conhecido",
        "Escopo congelado",
        "Critérios congelados",
        "Rollback executável",
        "Responsabilidade explícita",
        "Nunca remover, ignorar ou tornar mais fraco um critério que falhou",
        "COMPLETED_LOCAL / PROMOTION_PENDING",
    ):
        assert requirement in plan

    assert "um único PR da tarefa" in plan
    assert "primeiro commit do gate seguinte" in plan
    assert "proibido abrir PR recursivo" in plan
    assert "PRs #17 e #18" in plan
    assert "não criam precedente" in plan

    assert "seção 1.2 do plano principal" in rules
    assert "Critério que falhou nunca pode ser removido" in rules
    assert "COMPLETED_LOCAL / PROMOTION_PENDING" in rules
    assert "primeiro commit do gate seguinte" in rules
    assert "proibido" in rules and "PR recursivo" in rules
    assert "DEC-011" in task_index
    assert "sem PR recursivo de fechamento" in task_index


def test_phase3_realignment_requires_two_isolated_gates_and_human_pauses() -> None:
    panel = _read(TASK_PANEL)
    plan = _read(IMPLEMENTATION_PLAN)
    task_index = _read(TASKS_INDEX)
    realignment = _read(PHASE3_REALIGNMENT)
    order_decision = _read(PHASE3_ORDER_DECISION)

    assert "DEC-012" in panel
    assert "DEC-012" in plan
    assert "DEC-012" in task_index
    assert "DEC-013" in panel
    assert "DEC-013" in plan
    assert "DEC-013" in task_index
    assert "F3.C1 → F3.C2 → F3.4" in plan
    assert "F3.4 → F3.6 → F3.5 → F3.8" in plan
    assert "raiz autorizada explícita" in order_decision
    assert "não habilita efeito algum" in order_decision
    assert "PAUSA HUMANA OBRIGATÓRIA" in realignment
    assert "autorização explícita nova" in realignment
    assert "F3.5 exige nova autorização explícita" in panel
    assert "Não restou achado blocker/high" in realignment
