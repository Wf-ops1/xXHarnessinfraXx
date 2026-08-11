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
    assert "SHA sintético" in readme


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
    assert "a F4.3 calcula seis dimensões" in readme
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
    assert "F3.7 continua dependente da F4.7" in readme
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
    assert "Suíte vazia/gate desconhecido podem passar `0/0`" in readme

    assert "`docs/promote-f4.c1`" in panel
    assert "F4.C1 `PROMOTED`" in panel
    assert "PR #40" in panel
    assert "65c54338b5753d31c0b0ed15ab6cf9ba1486f493" in panel
    assert "31453116947" in panel
    assert "3905d02d575fc177d917f605b7e1a9b6a658c818" in panel
    assert "31453662008" in panel
    assert "PR #41" in panel
    assert "39f7366" in panel
    assert "31454615745" in panel
    assert "POST_PROMOTION_BLOCKED" in panel
    assert "DEC-015" in panel
    assert "docs/tasks/completed/F4.4.md" in panel
    assert "docs/tasks/completed/F4.C1.md" in panel
    assert "nenhuma tarefa ativa de implementação" in panel
    assert "ADMIN_PR_OPEN / CHECKS_PENDING" in panel
    assert "702 passed, 2 skipped, 6 subtests passed" in panel
    assert "certificar/arquivar a F3.8 no primeiro commit do gate seguinte" not in panel

    assert "OpenAI Responses e endpoint local fazem HTTP real" in lifecycle
    assert "Serena não é MCP" not in lifecycle
    assert "terminal usa `shell=True`" not in lifecycle
    assert "registry de executores vazio" in user_guide
    assert "harness resume <id>" in user_guide
    assert "context_request + graph_input" in user_guide
    assert "CONTEXT_EVALUATED" in user_guide
    assert "FAILED_RETRY_EXHAUSTED" in user_guide
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
