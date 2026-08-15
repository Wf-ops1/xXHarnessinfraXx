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
    assert "PROMOTED / ADMIN_LOCAL / PUBLICATION_PENDING" in panel
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
