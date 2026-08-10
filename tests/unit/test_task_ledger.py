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
POST_MERGE_DECISION = ROOT / "docs" / "decisions" / "DEC-014-reconciliacao-pos-merge.md"
PHASE4_COMPOSITION_DECISION = (
    ROOT / "docs" / "decisions" / "DEC-015-composicao-canonica-fase4.md"
)
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


def test_normative_sources_agree_on_gate_and_post_merge_reconciliation() -> None:
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
    assert "docs/promote-<id>" in plan
    assert "PR administrativo exclusivamente documental" in plan
    assert "não conta como segundo PR" in plan
    assert "de implementação da tarefa" in plan
    assert "não gera outra reconciliação recursiva" in plan

    assert "seção 1.2 do plano principal" in rules
    assert "Critério que falhou nunca pode ser removido" in rules
    assert "COMPLETED_LOCAL / PROMOTION_PENDING" in rules
    assert "docs/promote-<id>" in rules
    assert "reconciliação pós-merge possui PR documental próprio" in rules
    assert "não conta como segundo PR de implementação" in rules
    assert "DEC-011" in task_index
    assert "DEC-014" in task_index
    assert "substituída pela reconciliação imediata" in task_index


def test_f4_3_gate_uses_the_certified_f4_2_baseline() -> None:
    panel = _read(TASK_PANEL)
    task_index = _read(TASKS_INDEX)
    f3_5_dossier = _read(COMPLETED_ROOT / "F3.5.md")
    dossier = _read(COMPLETED_ROOT / "F3.8.md")
    f4_1_dossier = _read(COMPLETED_ROOT / "F4.1.md")
    f4_2_dossier = _read(COMPLETED_ROOT / "F4.2.md")
    f4_3_dossier = _read(ACTIVE_ROOT / "F4.3.md")
    decision = _read(POST_MERGE_DECISION)

    assert not (ACTIVE_ROOT / "F3.5.md").exists()
    assert not (ACTIVE_ROOT / "F3.8.md").exists()
    assert not (ACTIVE_ROOT / "F4.1.md").exists()
    assert (COMPLETED_ROOT / "F3.8.md").is_file()
    assert (COMPLETED_ROOT / "F4.1.md").is_file()
    assert "docs/tasks/completed/F4.2.md" in panel
    assert not (ACTIVE_ROOT / "F4.2.md").exists()
    assert (COMPLETED_ROOT / "F4.2.md").is_file()
    assert "docs/tasks/completed/F4.2.md" in panel
    assert "F4.2 `PROMOTED`" in panel
    assert (ACTIVE_ROOT / "F4.3.md").is_file()
    assert "docs/tasks/active/F4.3.md" in panel
    assert "F4.3 `READY` R6" in panel
    assert "task/f4.3-evidence-context-sufficiency" in panel
    assert "> **Gate:** `READY`" in f4_3_dossier
    assert "> **Lifecycle:** `COMPLETED_LOCAL / PROMOTION_PENDING`" in f4_3_dossier
    assert "370569377a1b065db479c239edde4016e1de5c0a" in f4_3_dossier
    assert "31346860397" in f4_3_dossier
    assert "> **Revisão do gate:** `R6`" in f4_3_dossier
    assert "checkpoint/f4.3-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r2-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r3-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r4-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r5-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r6-ready" in f4_3_dossier
    assert "DEC-015" in f4_3_dossier
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "45d3b059db071bdb98285e2ad821f525f80a9de6" in dossier
    assert "623 passed, 2 skipped, 6 subtests passed" in dossier
    assert "checkpoint/f3.8-complete" in dossier
    assert "31289781573" in dossier
    assert "31290430138" in dossier
    assert "31290644133" in dossier
    assert "3576a0495fd0d02a4413a131ec9848bfd24652ea" in dossier
    assert "checkpoint/f3.8-r2-docs-ready" in dossier
    assert "21 passed, 6 subtests passed" in dossier
    assert "f941c89fd0ec112aca82621ab9e11244f05962aa" in dossier
    assert "31292195340" in dossier
    assert "e6b5b84bbe8299f8e04b9ad28c0ca0a86269c98f" in dossier
    assert "31295594376" in dossier
    assert "checkpoint/f3.8-promotion-sync-ready" in dossier
    assert "PR #35" in panel
    assert "CI required" in panel
    assert "Autorizo o merge do PR #29" not in panel
    assert "Autorizo publicar a branch" not in panel
    assert "Autorizo o merge do PR #30" not in panel
    assert "Autorizo iniciar a F4.1" not in panel
    assert "05f54dd8690f060008acb95cf3de5d6a3c12b9a0" in dossier
    assert "PR administrativo #30" in dossier
    assert "bd0bda9385db850208f125e69757118ee9fe2b27" in dossier
    assert "31316549732" in dossier
    assert "c2aa89b50ad32dc90b26b70087dbd795e32f0042" in dossier
    assert "31316853244" in dossier
    assert "PR #27 aberto" not in panel
    assert "Autorizo o merge do PR #27" not in panel
    assert "> **Lifecycle:** `PROMOTED`" in f3_5_dossier
    assert "e6d947a2713e61c0700154cb7453f8bc0a7c342f" in f3_5_dossier
    assert "b6a4a24179271a8caa22252f71d08c35e13e7a41" in f3_5_dossier
    assert "31284043501" in f3_5_dossier
    assert "31285547886" in f3_5_dossier
    assert "completed/F3.5.md" in task_index
    assert "completed/F3.8.md" in task_index
    assert "completed/F4.1.md" in task_index
    assert "> **Lifecycle:** `PROMOTED`" in f4_1_dossier
    assert "3ba0e254d9d7425113ffcbcd6d22b5c663d7255e" in f4_1_dossier
    assert "31322494169" in f4_1_dossier
    assert "12ce3b7360a6035fb354326261fc409de15e29ec" in f4_1_dossier
    assert "31323952381" in f4_1_dossier
    assert "checkpoint/f4.1-promotion-sync-ready" in f4_1_dossier
    assert "31328788064" in f4_1_dossier
    assert "> **Gate:** `READY`" in f4_2_dossier
    assert "> **Lifecycle:** `PROMOTED`" in f4_2_dossier
    assert "e1ecc39cf26df1a4267aef867829b6d71f8bda1f" in f4_2_dossier
    assert "31328946696" in f4_2_dossier
    assert "571a8eb8be27179dd83527d7691012d732a27d28" in f4_2_dossier
    assert "31329231458" in f4_2_dossier
    assert "checkpoint/f4.2-ready" in f4_2_dossier
    assert "643 passed, 2 skipped, 6 subtests passed" in f4_2_dossier
    assert "7702396d5dd74ebed3f5a0aa449721a3a89d554d" in f4_2_dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/34" in f4_2_dossier
    assert "PR_OPEN / CHECKS_PENDING" in f4_2_dossier
    assert "2268f3fa276b017ad5b64efdb54e7abbf1f917d9" in f4_2_dossier
    assert "31344668587" in f4_2_dossier
    assert "212a9bfba2189ce8ca84d8eca76ede2d872b7d2c" in f4_2_dossier
    assert "31345231098" in f4_2_dossier
    assert "checkpoint/f4.2-promotion-sync-ready" in f4_2_dossier
    assert "completed/F4.2.md" in task_index
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/35" in f4_2_dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in f4_2_dossier
    assert "administrativo #35 / merge `3705693` / pós-merge `31346860397`" in task_index
    assert "370569377a1b065db479c239edde4016e1de5c0a" in panel
    assert "31346860397" in panel
    assert "administrativo #33 / merge `571a8eb` / pós-merge `31329231458`" in task_index
    assert "O PR administrativo não cria reconciliação recursiva de si mesmo" in decision


def test_f4_3_r6_preserves_prior_gates_and_names_every_phase4_owner() -> None:
    panel = _read(TASK_PANEL)
    plan = _read(IMPLEMENTATION_PLAN)
    task_index = _read(TASKS_INDEX)
    dossier = _read(ACTIVE_ROOT / "F4.3.md")
    decision = _read(PHASE4_COMPOSITION_DECISION)

    r1_at = dossier.find("### R1 — gate inicial preservado")
    r2_at = dossier.find("### R2 — diagnóstico e recertificação documental")
    r3_at = dossier.find("### R3 — exceção mínima da FSM")
    r4_at = dossier.find("### R4 — entrada pré-grafo em `PLANNING`")
    r5_at = dossier.find("### R5 — correção mínima do gate de tipos")
    r6_at = dossier.find("### R6 — auditoria pós-CI reabre o gate fail-closed")
    assert r1_at >= 0
    assert r2_at > r1_at
    assert r3_at > r2_at
    assert r4_at > r3_at
    assert r5_at > r4_at
    assert r6_at > r5_at
    assert "perde precedência operacional para este R2" in dossier
    assert "checkpoint/f4.3-ready" in dossier
    assert "checkpoint/f4.3-r2-ready" in dossier
    assert "checkpoint/f4.3-r3-ready" in dossier
    assert "checkpoint/f4.3-r4-ready" in dossier
    assert "checkpoint/f4.3-r5-ready" in dossier
    assert "checkpoint/f4.3-r6-ready" in dossier
    assert "BLOCKED_INSUFFICIENT_CONTEXT → FAILED_RETRY_EXHAUSTED" in dossier
    assert "ExecutionLifecycleService" in dossier
    assert "INITIATED → CONTEXT_ASSEMBLING" in dossier
    assert "BLOCKED_INSUFFICIENT_CONTEXT" in dossier
    assert "BLOCKED_PREREQUISITE" in dossier
    assert "GraphExecutor" in dossier
    assert "conditional` não vazio falha" in dossier
    assert "suíte vazia/gate desconhecido/ID `tests`" in dossier

    for source in (panel, plan, task_index, dossier):
        assert "DEC-015" in source
    assert "ExecutionLifecycleService" in decision
    assert "GraphExecutor" in decision
    assert "F4.4" in decision
    assert "F4.5" in decision
    assert "F4.6" in decision
    assert "F4.7" in decision
    assert "F4.8" in decision
    assert "all_passed=True" in decision
    assert "context_request" in decision
    assert "graph_input" in decision
    assert "ao menos um gate obrigatório" in decision
    assert "checkpoint/f4.3-r2-ready" in panel
    assert "checkpoint/f4.3-r3-ready" in panel
    assert "checkpoint/f4.3-r4-ready" in panel
    assert "checkpoint/f4.3-r5-ready" in panel
    assert "checkpoint/f4.3-r6-ready" in panel
    assert "Não há blocker técnico local ou remoto aberto" in panel
    assert "runtime/planner.py:68" in panel
    assert "673 passed, 2 skipped, 6 subtests passed" in dossier
    assert "materializa `ContextPackage.relevant_symbols` como `list[str]`" in dossier
    assert "674 passed, 2 skipped, 6 subtests passed" in dossier
    assert "0c376023d3f6a2d6ccde8277de715e0dd617e1b3" in dossier
    assert "1ee5f062b75a45b0cbcbab0e23b68458969c7c99" in dossier
    assert "[#36](https://github.com/Wf-ops1/Harnessinfra/pull/36)" in dossier
    assert "0cc4c383ff024024242810dfff7961d495ce6ef6" in dossier
    assert "31409970887" in dossier
    assert "REPAIR_ACTIVE / PROMOTION_BLOCKED" in dossier
    assert "31410376576" in dossier
    assert "artifact_evidence=()" in dossier
    assert "req-other" in dossier
    assert "d686d50e84eba6cf2d318da837e26547bb3b833c" in dossier
    assert "ed559ee8f0c7c0b4c52bdd7b144d19af0ddbc7c0" in dossier
    assert "grupos congelados: 96 / 48 / 63 / 72 testes" in dossier
    assert "679 passed, 2 skipped, 6 subtests passed" in dossier
    assert "> **Lifecycle:** `COMPLETED_LOCAL / PROMOTION_PENDING`" in dossier
    assert "ede9a54fac2517586d3f4a48b586b73a3f47a33a" in dossier
    assert "31414226952" in dossier
    assert "11/11 checks verdes" in dossier
    assert "merge não autorizado" in dossier


def test_negative_evidence_precedes_positive_state_until_recertification() -> None:
    panel = _read(TASK_PANEL)
    rules = _read(AGENT_RULES)
    plan = _read(IMPLEMENTATION_PLAN)
    decision = _read(POST_MERGE_DECISION)
    dossier = _read(COMPLETED_ROOT / "F3.5.md")
    f3_8_dossier = _read(COMPLETED_ROOT / "F3.8.md")

    for source in (panel, rules, plan, decision):
        assert "evidência negativa" in source.casefold()
        assert "recertifica" in source.casefold()

    assert "POST_PROMOTION_BLOCKED" in rules
    assert "POST_PROMOTION_BLOCKED" in plan
    assert "POST_PROMOTION_BLOCKED" in decision
    blocked_at = dossier.rfind("PROMOTION_BLOCKED")
    certified_at = dossier.rfind("## Certificação final de promoção")
    assert blocked_at >= 0
    assert certified_at > blocked_at
    assert 0 <= dossier.rfind("31281757984") < certified_at
    assert dossier.rfind("31284043501") > certified_at
    assert dossier.rfind("31285547886") > certified_at
    assert "## R1 — CI do PR #29 reabre portabilidade e promoção" in f3_8_dossier
    assert "Essa evidência negativa não invalida os checks técnicos anteriores" in f3_8_dossier
    f3_8_r1_blocked_at = f3_8_dossier.find("> **Estado:** `REPAIR_ACTIVE / PROMOTION_BLOCKED`")
    f3_8_r1_recertified_at = f3_8_dossier.find("### Recertificação do reparo R1")
    f3_8_r2_blocked_at = f3_8_dossier.find("## R2 — Recongelamento")
    f3_8_r2_recertified_at = f3_8_dossier.find("### Recertificação do reparo R2")
    assert f3_8_r1_blocked_at >= 0
    assert f3_8_r1_recertified_at > f3_8_r1_blocked_at
    assert f3_8_r2_blocked_at > f3_8_r1_recertified_at
    assert f3_8_r2_recertified_at > f3_8_r2_blocked_at
    assert "Falha histórica, diagnóstico e tentativas inválidas permanecem explícitos" in f3_8_dossier


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
    assert "DEC-014" in panel
    assert "DEC-014" in task_index
    assert "DEC-015" in panel
    assert "DEC-015" in plan
    assert "DEC-015" in task_index
    assert "F3.C1 → F3.C2 → F3.4" in plan
    assert "F3.4 → F3.6 → F3.5 → F3.8" in plan
    assert "raiz autorizada explícita" in order_decision
    assert "não habilita efeito algum" in order_decision
    assert "PAUSA HUMANA OBRIGATÓRIA" in realignment
    assert "autorização explícita nova" in realignment
    assert "docs/tasks/completed/F4.2.md" in panel
    assert "F4.1" in panel
    assert "F3.7 permanece depois" in panel
    assert "Não restou achado blocker/high" in realignment
