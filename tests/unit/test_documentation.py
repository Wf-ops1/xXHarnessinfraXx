"""Regressões para o estado e a portabilidade da documentação."""

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_FILES = (
    ROOT / "README.md",
    ROOT / "TASK.md",
    ROOT / ".agents" / "AGENTS.md",
    *sorted((ROOT / "docs").rglob("*.md")),
)
CURRENT_CLAIM_FILES = tuple(
    document
    for document in MARKDOWN_FILES
    if "docs/tasks/completed" not in document.relative_to(ROOT).as_posix()
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)]+)\)")
FORBIDDEN_CURRENT_CLAIMS = (
    re.compile(r"(?im)^.*\bstatus\b.*\bem produção\b"),
    re.compile(r"(?i)\b100%\s+(?:operacional|funcional)\b"),
    re.compile(r"(?i)\baltamente robusto\b"),
    re.compile(r"(?i)\btotalmente revisado e encontra-se\b"),
)


def _read(document: Path) -> str:
    return document.read_text(encoding="utf-8", errors="strict")


def test_readme_contains_frozen_capability_matrix() -> None:
    readme = _read(ROOT / "README.md")

    assert "> **Status atual: Protótipo / Em desenvolvimento**" in readme
    assert "| Capacidade | Implementada | Experimental | Planejada |" in readme
    assert "adapters de modelos" in readme
    assert "candidate commit real e singular" in readme
    assert "git cherry-pick" in readme


def test_f73_quality_gate_guide_documents_every_fail_closed_gate() -> None:
    readme = _read(ROOT / "README.md")
    guide = _read(ROOT / "docs" / "quality_gates.md")

    assert "docs/quality_gates.md" in readme
    for contract in (
        "mypy --strict src",
        "--cov-branch",
        "check_f7_3_coverage.py",
        "check_f7_3_security.py secrets",
        "check_f7_3_security.py dependencies",
        "23 kernels",
        "80%",
        "CI required",
        "is_secret",
        "zero vulnerabilidade",
    ):
        assert contract in guide


def test_f66_recovery_matrix_has_exactly_nine_checkpoint_contracts() -> None:
    user_guide = _read(ROOT / "docs" / "user_guide.md")
    checkpoints = (
        "CP-01-worktree-created",
        "CP-02-context-saved",
        "CP-03-model-response",
        "CP-04-tool-call",
        "CP-05-candidate-commit",
        "CP-06-journal-append",
        "CP-07-approval",
        "CP-08-promotion",
        "CP-09-knowledge-transaction",
    )

    assert "## Matriz de recovery F6.6" in user_guide
    assert user_guide.count("| `CP-") == 9
    for checkpoint in checkpoints:
        assert user_guide.count(checkpoint) == 1
    for field in (
        "Estado persistido",
        "Operação idempotente",
        "Comportamento de `resume`",
        "Cleanup permitido",
        "Evidência",
    ):
        assert field in user_guide
    assert "`recovered`" in user_guide
    assert "`blocked_requires_intervention`" in user_guide
    assert "`known_gap_f6_7`" in user_guide
    assert "PREPARED → COMMITTED` sem staging/pointer" in user_guide


def test_f67_knowledge_recovery_contract_replaces_false_commit() -> None:
    user_guide = _read(ROOT / "docs" / "user_guide.md")

    assert "### Protocolo knowledge corrigido na F6.7" in user_guide
    assert "Um registro legado sem SHA, digest ou staging termina" in user_guide
    assert "`ABORTED`; ele nunca cria `current.json`" in user_guide
    assert "lock cross-processo e fencing token crescente" in user_guide
    assert "cleanup_retained_snapshots()" in user_guide
    assert "pointer/snapshot idênticos" in user_guide


def test_documents_do_not_claim_current_operational_readiness() -> None:
    for document in CURRENT_CLAIM_FILES:
        content = _read(document)
        assert "Em Produção" not in content, document
        for pattern in FORBIDDEN_CURRENT_CLAIMS:
            assert pattern.search(content) is None, (document, pattern.pattern)


def test_current_docs_recognize_real_worktree_without_claiming_full_integration() -> None:
    readme = _read(ROOT / "README.md")
    operating_model = _read(ROOT / "docs" / "agentic_operating_model.md")
    architecture = _read(ROOT / "docs" / "harness_architecture_spec.md")

    assert "Worktree é diretório comum" not in readme
    assert "cria diretório, não" not in readme
    assert "não chama `git worktree`" not in operating_model
    assert "| Workspace Git | `workspace/` | Simulada" not in architecture
    assert "lifecycle ainda não injeta automaticamente seu guard" in readme.casefold()
    assert "worktree git real ainda não está ligado" in operating_model.casefold()
    assert "Cria/valida worktree Git externo" in architecture


def test_current_docs_recognize_f3_8_tools_without_claiming_lifecycle_integration() -> None:
    readme = _read(ROOT / "README.md")
    operating_model = _read(ROOT / "docs" / "agentic_operating_model.md")
    architecture = _read(ROOT / "docs" / "harness_architecture_spec.md")

    assert "recebe string e usa" not in readme
    assert "terminal aceita comando como string" not in operating_model
    assert "terminal não cumpre contrato final" not in architecture
    assert "executa somente `argv`" in readme
    assert "factory opt-in" in readme.casefold()
    assert "registrations opt-in" in operating_model.casefold()
    assert "registry opt-in" in architecture.casefold()
    assert "ainda não constrói esse registry" in operating_model.casefold()


def test_current_docs_separate_tool_policy_from_content_bound_promotion() -> None:
    readme = _read(ROOT / "README.md")
    lifecycle = _read(ROOT / "docs" / "agentic_lifecycle_audit.md")
    user_guide = _read(ROOT / "docs" / "user_guide.md")
    walkthrough = _read(ROOT / "docs" / "walkthrough.md")

    for document in (readme, lifecycle, user_guide, walkthrough):
        assert "default-deny" in document
        assert "F5.2" in document
    for dimension in ("role", "node", "workflow", "trust", "tool", "operação", "path"):
        assert dimension in user_guide
    assert "lote inteiro" in user_guide
    assert "TOOL_CALLED" in user_guide
    assert "F5.3" in user_guide
    assert "F5.6" in user_guide
    assert "Aprovação de promoção vinculada ao conteúdo F5.6" in user_guide
    assert "approval-request.json" in user_guide
    assert "INVALIDATED" in user_guide
    assert "EXPIRED" in user_guide
    assert "não converte" in user_guide
    assert "não é construído automaticamente" in walkthrough


def test_current_docs_recognize_real_serena_without_claiming_live_default() -> None:
    readme = _read(ROOT / "README.md")
    operating_model = _read(ROOT / "docs" / "agentic_operating_model.md")

    assert "Serena apenas cria/toca arquivo" not in readme
    assert "Serena e Codebase-Memory não se conectam a MCP" not in operating_model
    assert "Streamable HTTP configurado" in readme
    assert "Serena possui cliente MCP explícito e opt-in" in operating_model
    assert "configuração e injeção live continuam externas e opt-in" in readme


def test_current_docs_recognize_f4_2_indexing_without_claiming_f4_3_or_mcp() -> None:
    readme = _read(ROOT / "README.md")
    lifecycle = _read(ROOT / "docs" / "agentic_lifecycle_audit.md")
    user_guide = _read(ROOT / "docs" / "user_guide.md")
    walkthrough_audit = _read(ROOT / "docs" / "walkthrough_audit.md")

    for document in (readme, lifecycle, user_guide, walkthrough_audit):
        assert "mock_ast" not in document
        assert "PythonAstIndexer" in document
    assert ".harness/state/structural-index/snapshots/<sha>.json" in user_guide
    assert "SHA/schema/status/digest validados" in lifecycle
    assert "consulta ausente/inválida continua falhando" in walkthrough_audit
    assert "F4.3/F4.4 produzem contexto e plano persistidos" in readme
    assert "backend MCP ainda não" in lifecycle


def test_public_state_docs_distinguish_real_primitives_from_missing_composition() -> None:
    readme = _read(ROOT / "README.md")
    panel = _read(ROOT / "TASK.md")
    lifecycle = _read(ROOT / "docs" / "agentic_lifecycle_audit.md")
    user_guide = _read(ROOT / "docs" / "user_guide.md")
    walkthrough = _read(ROOT / "docs" / "walkthrough.md")
    walkthrough_audit = _read(ROOT / "docs" / "walkthrough_audit.md")
    historical_audit = _read(ROOT / "docs" / "audit_report.md")

    readme = " ".join(readme.split())
    panel = " ".join(panel.split())
    lifecycle = " ".join(lifecycle.split())
    user_guide = " ".join(user_guide.split())
    walkthrough = " ".join(walkthrough.split())
    walkthrough_audit = " ".join(walkthrough_audit.split())
    historical_audit = " ".join(historical_audit.split())

    assert "PR #29" in readme
    assert "e6b5b84" in readme
    assert "31295594376" in readme
    assert "PR #30" in readme
    assert "c2aa89b" in readme
    assert "31316853244" in readme
    assert "A F4.1 foi promovida pelo PR #32" in readme
    assert "12ce3b7" in readme
    assert "31323952381" in readme
    assert "PR #33" in readme
    assert "571a8eb" in readme
    assert "31329231458" in readme
    assert "A F4.8 foi promovida pelo PR #49" in readme
    assert "A F3.7 foi promovida pelo PR #51" in readme
    assert "permanece obrigatória antes" not in readme
    assert "A F4.2 foi promovida pelo PR #34" in readme
    assert "212a9bf" in readme
    assert "31345231098" in readme
    assert "PR #35 no merge `3705693`" in readme
    assert "31346860397" in readme
    assert "A F4.3 preservou os gates R1–R6" in readme
    assert "passou na regressão local de 679 testes" in readme
    assert "PR #36 encerrou no head `84eda1c`" in readme
    assert "31414853048" in readme
    assert "merge `fa31ef8`" in readme
    assert "31419214233" in readme
    assert "PR #37" in readme
    assert "merge `5c8408d`" in readme
    assert "31433785637" in readme
    assert "PR #38 encerrou no head `fbdb6ee`" in readme
    assert "31442203348" in readme
    assert "merge `93ce4ce`" in readme
    assert "31445624269" in readme
    assert "`docs/promote-f4.4`" in readme
    assert "PR #39" in readme
    assert "merge `94641d2`" in readme
    assert "31447628152" in readme
    assert "POST_PROMOTION_BLOCKED" in readme
    assert "`harness verify`" in readme
    assert "typecheck/lint/unit_test/build/security_scan" in readme
    assert "runner `0/0` falham antes de subprocessos" in readme

    assert "F5.5 — integrar secrets e redaction no caminho crítico" in panel
    assert "F5.6 `PROMOTED`" in panel
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in panel
    assert "docs/promote-f5.6" in panel
    assert "F5.7 — cancelamento e rollback seguros" in panel
    assert "docs/promote-f5.7" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/65" in panel
    assert "31845896973" in panel
    assert "e8470ece8bdb7e98ddfe9817270d0b17032404d4" in panel
    assert "31846634851" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/66" in panel
    assert "bb8d32e" in panel
    assert "31848981895" in panel
    assert "998a7acaca46dc7f751798be4e2be9266d8028d1" in panel
    assert "31849767573" in panel
    assert "F5.C1" in panel
    assert "POST_PROMOTION_BLOCKED" in panel
    assert "docs/tasks/completed/F5.C1.md" in panel
    assert "2b405fdae5ea5560ce8e411297a0c11c4abc1bf9" in panel
    assert "31857239235" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/68" in panel
    assert "31858431821" in panel
    assert "5b8e5585f2fd729787589feeb0ed9f4d217e6e7f" in panel
    assert "29e8a9751c2cc1bf4e45fa530d971e969f22342f" in panel
    assert "31859624571" in panel
    assert "task/f6.1-unified-event-schema" in panel
    assert "docs/tasks/completed/F6.1.md" in panel
    assert "4c57a33e2df6ade006dffc184a5640298ae3a45a" in panel
    assert "31868906875" in panel
    assert "7d6a0e179f30008a7a67275da94878a179f0aba9" in panel
    assert "31887143905" in panel
    assert "| **Gate** | `COMPLETED_LOCAL / PRODUCT_COMMITTED_AWAITING_PUBLICATION_AUTHORIZATION` |" in panel
    assert "docs/tasks/active/F7.3.md" in panel
    assert "task/f7.3-quality-gates" in panel
    assert "docs/tasks/completed/F7.2.md" in panel
    assert "task/f7.2-test-matrix" in panel
    assert "1055 testes coletáveis" in panel
    assert "12 camadas/42 requisitos" in panel
    assert "bdae858861a9c5294f90a231115b3ed930030117" in panel
    assert "62 passed in 83.45s" in panel
    assert "1062 passed, 5 skipped, 6 subtests passed in 461.12s" in panel
    assert "09e0ee30e52e498b8fb8c3a128c2ffa5fc1ff6e8" in panel
    assert "PR #85" in panel
    assert "32038804579" in panel
    assert "53cafa5134c3af5f4d0a7497b3f44e996a6581dd" in panel
    assert "32039759737" in panel
    assert "docs/promote-f7.2" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/86" in panel
    assert "b40f25113362c1fe11362b69becc6c45c064b48d" in panel
    assert "32043891060" in panel
    assert "4e9f7a25ed47bb425eeefa3821ca2d051d4d8008" in panel
    assert "32045181204" in panel
    assert "85,61%" in panel
    assert "22 arcos" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/86" in readme
    assert "32045181204" in readme
    assert "docs/tasks/completed/F7.1.md" in panel
    assert "2ce104b687650587fa6881a88ea281dac22a83b3" in panel
    assert "1050 passed, 5 skipped, 6 subtests passed in 968.39s" in panel
    assert "PR #83" in panel
    assert "31984775704" in panel
    assert "a26807c030c7f099c5419ed5166a17cb46f4a2e4" in panel
    assert "31985232560" in panel
    assert "76f43dd29923c87e00062ca65afd534b5f4f1863" in panel
    assert "31985776520" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/84" in panel
    assert "197eb33b0d9c33a87a51cef38b4da39afc5588c6" in panel
    assert "31998528616" in panel
    assert "ceca850083fbbc2a6da54394054b09b6f335c9c7" in panel
    assert "31999182890" in panel
    assert "b46ebd9c84cacab6bd58d2fb2712879f6dabc164" in panel
    assert "32000365336" in panel
    assert "checkpoint/f6.4-complete" in panel
    assert "990 passed, 5 skipped, 6 subtests passed in 937.00s" in panel
    assert "31923378762" in panel
    assert "991 passed, 5 skipped, 6 subtests passed in 371.40s" in panel
    assert "docs/tasks/completed/F6.2.md" in panel
    assert "task/f6.2-harden-journal" in panel
    assert "ac887b055959d9d2c0c43b9b57df33e0d1eb9378" in panel
    assert "31888960272" in panel
    assert "146 passed in 27.87s" in panel
    assert "954 passed, 5 skipped, 6 subtests passed in 471.73s" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/71" in panel
    assert "31899279536" in panel
    assert "3f63428fba6223b8cb4a96f35fae609fbfffaa7f" in panel
    assert "31899659117" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/72" in panel
    assert "674cd9a4c9970f34394dfbd7a6ef677057245fc4" in panel
    assert "31901521807" in panel
    assert "d9e4010cc178b61a95754a0b4266c40d4a309638" in panel
    assert "31901668046" in panel
    assert "f5d2a3372a630d3ca1dabee1b02465fbde8da87d" in panel
    assert "31902119059" in panel
    assert "docs/tasks/completed/F6.3.md" in panel
    assert "docs/tasks/completed/F6.4.md" in panel
    assert "6e6ebb8b0871b3dd7d1a0bb80ec27704a2f389d9" in panel
    assert "31928606331" in panel
    assert "574df7a538e9a69cce13ce9ab10883241ef0350f" in panel
    assert "31929031317" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/76" in panel
    assert "8c6d2a8467a94de1ca1dbc102cbfca49bce0e8c5" in panel
    assert "31930029057" in panel
    assert "3c1f4d2862a8704d78397da8ebbbc7b31659b95a" in panel
    assert "31930869377" in panel
    assert "a42ec411f1a1516336abc1c5b1de57461a03c64d" in panel
    assert "31931649225" in panel
    assert "docs/tasks/completed/F6.5.md" in panel
    assert "7386638c76b3270ab9849337e6e429b8f29a9202" in panel
    assert "31936640635" in panel
    assert "c0491258ceab29785c97c2a4f1375d1f7d1f9645" in panel
    assert "31953772121" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/78" in panel
    assert "2dab988d9c84d43e7f43f73c35b9011ff64e79ab" in panel
    assert "31954547026" in panel
    assert "fcc927e9f70e2a00fe1b9973512401d22ad470a2" in panel
    assert "31955779575" in panel
    assert "638681638a341df9046f784b79140f4e40124032" in panel
    assert "31956649961" in panel
    assert "docs/tasks/completed/F6.6.md" in panel
    assert "1d5467457cf99c4ee34d69000630de1b1aa0900b" in panel
    assert "1030 passed, 5 skipped, 6 subtests passed in 765.28s" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/79" in panel
    assert "1ce953df5ad3db3764f44fc063cb617c18546d3c" in panel
    assert "31962221925" in panel
    assert "8be678946dc57244974caf5b485c33425a7466c3" in panel
    assert "31963338576" in panel
    assert "docs/promote-f6.6" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/80" in panel
    assert "06abef0637a8f6db91c5788c8e28148d81a765be" in panel
    assert "31967211097" in panel
    assert "43cb6ea48a2ee0148a9c9d63ec545d6d3e927ee5" in panel
    assert "31967664405" in panel
    assert "1327f299c2a748fdb3efb759291b67b39bd2598b" in panel
    assert "31968035375" in panel
    assert "docs/tasks/completed/F6.7.md" in panel
    assert "3fd5565d2308eecb667d9782f81b17be74040bd6" in panel
    assert "1049 passed, 5 skipped, 6 subtests passed in 394.77s" in panel
    assert "93f7bf20e8721e293b872f887ff6ef837b820e39" in panel
    assert "31977793119" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/82" in panel
    assert "5ee3fcc9e56df92b86a83a7a24b6c7bd57d413ce" in panel
    assert "31978357679" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/73" in panel
    assert "31913438082" in panel
    assert "1bd095a8f7c474b554a0a0cbd0a2be62448dc9b3" in panel
    assert "31913877551" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/74" in panel
    assert "c92597111f0c9ad11c01360f0348357c2fe379b2" in panel
    assert "31916819934" in panel
    assert "e557d46c2d3f9848ab39c289f9ace4f3c959b11c" in panel
    assert "31916987572" in panel
    assert "5b10b2d453768de62e9f64ae6d0095cfcd95cd03" in panel
    assert "31918043022" in panel
    assert "tamper-evident local" in readme
    assert "A F7.1 comprovou localmente o ciclo vertical" in readme
    assert "Prova vertical controlada F7.1" in user_guide
    assert "injeção de teste" in user_guide
    assert "PR #83" in readme
    assert "31985232560" in readme
    assert "31985776520" in readme
    assert "PR #84" in readme
    assert "31998528616" in readme
    assert "31999182890" in readme
    assert "32000365336" in readme
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/70" in panel
    assert "aae1aea7120d68aec1ccf3861b609f1a3880590b" in panel
    assert "31888260797" in panel
    assert "31817497094" in panel
    assert "a449bd19b5f6535402535bc2815527a9689095dc" in panel
    assert "docs/tasks/completed/F5.5.md" in panel
    assert "task/f5.5-secrets-redaction" in panel
    assert "2f4e391bfe3588f713a436b051d4f60e970e4df1" in panel
    assert "31759971204" in panel
    assert "230 passed, 3 skipped" in panel
    assert "192 passed, 3 skipped" in panel
    assert "873 passed, 5 skipped, 6 subtests passed" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/61" in panel
    assert "31765166979" in panel
    assert "2227b73131d405cde046c58ec83094889a3feb51" in panel
    assert "31769631054" in panel
    assert "https://github.com/Wf-ops1/xXHarnessinfraXx/pull/62" in panel
    assert "45f4fb7" in panel
    assert "daec37d119fced3a5e041c412ab01e7524c15800" in panel
    assert "31771169636" in panel
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/60" in panel
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/58" in panel
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/54" in panel
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/53" in panel
    assert "31629604755" in panel
    assert "31630446370" in panel
    assert "31633748837" in panel
    assert "31650131258" in panel
    assert "DEC-014" in panel
    assert "docs/tasks/completed/F5.3.md" in panel
    assert "docs/tasks/completed/F5.4.md" in panel
    assert "docs/tasks/completed/F5.2.md" in panel
    assert "docs/tasks/completed/F5.1.md" in panel
    assert "fe95a91648a79c404565583c87c1cf357e8ab3a2" in panel
    assert "F4.8" in panel
    assert "F3.7 — promoção Git segura" in panel
    assert "F5.1" in panel
    assert "checkpoint/f5.1-ready" in panel
    assert "checkpoint/f5.2-ready" in panel
    assert "checkpoint/f5.3-ready" in panel
    assert "checkpoint/f5.4-ready" in panel
    assert "checkpoint/f5.4-complete" in panel
    assert "checkpoint/f5.5-complete" in panel
    assert "f4460ad" in panel
    assert "https://github.com/Wf-ops1/Harnessinfra/pull/59" in panel
    assert "856 passed, 5 skipped, 6 subtests passed" in panel
    assert "FAILED_BUDGET_EXCEEDED" in user_guide
    assert "BUDGET_RESERVED" in user_guide
    assert "status`/`inspect" in walkthrough
    assert "certificar/arquivar a F3.8 no primeiro commit do gate seguinte" not in panel

    assert "OpenAI Responses e endpoint local fazem HTTP real" in lifecycle
    assert "Serena não é MCP" not in lifecycle
    assert "F5.7 `PROMOTED`" in lifecycle
    assert "git revert --no-edit" in lifecycle
    assert "F5.7 R3 está `PROMOTED`" in walkthrough
    assert "terminal usa `shell=True`" not in lifecycle
    assert "registry de executores vazio" in user_guide
    assert "harness resume <id>" in user_guide
    assert "Configuração efetiva F5.1" in user_guide
    assert "importlib.resources" in user_guide
    assert "não relê profile" in user_guide
    assert "context_request + graph_input" in user_guide
    assert "CONTEXT_EVALUATED" in user_guide
    assert "FAILED_RETRY_EXHAUSTED" in user_guide
    assert "on_failure` compilado" in user_guide
    assert "A F4.8 promovida" in user_guide
    assert "targeted → full" in lifecycle
    assert "F4.8 `PROMOTED`" in lifecycle
    assert "F3.7 `PROMOTED`" in lifecycle
    assert "cherry-pick único" in lifecycle
    assert "F4.8 promovida" in walkthrough
    assert "promoção F3.7 usa candidate/cherry-pick reais" in walkthrough
    assert "provider simulado" not in walkthrough
    assert "não existe worktree Git" not in walkthrough
    assert "Worktree real ausente" not in walkthrough_audit
    assert "Terminal recebe string e usa `shell=True`" not in walkthrough_audit
    assert "snapshot histórico da F0.5" in historical_audit
    assert "não representa o estado corrente" in historical_audit


def test_markdown_links_are_relative_and_resolve() -> None:
    for document in MARKDOWN_FILES:
        for match in MARKDOWN_LINK.finditer(_read(document)):
            raw_target = match.group("target").strip()
            if raw_target.startswith("<") and raw_target.endswith(">"):
                raw_target = raw_target[1:-1].strip()
            target = raw_target.split(maxsplit=1)[0]
            parsed = urlparse(target)

            if parsed.scheme in {"http", "https", "mailto"} or target.startswith("#"):
                continue

            assert parsed.scheme == "", (document, target)
            path_part = unquote(target.split("#", 1)[0])
            assert path_part, (document, target)
            resolved = (document.parent / path_part).resolve()
            assert resolved.exists(), (document, target, resolved)


def test_markdown_files_have_basic_structural_integrity() -> None:
    fence = chr(96) * 3
    for document in MARKDOWN_FILES:
        content = _read(document)
        assert content.startswith("# "), document
        assert content.endswith("\n"), document
        assert sum(line.startswith(fence) for line in content.splitlines()) % 2 == 0, document
