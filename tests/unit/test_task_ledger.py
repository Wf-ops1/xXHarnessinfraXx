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


def test_f4_4_promotion_uses_the_certified_f4_3_baseline() -> None:
    panel = _read(TASK_PANEL)
    task_index = _read(TASKS_INDEX)
    f3_5_dossier = _read(COMPLETED_ROOT / "F3.5.md")
    dossier = _read(COMPLETED_ROOT / "F3.8.md")
    f4_1_dossier = _read(COMPLETED_ROOT / "F4.1.md")
    f4_2_dossier = _read(COMPLETED_ROOT / "F4.2.md")
    f4_3_dossier = _read(COMPLETED_ROOT / "F4.3.md")
    f4_4_dossier = _read(COMPLETED_ROOT / "F4.4.md")
    decision = _read(POST_MERGE_DECISION)

    assert not (ACTIVE_ROOT / "F3.5.md").exists()
    assert not (ACTIVE_ROOT / "F3.8.md").exists()
    assert not (ACTIVE_ROOT / "F4.1.md").exists()
    assert (COMPLETED_ROOT / "F3.8.md").is_file()
    assert (COMPLETED_ROOT / "F4.1.md").is_file()
    assert not (ACTIVE_ROOT / "F4.2.md").exists()
    assert (COMPLETED_ROOT / "F4.2.md").is_file()
    assert "completed/F4.2.md" in task_index
    assert not (ACTIVE_ROOT / "F4.3.md").exists()
    assert (COMPLETED_ROOT / "F4.3.md").is_file()
    assert not (ACTIVE_ROOT / "F4.4.md").exists()
    assert (COMPLETED_ROOT / "F4.4.md").is_file()
    assert "completed/F4.4.md" in task_index
    assert "> **Lifecycle:** `PROMOTED`" in f4_4_dossier
    assert "> **Gate:** `READY`" in f4_3_dossier
    assert "> **Lifecycle:** `PROMOTED`" in f4_3_dossier
    assert "370569377a1b065db479c239edde4016e1de5c0a" in f4_3_dossier
    assert "31346860397" in f4_3_dossier
    assert "> **Revisão do gate:** `R6`" in f4_3_dossier
    assert "checkpoint/f4.3-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r2-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r3-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r4-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r5-ready" in f4_3_dossier
    assert "checkpoint/f4.3-r6-ready" in f4_3_dossier
    assert "checkpoint/f4.3-promotion-sync-ready" in f4_3_dossier
    assert "84eda1c421d13d1e8e86620127c3318e2cfe5086" in f4_3_dossier
    assert "31414853048" in f4_3_dossier
    assert "fa31ef8987b1028d38014fe676247cd425daf9b6" in f4_3_dossier
    assert "31419214233" in f4_3_dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/37" in f4_3_dossier
    assert "8021a54c4024e541898bdd7f94cf981e0f14f179" in f4_3_dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in f4_3_dossier
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
    assert "PR #38" in f4_4_dossier
    assert "11/11" in f4_4_dossier
    assert "fbdb6ee3d2e1728cbc691b98f04846989475c614" in f4_4_dossier
    assert "31442203348" in f4_4_dossier
    assert "93ce4ce9f4f0042c58d64103528b6c359a475bd9" in f4_4_dossier
    assert "31445624269" in f4_4_dossier
    assert "Autorizo o merge do PR #29" not in panel
    assert "Autorizo publicar a branch docs/promote-f4.4" not in panel
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
    assert "completed/F4.3.md" in task_index
    assert "administrativo #37 / merge `5c8408d` / pós-merge `31433785637`" in task_index
    assert "93ce4ce9f4f0042c58d64103528b6c359a475bd9" in f4_4_dossier
    assert "31445624269" in f4_4_dossier
    assert "administrativo #33 / merge `571a8eb` / pós-merge `31329231458`" in task_index
    assert "O PR administrativo não cria reconciliação recursiva de si mesmo" in decision


def test_f4_3_r6_preserves_prior_gates_and_names_every_phase4_owner() -> None:
    panel = _read(TASK_PANEL)
    plan = _read(IMPLEMENTATION_PLAN)
    task_index = _read(TASKS_INDEX)
    dossier = _read(COMPLETED_ROOT / "F4.3.md")
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
    assert "checkpoint/f4.3-promotion-sync-ready" in dossier
    assert "F5.5 — integrar secrets e redaction no caminho crítico" in panel
    assert "F5.6 `PROMOTED`" in panel
    assert "docs/promote-f5.6" in panel
    assert "daec37d119fced3a5e041c412ab01e7524c15800" in panel
    assert "31771169636" in panel
    assert "docs/tasks/completed/F5.5.md" in panel
    assert "task/f5.5-secrets-redaction" in panel
    assert "2f4e391bfe3588f713a436b051d4f60e970e4df1" in panel
    assert "31759971204" in panel
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/54" in panel
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/53" in panel
    assert "docs/tasks/completed/F4.8.md" in panel
    assert "31568908128" in panel
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
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "ede9a54fac2517586d3f4a48b586b73a3f47a33a" in dossier
    assert "31414226952" in dossier
    assert "11/11 checks verdes" in dossier
    assert "merge não autorizado" in dossier
    assert "84eda1c421d13d1e8e86620127c3318e2cfe5086" in dossier
    assert "31414853048" in dossier
    assert "fa31ef8987b1028d38014fe676247cd425daf9b6" in dossier
    assert "31419214233" in dossier
    assert dossier.rfind("## Certificação final da promoção") > dossier.rfind("merge não autorizado")


def test_f4_4_promotion_records_implementation_and_post_merge_ci() -> None:
    readme = _read(ROOT / "README.md")
    dossier = _read(COMPLETED_ROOT / "F4.4.md")
    task_index = _read(TASKS_INDEX)

    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "> **Implementação:** `incorporada em main pelo PR #38 e certificada pela CI pós-merge`" in dossier
    assert "checkpoint/f4.4-ready" in dossier
    assert "task/f4.4-typed-specific-plan" in dossier
    assert "5c8408df9d1d1ce16d21508fbcb3a647ecf20ee1" in dossier
    assert "31433785637" in dossier
    assert "structured_output_with_fallback" in dossier
    assert "PLAN_GENERATION_STARTED" in dossier
    assert "PLAN_GENERATED" in dossier
    assert "context_digest" in dossier
    assert "graph_input_digest" in dossier
    assert "GraphExecutor" in dossier
    assert "F4.5–F4.8" in dossier
    assert "Autorizo implementar a F4.4 conforme o gate READY e a DEC-015" in dossier
    assert "Autorizo criar o commit local de conclusão da F4.4" in dossier
    assert "Autorizo o merge do PR #38" in dossier
    assert "fbdb6ee3d2e1728cbc691b98f04846989475c614" in dossier
    assert "31442203348" in dossier
    assert "93ce4ce9f4f0042c58d64103528b6c359a475bd9" in dossier
    assert "31445624269" in dossier
    assert "LOCAL_READY / PUBLICATION_PENDING" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/39" in dossier
    assert "63562bdd724213dbfbf47442e9c2f7e3354d662b" in dossier
    assert "31447000037" in dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in dossier
    assert "PR #38 encerrou no head `fbdb6ee`" in readme
    assert "docs/promote-f4.4" in readme
    assert "completed/F4.4.md" in task_index
    assert "PR #38 / merge `93ce4ce` / pós-merge `31445624269`" in task_index
    assert "administrativo #39 / merge `94641d2` / pós-merge `31447628152`" in task_index
    assert "administrativo #37 / merge `5c8408d` / pós-merge `31433785637`" in task_index


def test_f4_6_promotion_records_repair_history_and_post_merge_ci() -> None:
    panel = _read(TASK_PANEL)
    readme = _read(ROOT / "README.md")
    dossier = _read(COMPLETED_ROOT / "F4.C1.md")
    f4_5_dossier = _read(COMPLETED_ROOT / "F4.5.md")
    task_index = _read(TASKS_INDEX)

    assert not (ACTIVE_ROOT / "F4.C1.md").exists()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "checkpoint/f4.c1-ready" in dossier
    assert "checkpoint/f4.c1-complete" in dossier
    assert "b4d212cb96a4b1b3335a467a7719b40856c30558" in dossier
    assert "65c54338b5753d31c0b0ed15ab6cf9ba1486f493" in dossier
    assert "31453116947" in dossier
    assert "3905d02d575fc177d917f605b7e1a9b6a658c818" in dossier
    assert "31453662008" in dossier
    assert "LOCAL_READY / PUBLICATION_PENDING" in dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/41" in dossier
    assert "39f7366fcd4b9aebdcb7e5fb0b6964a9929c2a39" in dossier
    assert "31454615745" in dossier
    assert "SnapshotConflictError" in dossier
    assert "os.link" in dossier
    f4_6_dossier = _read(COMPLETED_ROOT / "F4.6.md")
    f4_7_dossier = _read(COMPLETED_ROOT / "F4.7.md")
    assert not (ACTIVE_ROOT / "F4.6.md").exists()
    assert not (ACTIVE_ROOT / "F4.7.md").exists()
    assert (COMPLETED_ROOT / "F4.7.md").is_file()
    assert "F5.1 — resolver configuração no início da execução" in panel
    assert "checkpoint/f5.1-ready" in panel
    assert "docs/tasks/completed/F4.8.md" in panel
    assert "c46910e50ede1196c9beb1242cb7bd708905d666" in panel
    assert "31630446370" in panel
    assert "> **Gate:** `READY`" in f4_7_dossier
    assert "> **Lifecycle:** `PROMOTED`" in f4_7_dossier
    assert "checkpoint/f4.7-ready" in f4_7_dossier
    assert "checkpoint/f4.7-complete" in f4_7_dossier
    assert "a706b7fb8ce6ca6ea7a3a2a65f7ad4ab7630bf6a" in f4_7_dossier
    assert "bbc2d93963c9c9fdfd5dfffa2d44c64439862c72" in f4_7_dossier
    assert "751 passed, 5 skipped, 6 subtests passed" in f4_7_dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/46" in f4_7_dossier
    assert "054bf6e31b45e00aa7f27e35f0405b871111647b" in f4_7_dossier
    assert "31528955883" in f4_7_dossier
    assert "checkpoint/f4.7-r1-ready" in f4_7_dossier
    assert "checkpoint/f4.7-r1-complete" in f4_7_dossier
    assert "2841346a" in f4_7_dossier
    assert "20/20" in f4_7_dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/47" in f4_7_dossier
    assert "f37e422a1fbcaf386c0dea7775192e2dace6ee26" in f4_7_dossier
    assert "b79e14d2ba2c76514b7e6a6b22017b02348e6453" in f4_7_dossier
    assert "31533353223" in f4_7_dossier
    assert "4aa701a9394e5bdcb9c14dc5a9a715638c183258" in f4_7_dossier
    assert "31534918672" in f4_7_dossier
    assert "LOCAL_READY / PUBLICATION_PENDING" in f4_7_dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in f4_7_dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/48" in f4_7_dossier
    assert "e198e5b713e7dc6260899b05414a07058af8595e" in f4_7_dossier
    assert "SKIPPED_NOT_APPLICABLE" in f4_7_dossier
    assert "ao menos um gate obrigatório" in f4_7_dossier
    assert "> **Gate:** `READY`" in f4_6_dossier
    assert "> **Lifecycle:** `PROMOTED`" in f4_6_dossier
    assert "> **Revisão do gate:** `R3" in f4_6_dossier
    assert "src/ai_engineering_harness/tools/adapters/terminal.py" in f4_6_dossier
    assert "<sys.prefix>/bin/python" in f4_6_dossier
    assert "path de lançamento" in f4_6_dossier
    assert "checkpoint/f4.6-ready" in f4_6_dossier
    assert "checkpoint/f4.6-r1-ready" in f4_6_dossier
    assert "checkpoint/f4.6-complete" in f4_6_dossier
    assert "507c216" in f4_6_dossier
    assert "735 passed, 2 skipped, 6 subtests passed" in f4_6_dossier
    assert "ERROR_PREREQUISITE" in f4_6_dossier
    assert "ProvisionedWorktree" in f4_6_dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/43" in f4_5_dossier
    assert "b30416470b0ea4b266d2c4a65b9b1963858d51b8" in f4_5_dossier
    assert "31459427729" in f4_5_dossier
    assert "completed/F4.7.md" in task_index
    assert "corretivo #47 / merge `4aa701a` / pós-merge `31534918672`" in task_index
    assert "administrativo #48 / merge `d4e34c7` / pós-merge `31541047111`" in task_index
    assert not (ACTIVE_ROOT / "F4.5.md").exists()
    assert "> **Gate:** `READY`" in f4_5_dossier
    assert "> **Lifecycle:** `PROMOTED`" in f4_5_dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/42" in f4_5_dossier
    assert "a77b4d9890a83a498c5f70db7efdcec92d92baed" in f4_5_dossier
    assert "31457756495" in f4_5_dossier
    assert "9e8dfe80a8aaf0bcf4180866fb6e40eb117b0fc6" in f4_5_dossier
    assert "31457935429" in f4_5_dossier
    assert "4ae0de798607cf4fec13c0469fddb93d8024ead5" in f4_5_dossier
    assert "31458482033" in f4_5_dossier
    assert "714 passed, 2 skipped, 6 subtests passed" in f4_5_dossier
    assert "bfb70fc216900e610fd80ffe1fd2da89382ce1b0" in f4_5_dossier
    assert "typecheck`, `lint`, `unit_test`, `build` e `security_scan`" in f4_5_dossier
    assert "GateRunner" in f4_5_dossier
    assert "F4.6" in f4_5_dossier
    assert "PR #40 foi incorporado pelo merge `3905d02`" in readme
    assert "31453116947" in readme
    assert "31453662008" in readme
    assert "merge `362407f`" in readme
    assert "31455148050" in readme
    assert "PR #42" in readme
    assert "9e8dfe8" in readme
    assert "31457935429" in readme
    assert "4ae0de7" in readme
    assert "31458482033" in readme
    assert "PR #43" in readme
    assert "`46b7070`" in readme
    assert "31459891130" in readme
    assert "completed/F4.C1.md" in task_index
    assert "PR #40 / merge `3905d02` / pós-merge `31453662008`" in task_index
    assert "administrativo #41 / merge `362407f` / pós-merge `31455148050`" in task_index
    assert "31455148050" in task_index
    assert "PR #42" in task_index
    assert "completed/F4.5.md" in task_index
    assert "PR #42 / merge `4ae0de7` / pós-merge `31458482033`" in task_index
    assert "administrativo #43 / merge `46b7070` / pós-merge `31459891130`" in task_index
    assert "f26c124" in f4_6_dossier
    assert "736 passed, 3 skipped, 6 subtests passed" in f4_6_dossier
    assert "checkpoint/f4.6-r3-ready" in f4_6_dossier
    assert "checkpoint/f4.6-r3-complete" in f4_6_dossier
    assert "ce07850" in f4_6_dossier
    assert "167dbe5" in f4_6_dossier
    assert "738 passed, 5 skipped, 6 subtests passed" in f4_6_dossier
    assert "00e83574da789fa58f22f928b5290b9471264a63" in f4_6_dossier
    assert "31505324814" in f4_6_dossier
    assert "93832738803" in f4_6_dossier
    assert "93833502210" in f4_6_dossier
    assert "a4fd1dabe09c9f6064f7c34b0ddb6bc62761135d" in f4_6_dossier
    assert "31510277593" in f4_6_dossier
    assert "LOCAL_READY / PUBLICATION_PENDING" in f4_6_dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in f4_6_dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/45" in f4_6_dossier
    assert "5882e42088f0ded00c88f5ad24451378e9adfebf" in f4_6_dossier
    assert "31512347572" in f4_6_dossier
    assert "completed/F4.6.md" in task_index
    assert "PR #44 / merge `a4fd1da` / pós-merge `31510277593`" in task_index
    assert "administrativo #45 / merge `b578515` / pós-merge `31513097203`" in task_index


def test_f4_8_promotion_records_repair_loop_and_post_merge_ci() -> None:
    panel = _read(TASK_PANEL)
    readme = _read(ROOT / "README.md")
    dossier = _read(COMPLETED_ROOT / "F4.8.md")
    task_index = _read(TASKS_INDEX)

    assert not (ACTIVE_ROOT / "F4.8.md").exists()
    assert (COMPLETED_ROOT / "F4.8.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "incorporada em main pelo PR #49 e certificada pela CI pós-merge" in dossier
    assert "checkpoint/f4.8-ready" in dossier
    assert "checkpoint/f4.8-complete" in dossier
    assert "bb6752c1f1524b8c747cddc55e74ed7e6491e845" in dossier
    assert "8e5e11d81c685c53ba349bab4d95cdd61ee19ba6" in dossier
    assert "5bf0d75e6878f0d1362e0b2053a228a95ec80cef" in dossier
    assert "f9c8c2d5d2e1f53ef857119886c16b8b2b2c1d8d" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/49" in dossier
    assert "31550975708" in dossier
    assert "72f89e3ede8c4d7457857c13115f690d87df4aad" in dossier
    assert "31551685950" in dossier
    assert "758 passed, 5 skipped" in dossier
    assert "targeted seguido de full" in dossier
    assert "FAILED_RETRY_EXHAUSTED" in dossier
    assert "crash-resume" in dossier
    assert "docs/promote-f4.8" in dossier
    assert dossier.find("## Certificação final da promoção") > dossier.find(
        "## Publicação do PR — snapshot histórico"
    )
    assert dossier.rfind("## Publicação administrativa") > dossier.rfind(
        "## Certificação final da promoção"
    )
    assert "F5.1 — resolver configuração no início da execução" in panel
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/50" in dossier
    assert "3d571cadaffa798c7be1387431e54eaf0463346a" in dossier
    assert not (ACTIVE_ROOT / "F3.7.md").exists()
    assert (COMPLETED_ROOT / "F3.7.md").is_file()
    assert "F3.7 — promoção Git segura" in panel
    assert "A F4.8 foi promovida pelo PR #49" in readme
    assert "completed/F4.8.md" in task_index
    assert "PR #49 / merge `72f89e3` / pós-merge `31551685950`" in task_index


def test_f3_7_promotion_records_r2_and_post_merge_ci() -> None:
    panel = _read(TASK_PANEL)
    dossier = _read(COMPLETED_ROOT / "F3.7.md")
    task_index = _read(TASKS_INDEX)

    assert not (ACTIVE_ROOT / "F3.7.md").exists()
    assert (COMPLETED_ROOT / "F3.7.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Revisão final:** `R2`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "task/f3.7-safe-promotion" in dossier
    assert "9f75e35db38fc6648497c01bd8f81dcdecec8029" in dossier
    assert "31557794240" in dossier
    assert "sha-promoted-37" in dossier
    assert "git add ." in dossier
    assert "sha-fallback-<execution_id>" in dossier
    assert "candidate_commit_sha" in dossier
    assert "promotion_commit_sha" in dossier
    assert "BLOCKED_BASE_CHANGED" in dossier
    assert "DRY_RUN_COMPLETED" in dossier
    assert "git cherry-pick <candidate_sha>" in dossier
    assert "ApprovalStatus.APPROVED" in dossier
    assert "última suíte canônica F4.7 passou no mesmo candidate SHA" in dossier
    assert "write-ahead durável" in dossier
    assert "tests/e2e/test_safe_promotion.py" in dossier
    assert "checkpoint/f3.7-ready" in dossier
    assert "checkpoint/f3.7-complete" in dossier
    assert "checkpoint/f3.7-r1-ready" in dossier
    assert "checkpoint/f3.7-r1-complete" in dossier
    assert "checkpoint/f3.7-r2-ready" in dossier
    assert "checkpoint/f3.7-r2-complete" in dossier
    assert "774 passed, 5 skipped, 6 subtests passed" in dossier
    assert "F5.1 — resolver configuração no início da execução" in panel
    assert "d31227694344ea89303bfb6853eb238c4ca6d8f7" in dossier
    assert "31565797052" in dossier
    assert "94017253149" in dossier
    assert "94017253186" in dossier
    assert "31567250425" in dossier
    assert "94021523104" in dossier
    assert "94021523172" in dossier
    assert "9cf15d43e906fc8c3611ca4c6c0863218e33784c" in dossier
    assert "exatamente uma chamada `git cherry-pick <candidate_sha>`" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/51" in dossier
    assert "ac1d3e2ad5bda0111d5da7e7569d23318c9d762a" in dossier
    assert "40f81375f93706352fd19b5ef280ebe674d5249d" in dossier
    assert "31568577459" in dossier
    assert "10d75408f10ce83ffa232f117d203aa2f26bedb0" in dossier
    assert "31568908128" in dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/52" in dossier
    assert "639653532768b4b06eedc30045308923c83218d9" in dossier
    assert "docs/tasks/completed/F3.7.md" in panel
    assert "completed/F3.7.md" in task_index
    assert "PR #51 / merge `10d75408` / pós-merge `31568908128`" in task_index
    assert "administrativo #50 / merge `9f75e35` / pós-merge `31557794240`" in task_index


def test_f5_1_promotion_records_configuration_and_post_merge_ci() -> None:
    panel = _read(TASK_PANEL)
    dossier = _read(COMPLETED_ROOT / "F5.1.md")
    task_index = _read(TASKS_INDEX)
    readme = _read(ROOT / "README.md")

    assert not (ACTIVE_ROOT / "F5.1.md").exists()
    assert (COMPLETED_ROOT / "F5.1.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "checkpoint/f5.1-ready" in dossier
    assert "checkpoint/f5.1-complete" in dossier
    assert "f246feb2a70bb83f08ff31341525fd29bd6d10f8" in dossier
    assert "f42af272c54b2610554eb34acd75dc895a011974" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/53" in dossier
    assert "31629604755" in dossier
    assert "c46910e50ede1196c9beb1242cb7bd708905d666" in dossier
    assert "31630446370" in dossier
    assert "792 passed, 5 skipped, 6 subtests passed" in dossier
    assert "LOCAL_READY / PUBLICATION_PENDING" in dossier
    assert "docs/promote-f5.1" in dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/54" in dossier
    assert "f7e117303bb01cbc1afbc604781efd09ab9c94c8" in dossier
    assert "F5.3 — trust boundary integrado" in panel
    assert "docs/tasks/completed/F5.1.md" in panel
    assert "31633748837" in panel
    assert "fe95a91648a79c404565583c87c1cf357e8ab3a2" in panel
    assert "completed/F5.1.md" in task_index
    assert "administrativo #54 / merge `fe95a91` / pós-merge `31633748837`" in task_index
    assert "F5.1 foi promovida pelo" in readme


def test_f5_2_ready_gate_freezes_unified_policy_contract() -> None:
    panel = _read(TASK_PANEL)
    dossier = _read(COMPLETED_ROOT / "F5.2.md")
    task_index = _read(TASKS_INDEX)
    readme = _read(ROOT / "README.md")

    assert not (ACTIVE_ROOT / "F5.2.md").exists()
    assert (COMPLETED_ROOT / "F5.2.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "checkpoint/f5.2-ready" in dossier
    assert "checkpoint/f5.2-complete" in dossier
    assert "BRANCH_PUBLISHED / PR_PENDING" in dossier
    assert "PR_OPEN / CHECKS_PENDING" in dossier
    assert "origin/task/f5.2-unified-policy" in dossier
    assert "push` somente em `main` e `phase/**" in dossier
    assert "evento `pull_request` contra `main`" in dossier
    assert "task/f5.2-unified-policy" in dossier
    assert "fe95a91648a79c404565583c87c1cf357e8ab3a2" in dossier
    assert "policy_default_allows_unknown=True" in dossier
    assert "116 passed in 15.69s" in dossier
    assert "ac665b945a2cfbadaa7672855219e624d7eca45e" in dossier
    assert "5198275a640ebc42eed5d151aa51a3047f7d4726" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/55" in dossier
    assert "31643363586" in dossier
    assert "4dccce3877d4b8d715efb7ab8212ff1ee0bff1a2" in dossier
    assert "31644174160" in dossier
    assert "df5fee5b97e4c0613327043a71bc665eacf46aa1" in dossier
    assert "31646282269" in dossier
    assert "LOCAL_READY / PUBLICATION_PENDING" in dossier
    assert "docs/promote-f5.2" in dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/56" in dossier
    assert "73fb40d14f6405a5eea766bbc5bb9a3898077854" in dossier
    assert "811 passed, 5 skipped, 6 subtests passed" in dossier
    for dimension in (
        "role",
        "node_id",
        "workflow",
        "trust_mode",
        "tool",
        "operation",
        "path",
    ):
        assert dimension in dossier
    assert "default-deny" in dossier
    assert "TOOL_CALLED" in dossier
    assert "F5.3" in dossier
    assert "F5.6" in dossier
    assert "docs/tasks/completed/F5.2.md" in panel
    assert "completed/F5.2.md" in task_index
    assert "F5.2 foi promovida pelo" in readme


def test_f5_3_promotion_preserves_the_frozen_trust_boundary() -> None:
    panel = _read(TASK_PANEL)
    dossier = _read(COMPLETED_ROOT / "F5.3.md")
    task_index = _read(TASKS_INDEX)
    readme = _read(ROOT / "README.md")

    assert not (ACTIVE_ROOT / "F5.3.md").exists()
    assert (COMPLETED_ROOT / "F5.3.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "checkpoint/f5.3-ready" in dossier
    assert "task/f5.3-trust-boundary" in dossier
    assert "0607a0b385da1a864f629bf4811810a574d03768" in dossier
    assert "31650131258" in dossier
    assert "marker_only_trusted=(True, 'trusted', True, True)" in dossier
    assert "101 passed, 2 skipped" in dossier
    for boundary in (
        "imports",
        "comandos",
        "worktree",
        "hooks",
        "promoção",
        "secrets",
    ):
        assert boundary in dossier
    assert "default-restricted" in panel
    assert "marcador" in dossier
    assert "ApprovalStatus.APPROVED" in dossier
    assert "PathGuard" in dossier
    assert "shell=False" in dossier
    assert "F5.4" in dossier
    assert "F5.7" in dossier
    assert "docs/tasks/completed/F5.3.md" in panel
    assert "completed/F5.3.md" in task_index
    assert "F5.3 foi promovida pelo" in readme
    assert "283 passed, 2 skipped" in readme
    assert "implementação local autorizada" in dossier
    assert "827 passed, 5 skipped, 6 subtests passed" in dossier
    assert "administrativo #56 / merge `0607a0b` / pós-merge `31650131258`" in task_index
    assert "4934aee925830e4aac2672b0bbf6ffadbf1c9ca9" in dossier
    assert "31659293351" in dossier
    assert "211edcf921912a32429934bf600473d8cc98941c" in dossier
    assert "31660030240" in dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/58" in dossier
    assert "7b7af9ea2512e1ea9a606053e39ae43678c83b39" in dossier
    assert "docs/promote-f5.3" in dossier


def test_f5_4_promotion_preserves_durable_execution_and_node_budget() -> None:
    panel = _read(TASK_PANEL)
    dossier = _read(COMPLETED_ROOT / "F5.4.md")
    task_index = _read(TASKS_INDEX)
    readme = _read(ROOT / "README.md")

    assert not (ACTIVE_ROOT / "F5.4.md").exists()
    assert (COMPLETED_ROOT / "F5.4.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "checkpoint/f5.4-ready" in dossier
    assert "task/f5.4-durable-budget" in dossier
    assert "4c0527baacc74821112adf7fe61b82af72589f69" in dossier
    assert "31728438719" in dossier
    assert "161 passed" in dossier
    for dimension in (
        "prompt tokens",
        "completion tokens",
        "tool calls",
        "duração",
        "tentativas",
        "custo estimado",
    ):
        assert dimension in dossier
    assert "fresh_tracker_consumed= 0" in dossier
    assert "FAILED_BUDGET_EXCEEDED" in dossier
    assert "write-ahead" in dossier
    assert "fencing token" in dossier
    assert "resume_neither_resets_nor_double_charges" in dossier
    assert "f4_8_specific_budget_remains_and_stricter_limit_wins" in dossier
    assert "F5.5" in dossier
    assert "F5.7" in dossier
    assert "docs/tasks/completed/F5.4.md" in panel
    assert "completed/F5.4.md" in task_index
    assert "F5.4 foi promovida pelo" in readme
    assert "202 passed" in dossier
    assert "856 passed, 5 skipped, 6 subtests passed" in dossier
    assert "checkpoint/f5.4-complete" in dossier
    assert "722916b0d5c9eddb0a06151894701e3f16e113aa" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/59" in dossier
    assert "0cb69b1d94bd650c69528777514c6f1b12478392" in dossier
    assert "21aa4a6134db38615eed8c11cc15285924a62365" in dossier
    assert "31739876952" in dossier
    assert "d6246295045a156646af14de0011400feb6cb4f3" in dossier
    assert "31742231398" in dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in dossier
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/60" in dossier
    assert "5521bf3cb6fc8cd84316183f9471a3d96d6dd368" in dossier
    assert "docs/promote-f5.4" in dossier
    assert "administrativo #58 / merge `4c0527b` / pós-merge `31728438719`" in task_index
    assert "administrativo #60 / merge `2f4e391` / pós-merge `31759971204`" in task_index


def test_f5_5_gate_freezes_secret_injection_and_redaction() -> None:
    panel = _read(TASK_PANEL)
    dossier = _read(COMPLETED_ROOT / "F5.5.md")
    task_index = _read(TASKS_INDEX)
    readme = _read(ROOT / "README.md")
    user_guide = _read(ROOT / "docs" / "user_guide.md")

    assert not (ACTIVE_ROOT / "F5.5.md").exists()
    assert (COMPLETED_ROOT / "F5.5.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "checkpoint/f5.5-ready" in dossier
    assert "checkpoint/f5.5-complete" in dossier
    assert "f4460ad" in dossier
    assert "F5.6 `PROMOTED`" in panel
    assert "docs/promote-f5.6" in panel
    assert "task/f5.5-secrets-redaction" in dossier
    assert "2f4e391bfe3588f713a436b051d4f60e970e4df1" in dossier
    assert "31759971204" in dossier
    assert "230 passed, 3 skipped" in dossier
    assert "192 passed, 3 skipped" in dossier
    assert "873 passed, 5 skipped, 6 subtests passed" in dossier
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/61" in dossier
    assert "31764961921" in dossier
    assert "31765166979" in dossier
    assert "2227b73131d405cde046c58ec83094889a3feb51" in dossier
    assert "31769631054" in dossier
    assert "73be828a6e4e813e9370eac7f4289179c7f05d79" in dossier
    assert "45f4fb7" in panel
    assert "daec37d119fced3a5e041c412ab01e7524c15800" in panel
    assert "31771169636" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/62" in dossier
    assert "31770610085" in dossier
    assert "RedactionContext" in dossier
    assert "'split_dynamic_secret_leaks': True" in dossier
    assert "'unscoped_runtime_redaction_leaks': True" in dossier
    assert "'legacy_adapter_reads_env_without_boundary': True" in dossier
    assert "'serena_repr_leaks_header': True" in dossier
    assert "only_the_authorized_adapter_receives_the_secret" in dossier
    assert "exact_multiline_line_wrapped_and_dynamic_values_are_redacted" in dossier
    assert "journal_logs_exceptions_stdout_stderr_retry_and_evidence_are_secret_free" in dossier
    assert "OPENAI_API_KEY" in dossier
    assert "HARNESS_LOCAL_MODEL_API_KEY" in dossier
    assert "SERENA_MCP_TOKEN" in dossier
    assert "provider:openai" in dossier
    assert "provider:local" in dossier
    assert "tool:serena" in dossier
    assert "rollback" in dossier.casefold()
    assert "docs/tasks/completed/F5.5.md" in panel
    assert "completed/F5.5.md" in task_index
    assert "F5.5" in readme
    assert "a F5.5 ainda precisa remover" not in readme
    for name, consumer in (
        ("OPENAI_API_KEY", "provider:openai"),
        ("HARNESS_LOCAL_MODEL_API_KEY", "provider:local"),
        ("SERENA_MCP_TOKEN", "tool:serena"),
    ):
        assert name in user_guide
        assert consumer in user_guide
    assert "instâncias existentes não fazem hot" in user_guide
    assert "reload silencioso" in user_guide


def test_f5_6_promoted_gate_binds_approval_to_the_exact_promotion_content() -> None:
    panel = _read(TASK_PANEL)
    dossier = _read(COMPLETED_ROOT / "F5.6.md")
    task_index = _read(TASKS_INDEX)
    readme = _read(ROOT / "README.md")
    user_guide = _read(ROOT / "docs" / "user_guide.md")

    assert not (ACTIVE_ROOT / "F5.6.md").exists()
    assert (COMPLETED_ROOT / "F5.6.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in panel
    assert "docs/promote-f5.6" in panel
    assert "7a1f6ed84947f8bd3326aca70b3e8aeaaf761f24" in panel
    assert "31816727870" in panel
    assert "a449bd19b5f6535402535bc2815527a9689095dc" in panel
    assert "31817497094" in panel
    assert "checkpoint/f5.6-ready" in dossier
    assert "161e1c26eb0aad6b81e25ebdcda4f12519486ba4" in dossier
    assert "7941dfee0384927acdb5d94cd9e626194b7b1432" in dossier
    assert "checkpoint/f5.6-complete" in dossier
    for field in (
        "execution ID",
        "artifact digest",
        "plan digest",
        "diff digest",
        "candidate commit SHA",
        "resultados dos gates",
        "approver ID",
        "timestamp da decisão",
    ):
        assert field in dossier
    assert "approval-request.json" in dossier
    assert "approval_request.json" in dossier
    assert "INVALIDATED" in dossier
    assert "EXPIRED" in dossier
    assert "47 passed" in dossier
    assert "885 passed, 5 skipped, 6 subtests passed" in dossier
    assert "uv 0.12.3" in dossier
    assert "38 passed, 6 subtests passed" in dossier
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/63" in dossier
    assert "31813471013" in dossier
    assert "048838076704fb852129b6ef76e9af6b7f878c35" in dossier
    assert "31814250746" in dossier
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/64" in dossier
    assert "31816395182" in dossier
    assert "F5.7" in dossier
    assert "F6" in dossier
    assert "docs/tasks/completed/F5.6.md" in panel
    assert "completed/F5.6.md" in task_index
    assert "885 passed, 5 skipped, 6 subtests passed" in readme
    assert "Aprovação de promoção vinculada ao conteúdo F5.6" in user_guide
    assert "não converte" in user_guide


def test_f5_7_promotion_preserves_r3_negative_evidence_and_certification() -> None:
    panel = _read(TASK_PANEL)
    dossier = _read(COMPLETED_ROOT / "F5.7.md")
    f5_c1_dossier = _read(COMPLETED_ROOT / "F5.C1.md")
    f6_1_dossier = _read(ACTIVE_ROOT / "F6.1.md")
    task_index = _read(TASKS_INDEX)
    readme = _read(ROOT / "README.md")

    assert not (ACTIVE_ROOT / "F5.7.md").exists()
    assert (COMPLETED_ROOT / "F5.7.md").is_file()
    assert "> **Gate:** `READY`" in dossier
    assert "> **Lifecycle:** `PROMOTED`" in dossier
    assert "docs/promote-f5.7" in panel
    assert "task/f5.7-safe-cancel-rollback" in dossier
    assert "a449bd19b5f6535402535bc2815527a9689095dc" in dossier
    assert "checkpoint/f5.7-ready" in panel
    assert "checkpoint/f5.7-ready" in dossier
    assert "checkpoint/f5.7-r1-ready" in panel
    assert "checkpoint/f5.7-r1-ready" in dossier
    assert "checkpoint/f5.7-complete" in panel
    assert "checkpoint/f5.7-complete" in dossier
    assert "checkpoint/f5.7-r3-ready" in dossier
    assert "26bb04d534dc8be5aae884f400d971ad66b6a9c1" in panel
    assert "26bb04d534dc8be5aae884f400d971ad66b6a9c1" in dossier
    assert "d787ce5f61f2e79415c76c06d928f030c026a4d8" in panel
    assert "d787ce5f61f2e79415c76c06d928f030c026a4d8" in dossier
    assert "runtime/tool_loop.py" in dossier
    assert "pós-dispatch" in dossier
    assert "cancellation-policy.json" in dossier
    assert "reconciliação" in dossier
    assert "LegacyShellCommandError" in dossier
    assert "90 passed, 2 skipped" in dossier
    for required in (
        "cancelamento durante comando",
        "git revert --no-edit",
        "BLOCKED_ROLLBACK",
        "git revert --abort",
        "cleanup-worktree",
        "hook destrutivo",
        "shell=False",
        "F5.2 policy",
        "F5.6 approval",
        "merge.evil.driver",
        "hook_approval_granted: bool",
        "exit_code=0",
        "COMPLETED_LOCAL / PROMOTION_PENDING",
    ):
        assert required in dossier
    assert "completed/F5.7.md" in task_index
    assert "31817497094" in panel
    assert "31817497094" in task_index
    assert "a449bd19b5f6535402535bc2815527a9689095dc" in panel
    assert "174 passed, 2 skipped" in panel
    assert "910 passed, 5 skipped, 6 subtests passed" in panel
    assert "998a7ac" in panel
    assert "998a7ac" in task_index
    assert "31849767573" in panel
    assert "31849767573" in task_index
    assert "F5.C1" in panel
    assert not (ACTIVE_ROOT / "F5.C1.md").exists()
    assert (COMPLETED_ROOT / "F5.C1.md").is_file()
    assert "completed/F5.C1.md" in task_index
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/65" in dossier
    assert "31845896973" in dossier
    assert "e8470ece8bdb7e98ddfe9817270d0b17032404d4" in dossier
    assert "31846634851" in dossier
    assert "b1cca8134b04671c27f18c9260fa098739f7415b" in dossier
    assert "PR #65" in readme
    assert "31846634851" in readme
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/66" in dossier
    assert "bb8d32ef7edc59006bf2b7ae1df6a0fa30639450" in dossier
    assert "31848981895" in dossier
    assert "PR #66" in readme
    assert "31849767573" in task_index
    assert "> **Gate:** `READY`" in f5_c1_dossier
    assert "> **Lifecycle:** `PROMOTED`" in f5_c1_dossier
    assert "> **Reconciliação administrativa:** `ADMIN_PR_OPEN / CHECKS_PENDING`" in f5_c1_dossier
    assert "checkpoint/f5.c1-ready" in f5_c1_dossier
    assert "checkpoint/f5.c1-complete" in f5_c1_dossier
    assert "ec8aa96" in f5_c1_dossier
    assert "5da7052" in f5_c1_dossier
    for result in (
        "36 passed em 2.17s",
        "35 passed, 6 subtests passed",
        "267 passed, 2 skipped em 173.65s",
        "914 passed, 5 skipped, 6 subtests passed em 328.79s",
    ):
        assert result in f5_c1_dossier
    assert "| **Gate** | `READY / REPAIR_ACTIVE / PROMOTION_BLOCKED` |" in panel
    assert "docs/tasks/active/F6.1.md" in panel
    assert (ACTIVE_ROOT / "F6.1.md").is_file()
    assert "active/F6.1.md" in task_index
    assert "96" in task_index
    for source in (panel, task_index, readme):
        assert "c9e41c4" in source
        assert "c4aef27" in source
        assert "320" in source
        assert "930" in source
    assert "REPAIR_ACTIVE / PROMOTION_BLOCKED" in task_index
    assert "REPAIR_ACTIVE / PROMOTION_BLOCKED" in f6_1_dossier
    assert "c4aef27" in f6_1_dossier
    assert "320" in f6_1_dossier
    assert "930" in f6_1_dossier
    assert "KnowledgeSyncEvent" in f6_1_dossier
    assert "KnowledgeUpdateEvent" in f6_1_dossier
    assert "registered_event_models ['ExecutionEvent']" in f6_1_dossier
    for source in (panel, f6_1_dossier):
        assert "checkpoint/f6.1-complete" in source
        assert "016f4ca" in source
    for historical_evidence in ("282 passed", "929 passed", "REPAIR_ACTIVE", "evidência negativa"):
        assert historical_evidence in f6_1_dossier
    for r2_evidence in (
        "stored_hash_matches_persisted_envelope False",
        "password:1234",
        "apiKey:false",
        "historical_canonical_refs_unresolved 4",
        "ContractNotFoundError",
        "checkpoint/f6.1-r2-ready",
    ):
        assert r2_evidence in f6_1_dossier
    assert "Fase 6" in panel
    for source in (panel, task_index, f5_c1_dossier, readme):
        assert "PR #67" in source or "pull/67" in source
        assert "3158d3b" in source
        assert "31855763587" in source
        assert "2b405fd" in source
        assert "31857239235" in source
    assert "31855627698" in f5_c1_dossier
    assert "7c41c520e11825c74cc8e95e9dd79c20532bc359" in f5_c1_dossier
    assert "7c41c520e11825c74cc8e95e9dd79c20532bc359" in panel
    assert "31858431821" in f5_c1_dossier
    for source in (panel, task_index, readme):
        assert "PR #68" in source or "pull/68" in source
        assert "5b8e558" in source
        assert "29e8a975" in source
        assert "31859624571" in source


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

    assert "DEC-012" in plan
    assert "DEC-012" in task_index
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
    assert "completed/F4.4.md" in task_index
    assert "Fases 0–4" in panel
    assert "F3.7 — promoção Git segura" in panel
    assert "Não restou achado blocker/high" in realignment
