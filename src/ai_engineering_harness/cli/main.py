"""Interface CLI unificada final com todos os subcomandos do AI-Engineering-Harness."""

import json
import shutil
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ai_engineering_harness import __version__
from ai_engineering_harness.cli.commands.rollback import RollbackManager
from ai_engineering_harness.compiler import GraphCompiler, GraphCompilerError
from ai_engineering_harness.compiler.visualizer import GraphVisualizer
from ai_engineering_harness.contracts import ExecutionState
from ai_engineering_harness.core import ConfigResolver
from ai_engineering_harness.doctor.checker import DoctorChecker
from ai_engineering_harness.doctor.report import DoctorReport
from ai_engineering_harness.indexer import PythonAstIndexer, StructuralIndexError
from ai_engineering_harness.observability.audit import AuditTrailManager
from ai_engineering_harness.persistence import AtomicFileStateStorage, StateStorageError
from ai_engineering_harness.runtime import (
    ExecutionLifecycleError,
    ExecutionLifecycleService,
    GraphExecutionError,
    GraphExecutionPausedResult,
    NodeExecutorError,
    NodeExecutorRegistry,
    StateMachineError,
)
from ai_engineering_harness.runtime.maf_adapter import ArtifactValidationError
from ai_engineering_harness.security import (
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
    TrustEvaluationResult,
)
from ai_engineering_harness.workspace import ExternalWorktreeManager

console = Console()


def _lifecycle_service(
    project_root: Path,
    *,
    project_id: str = "default-proj",
    trust_boundary: TrustEvaluationResult | None = None,
) -> ExecutionLifecycleService:
    """Build the canonical lifecycle with deliberately unavailable real backends."""
    boundary = trust_boundary or _cli_trust_boundary(project_root)
    worktrees = ExternalWorktreeManager(
        project_root,
        project_id,
        trust_boundary=boundary,
    )
    return ExecutionLifecycleService(
        project_root,
        AtomicFileStateStorage(project_root),
        NodeExecutorRegistry(),
        config_resolver=ConfigResolver(project_root),
        verification_worktree_provider=worktrees.load_worktree,
        trust_boundary=boundary,
    )


def _cli_trust_boundary(project_root: Path) -> TrustEvaluationResult:
    """Build the fixed host-owned capability projection used by CLI verification."""

    executable_aliases = (
        "bun",
        "cargo",
        "dotnet",
        "git",
        "go",
        "npm",
        "pnpm",
        "python",
        "yarn",
    )
    consumers = tuple(f"terminal:{alias}" for alias in executable_aliases)
    authorization = TrustAuthorization(
        repository_root=str(project_root.resolve(strict=True)),
        executable_aliases=executable_aliases,
        secret_grants=tuple(
            SecretGrant(name=name, consumers=consumers)
            for name in ("PATH", "Path", "SYSTEMROOT", "SystemRoot")
        ),
    )
    return TrustBoundaryEvaluator(
        project_root,
        authorization=authorization,
    ).evaluate()


def _parse_json_object(raw: str, *, option_name: str = "--input-json") -> dict[str, object]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{option_name} must be valid JSON") from exc
    if type(value) is not dict:
        raise click.ClickException(f"{option_name} must be a JSON object")
    return value


def _raise_lifecycle_click_error(exc: Exception) -> None:
    raise click.ClickException(str(exc)) from exc

def _get_symbol(success: bool) -> str:
    encoding = getattr(sys.stdout, "encoding", "") or ""
    supports_unicode = "utf" in encoding.lower()
    if success:
        return "✔ " if supports_unicode else "[OK] "
    return "✖ " if supports_unicode else "[FAIL] "

@click.group(help="AI-Engineering-Harness - Motor Agentic Autônomo e Instalável")
@click.version_option(version=__version__, prog_name="harness")
def main():
    pass

@main.command(help="Inicializa a estrutura .harness/ no repositório local.")
def init():
    harness_dir = Path.cwd() / ".harness"
    (harness_dir / "agents").mkdir(parents=True, exist_ok=True)
    (harness_dir / "graphs" / "specs").mkdir(parents=True, exist_ok=True)
    (harness_dir / "policies").mkdir(parents=True, exist_ok=True)
    (harness_dir / "tools").mkdir(parents=True, exist_ok=True)
    (harness_dir / "bmad" / "custom").mkdir(parents=True, exist_ok=True)
    (harness_dir / "bmad" / "graphs").mkdir(parents=True, exist_ok=True)
    (harness_dir / "knowledge" / "artifacts").mkdir(parents=True, exist_ok=True)
    (harness_dir / "contracts").mkdir(parents=True, exist_ok=True)
    (harness_dir / "state" / "compiled").mkdir(parents=True, exist_ok=True)
    (harness_dir / "state" / "executions").mkdir(parents=True, exist_ok=True)
    (harness_dir / "state" / "structural-index").mkdir(parents=True, exist_ok=True)
    (harness_dir / "state" / "worktree-references").mkdir(parents=True, exist_ok=True)
    (harness_dir / "artifacts" / "executions").mkdir(parents=True, exist_ok=True)

    defaults_dir = Path(__file__).resolve().parent.parent / "defaults"
    if defaults_dir.exists():
        for category, target in [("agents", harness_dir / "agents"), ("graphs", harness_dir / "graphs" / "specs"), ("policies", harness_dir / "policies"), ("tools", harness_dir / "tools")]:
            src_cat = defaults_dir / category
            if src_cat.exists():
                for item in src_cat.glob("*"):
                    dst_item = target / item.name
                    if item.is_file() and not dst_item.exists():
                        shutil.copy2(item, dst_item)
                    elif item.is_dir() and not dst_item.exists():
                        shutil.copytree(item, dst_item)

    project_yaml = harness_dir / "project.yaml"
    if not project_yaml.exists():
        project_yaml.write_text("language: python\nframework: pytest\n", encoding="utf-8")

    console.print(f"[green]{_get_symbol(True)}[/green]Estrutura [bold].harness/[/bold] inicializada com sucesso.")

@main.command(help="Executa os probes de diagnóstico de saúde em 6 estágios.")
def doctor():
    console.print("[bold blue]harness doctor[/bold blue] - Executando Probes Seguros de Saúde...")
    checker = DoctorChecker(config={})
    results = checker.check_all()
    DoctorReport.render(results)

@main.command(help="Compila um grafo YAML no artefato tipado canônico.")
@click.argument("graph_spec_path", type=click.Path(exists=True, path_type=Path))
@click.option("--workflow", default=None, help="Nome do workflow; deve coincidir com graph.name.")
@click.option("--render", is_flag=True, help="Exibe o diagrama Mermaid visual do grafo.")
def compile(graph_spec_path, workflow, render):
    try:
        project_root = Path.cwd()
        compiler = GraphCompiler(
            project_root=project_root,
            trust_boundary=_cli_trust_boundary(project_root),
        )
        out_file = compiler.compile_graph(graph_spec_path, workflow)
    except GraphCompilerError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]{_get_symbol(True)}[/green]Grafo compilado com sucesso em: [bold]{out_file}[/bold]")

    if render:
        mermaid_code = GraphVisualizer.render_mermaid(graph_spec_path)
        console.print("\n[bold magenta]Diagrama Mermaid do Grafo:[/bold magenta]")
        console.print(f"```mermaid\n{mermaid_code}\n```")

@main.command(help="Reconstrói e valida o índice estrutural Python do commit Git atual.")
def index():
    indexer = PythonAstIndexer(project_root=Path.cwd())
    try:
        snapshot = indexer.rebuild("HEAD")
    except StructuralIndexError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        f"[green]{_get_symbol(True)}[/green]Índice estrutural reconstruído e validado. "
        f"Commit: {snapshot.commit_sha}. Símbolos: {len(snapshot.symbols)}"
    )

@main.command(help="Executa um workflow agentic autônomo.")
@click.argument("workflow_name")
@click.option("--approval-required", is_flag=True, help="Requer aprovação humana prévia para promoção.")
@click.option(
    "--input-json",
    default="{}",
    show_default=True,
    help="Objeto JSON usado como input inicial canônico.",
)
@click.option(
    "--profile",
    "profile_name",
    default="default",
    show_default=True,
    help="Perfil de configuração efetiva selecionado.",
)
@click.option(
    "--config-json",
    default=None,
    help="Objeto JSON de overrides com a maior precedência de configuração.",
)
def run(workflow_name, approval_required, input_json, profile_name, config_json):
    project_root = Path.cwd()
    trust_boundary = _cli_trust_boundary(project_root)
    if approval_required:
        raise click.ClickException(
            "--approval-required is unsupported; approval is declared by an explicit human node"
        )
    initial_input = _parse_json_object(input_json)
    cli_overrides = (
        None
        if config_json is None
        else _parse_json_object(config_json, option_name="--config-json")
    )
    try:
        compiler = GraphCompiler(
            project_root=project_root,
            trust_boundary=trust_boundary,
        )
        compiled_file = compiler.compiled_path(workflow_name)
        if not compiled_file.is_file():
            spec_path = project_root / ".harness" / "graphs" / "specs" / f"{workflow_name}.yaml"
            if not spec_path.is_file():
                raise click.ClickException(
                    f"Workflow '{workflow_name}' não possui artefato compilado nem spec em "
                    f".harness/graphs/specs/{workflow_name}.yaml"
                )
            compiled_file = compiler.compile_graph(spec_path, workflow_name)
    except GraphCompilerError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        service = _lifecycle_service(
            project_root,
            trust_boundary=trust_boundary,
        )
        result = service.start(
            compiled_file,
            initial_input=initial_input,
            profile_name=profile_name,
            cli_overrides=cli_overrides,
        )
    except (
        ArtifactValidationError,
        ExecutionLifecycleError,
        GraphExecutionError,
        NodeExecutorError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)

    if isinstance(result, GraphExecutionPausedResult):
        console.print(
            f"[yellow]Execução {result.execution_id} pausada para aprovação "
            f"no node {result.node_id}.[/yellow]"
        )
        return
    current_state = service.status(result.execution_id).current_state
    if current_state == ExecutionState.VERIFYING:
        console.print(
            f"[yellow]Workflow {workflow_name} concluiu a travessia e aguarda verificação "
            f"canônica. Execution ID: [bold cyan]{result.execution_id}[/bold cyan].[/yellow]"
        )
        return
    console.print(
        f"[green]{_get_symbol(True)}[/green]Workflow {workflow_name} concluído. "
        f"Execution ID: [bold cyan]{result.execution_id}[/bold cyan]; "
        f"outcome: [bold]{result.outcome}[/bold]."
    )

@main.command(help="Consulta o status em tempo real de uma execução.")
@click.argument("execution_id")
def status(execution_id):
    try:
        view = _lifecycle_service(Path.cwd()).status(execution_id)
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    table = Table(title=f"Status da Execução {execution_id}")
    table.add_column("Campo", style="cyan")
    table.add_column("Valor", style="bold green")
    table.add_row("Execution ID", view.execution_id)
    table.add_row("Workflow", view.workflow_name)
    table.add_row("Current node", view.current_node_id)
    table.add_row("FSM State", view.current_state.value)
    table.add_row("Approval", view.approval_status.value)
    table.add_row("Revision", str(view.revision))
    table.add_row("Última Atualização", view.updated_at.isoformat())
    console.print(table)

@main.command(help="Inspeciona os detalhes e o histórico de uma execução.")
@click.argument("execution_id")
def inspect(execution_id):
    try:
        view = _lifecycle_service(Path.cwd()).inspect(execution_id)
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    console.print(f"[bold cyan]Inspeção da Execução {execution_id}:[/bold cyan]")
    console.print(f"  - [bold]Estado FSM:[/bold] {view.status.current_state.value}")
    console.print(f"  - [bold]Node atual:[/bold] {view.status.current_node_id}")
    console.print(f"  - [bold]Aprovação:[/bold] {view.status.approval_status.value}")
    console.print(f"  - [bold]Artifact digest:[/bold] {view.artifact_digest}")
    console.print(f"  - [bold]Configuration digest:[/bold] {view.configuration_digest}")
    console.print(f"  - [bold]Initial input digest:[/bold] {view.initial_input_digest}")
    console.print(f"  - [bold]Eventos:[/bold] {view.event_count}")
    console.print(f"  - [bold]Tipos de evento:[/bold] {', '.join(view.event_types)}")

@main.command(help="Aprova manualmente a promoção de alterações em estado AWAITING_APPROVAL.")
@click.argument("execution_id")
@click.option("--approver", required=True, help="Identificador não vazio do aprovador.")
def approve(execution_id, approver):
    try:
        record = _lifecycle_service(Path.cwd()).approve(
            execution_id,
            approver=approver,
        )
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    console.print(
        f"[green]{_get_symbol(True)}[/green]Execução [bold]{execution_id}[/bold] "
        f"aprovada na revisão {record.revision}."
    )


@main.command(help="Retoma uma execução exclusivamente de seu bundle canônico.")
@click.argument("execution_id")
def resume(execution_id):
    try:
        result = _lifecycle_service(Path.cwd()).resume(execution_id)
    except (
        ArtifactValidationError,
        ExecutionLifecycleError,
        GraphExecutionError,
        NodeExecutorError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    if isinstance(result, GraphExecutionPausedResult):
        console.print(
            f"[yellow]Execução {execution_id} permanece pausada no node "
            f"{result.node_id}.[/yellow]"
        )
        return
    console.print(
        f"[green]{_get_symbol(True)}[/green]Execução [bold]{execution_id}[/bold] "
        f"concluída com outcome {result.outcome}."
    )


@main.command(help="Cancela uma execução cancelável sob o lock canônico.")
@click.argument("execution_id")
def cancel(execution_id):
    try:
        record = _lifecycle_service(Path.cwd()).cancel(execution_id)
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    console.print(
        f"[green]{_get_symbol(True)}[/green]Execução [bold]{execution_id}[/bold] "
        f"cancelada na revisão {record.revision}."
    )

@main.command(help="Executa gates configurados em um worktree validado.")
@click.argument("execution_id")
@click.option("--project-id", default="default-proj", show_default=True)
def verify(execution_id: str, project_id: str) -> None:
    try:
        result = _lifecycle_service(
            Path.cwd(),
            project_id=project_id,
        ).verify(execution_id)
    except (
        ArtifactValidationError,
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    if not result.all_passed:
        raise click.ClickException(
            "verificação bloqueou a conclusão: "
            f"{result.passed_gates}/{result.total_gates} gates aprovados"
        )
    console.print(
        f"[green]Verificação persistida. Aprovados: "
        f"{result.passed_gates}/{result.total_gates}[/green]"
    )

@main.command(help="Valida a integridade da Hash Chain dos logs de auditoria.")
@click.argument("execution_id")
@click.option("--export", type=click.Choice(["sarif", "json"], case_sensitive=False), help="Exporta os logs de auditoria no formato selecionado.")
def audit(execution_id, export):
    audit_mgr = AuditTrailManager(project_root=Path.cwd(), execution_id=execution_id)
    is_valid, msg = audit_mgr.verify_integrity()

    if export:
        if export.lower() == "sarif":
            out = audit_mgr.export_sarif()
        else:
            out = audit_mgr.export_json()
        console.print(out)
        return

    if is_valid:
        console.print(f"[green]{_get_symbol(True)}[/green][bold]AUDIT SUCCESS:[/bold] {msg}")
    else:
        console.print(f"[red]{_get_symbol(False)}[/red][bold]AUDIT FAILURE:[/bold] {msg}")

@main.command(help="Executa a reversão controlada em duas fases (Código / Efeitos).")
@click.argument("execution_id")
@click.option("--promoted", is_flag=True, help="Indica se a alteração já foi promovida.")
def rollback(execution_id, promoted):
    mgr = RollbackManager(project_root=Path.cwd())
    res = mgr.execute_rollback(execution_id=execution_id, is_promoted=promoted)
    console.print(f"[yellow]Rollback executado:[/yellow] {res['code_message']}")

if __name__ == "__main__":
    main()
