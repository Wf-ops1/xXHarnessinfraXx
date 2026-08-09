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
    assert "worktree real ainda não está integrado" in readme.casefold()
    assert "worktree git real ainda não está ligado" in operating_model.casefold()
    assert "Cria/valida worktree Git externo" in architecture


def test_current_docs_recognize_safe_terminal_without_claiming_tool_integration() -> None:
    readme = _read(ROOT / "README.md")
    operating_model = _read(ROOT / "docs" / "agentic_operating_model.md")
    architecture = _read(ROOT / "docs" / "harness_architecture_spec.md")

    assert "recebe string e usa" not in readme
    assert "terminal aceita comando como string" not in operating_model
    assert "terminal não cumpre contrato final" not in architecture
    assert "executa somente `argv`" in readme
    assert "terminal seguro ainda não está registrado" in operating_model.casefold()
    assert "Terminal seguro existe como primitivo" in architecture


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
