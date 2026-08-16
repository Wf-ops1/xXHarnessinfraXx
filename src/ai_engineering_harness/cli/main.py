"""Interface CLI unificada final com todos os subcomandos do AI-Engineering-Harness."""

import json
import shutil
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ai_engineering_harness import __version__
from ai_engineering_harness.compiler import GraphCompiler, GraphCompilerError
from ai_engineering_harness.compiler.visualizer import GraphVisualizer
from ai_engineering_harness.contracts import ExecutionState
from ai_engineering_harness.core import ConfigResolver
from ai_engineering_harness.doctor.checker import DoctorChecker
from ai_engineering_harness.doctor.report import DoctorReport
from ai_engineering_harness.indexer import PythonAstIndexer, StructuralIndexError
from ai_engineering_harness.observability import EvidenceError
from ai_engineering_harness.observability.audit import AuditTrailError, AuditTrailManager
from ai_engineering_harness.persistence import AtomicFileStateStorage, StateStorageError
from ai_engineering_harness.runtime import (
    ExecutionLifecycleError,
    ExecutionLifecycleService,
    ExecutionNextAction,
    GraphExecutionError,
    GraphExecutionPausedResult,
    NodeExecutorError,
    NodeExecutorRegistry,
    RollbackManager,
    StateMachineError,
)
from ai_engineering_harness.runtime.maf_adapter import ArtifactValidationError
from ai_engineering_harness.security import (
    Redactor,
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
    TrustEvaluationResult,
)
from ai_engineering_harness.workspace import ExternalWorktreeManager

console = Console()

_FOLLOW_TERMINAL_STATES = frozenset(
    {
        ExecutionState.BLOCKED_ROLLBACK,
        ExecutionState.COMPENSATED,
        ExecutionState.DRY_RUN_COMPLETED,
        ExecutionState.COMPLETED,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
        ExecutionState.FAILED_BUDGET_EXCEEDED,
        ExecutionState.FAILED_RETRY_EXHAUSTED,
    }
)


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
    rollbacks = RollbackManager(
        project_root,
        trust_boundary=boundary,
    )
    return ExecutionLifecycleService(
        project_root,
        AtomicFileStateStorage(project_root),
        NodeExecutorRegistry(),
        config_resolver=ConfigResolver(project_root),
        verification_worktree_provider=worktrees.load_worktree,
        trust_boundary=boundary,
        worktree_manager=worktrees,
        rollback_manager=rollbacks,
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
    raise click.ClickException(Redactor.redact_text(str(exc))) from exc


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )


def _next_action_text(execution_id: str, action: ExecutionNextAction) -> str:
    actions = {
        ExecutionNextAction.NONE: "none",
        ExecutionNextAction.RESUME: f"harness resume {execution_id}",
        ExecutionNextAction.VERIFY: f"harness verify {execution_id}",
        ExecutionNextAction.APPROVE: (
            f"harness approve {execution_id} --approver <identifier>"
        ),
        ExecutionNextAction.INSPECT: f"harness inspect {execution_id}",
        ExecutionNextAction.MANUAL_INTERVENTION: "manual intervention required",
    }
    return actions[action]


def _add_status_rows(table: Table, view) -> None:
    table.add_row("Schema", view.status_schema_version)
    table.add_row("Execution ID", view.execution_id)
    table.add_row("Workflow", view.workflow_name)
    table.add_row("Current node", view.current_node_id)
    table.add_row("FSM State", view.current_state.value)
    table.add_row("Approval", view.approval_status.value)
    table.add_row("Created", view.created_at.isoformat())
    table.add_row("Revision", str(view.revision))
    table.add_row("Updated", view.updated_at.isoformat())
    table.add_row("Current attempt", str(view.current_attempt))
    table.add_row("Persisted duration (ms)", str(view.duration_ms))
    if view.blocker is None:
        table.add_row("Blocker", "none")
    else:
        table.add_row("Blocker", f"{view.blocker.code}: {view.blocker.message}")
    table.add_row(
        "Next action",
        _next_action_text(view.execution_id, view.next_action),
    )

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

@main.command(help="Executa probes reais e somente leitura em 6 estágios.")
@click.option("--json", "json_output", is_flag=True, help="Emite o relatório tipado em JSON.")
@click.option("--workflow", default=None, help="Resolve os gates requeridos pelo workflow sem executá-los.")
def doctor(json_output: bool, workflow: str | None) -> None:
    checker = DoctorChecker(
        project_root=Path.cwd(),
        workflow=workflow,
    )
    report = checker.check()
    if json_output:
        click.echo(DoctorReport.to_json(report))
    else:
        console.print("[bold blue]harness doctor[/bold blue] - read-only health probes")
        DoctorReport.render(report)
    if not report.is_healthy:
        raise click.exceptions.Exit(1)

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

@main.command(name="list", help="Lista o catálogo canônico de execuções locais.")
def list_executions():
    try:
        views = _lifecycle_service(Path.cwd()).list_executions()
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    if not views:
        console.print("Nenhuma execução encontrada.")
        return
    click.echo("execution_id\tworkflow\tstate\tcurrent_node\tattempt\tupdated_at")
    for view in views:
        click.echo(
            "\t".join(
                (
                    view.execution_id,
                    view.workflow_name,
                    view.current_state.value,
                    view.current_node_id,
                    str(view.current_attempt),
                    view.updated_at.isoformat(),
                )
            )
        )


@main.command(help="Consulta o status canônico de uma execução.")
@click.argument("execution_id")
@click.option("--json", "as_json", is_flag=True, help="Emite a projeção tipada em JSON.")
def status(execution_id, as_json):
    try:
        view = _lifecycle_service(Path.cwd()).status(execution_id)
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    if as_json:
        click.echo(_canonical_json(view.model_dump(mode="json")))
        return
    table = Table(title=f"Status da Execução {execution_id}")
    table.add_column("Campo", style="cyan")
    table.add_column("Valor", style="bold green")
    _add_status_rows(table, view)
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
    console.print(
        f"  - [bold]Status schema:[/bold] {view.status.status_schema_version}"
    )
    console.print(f"  - [bold]Estado FSM:[/bold] {view.status.current_state.value}")
    console.print(f"  - [bold]Node atual:[/bold] {view.status.current_node_id}")
    console.print(f"  - [bold]Aprovação:[/bold] {view.status.approval_status.value}")
    console.print(f"  - [bold]Criada em:[/bold] {view.status.created_at.isoformat()}")
    console.print(f"  - [bold]Atualizada em:[/bold] {view.status.updated_at.isoformat()}")
    console.print(f"  - [bold]Tentativa atual:[/bold] {view.status.current_attempt}")
    console.print(f"  - [bold]Duração persistida (ms):[/bold] {view.status.duration_ms}")
    blocker = (
        "none"
        if view.status.blocker is None
        else f"{view.status.blocker.code}: {view.status.blocker.message}"
    )
    console.print(f"  - [bold]Bloqueador:[/bold] {blocker}")
    console.print(
        "  - [bold]Próxima ação:[/bold] "
        f"{_next_action_text(view.status.execution_id, view.status.next_action)}"
    )
    console.print(f"  - [bold]Artifact digest:[/bold] {view.artifact_digest}")
    console.print(f"  - [bold]Configuration digest:[/bold] {view.configuration_digest}")
    console.print(f"  - [bold]Initial input digest:[/bold] {view.initial_input_digest}")
    console.print(f"  - [bold]Eventos:[/bold] {view.event_count}")
    console.print(f"  - [bold]Tipos de evento:[/bold] {', '.join(view.event_types)}")


@main.command(help="Emite o journal canônico validado de uma execução em JSONL.")
@click.argument("execution_id")
@click.option(
    "--follow",
    is_flag=True,
    help="Emite somente novas sequências até a execução alcançar estado terminal.",
)
def events(execution_id, follow):
    emitted_count = 0
    try:
        service = _lifecycle_service(Path.cwd())
        while True:
            journal = service.events(execution_id)
            if len(journal) < emitted_count:
                raise click.ClickException("canonical journal sequence regressed")
            for event in journal[emitted_count:]:
                click.echo(event.canonical_json(), nl=False)
            emitted_count = len(journal)
            if not follow:
                return
            view = service.status(execution_id)
            if view.current_state in _FOLLOW_TERMINAL_STATES:
                final_journal = service.events(execution_id)
                if len(final_journal) < emitted_count:
                    raise click.ClickException("canonical journal sequence regressed")
                for event in final_journal[emitted_count:]:
                    click.echo(event.canonical_json(), nl=False)
                return
            time.sleep(1.0)
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)


@main.command(help="Verifica integralmente o manifesto de evidência terminal.")
@click.argument("execution_id")
@click.option(
    "--verify",
    is_flag=True,
    help="Exige record terminal, journal, manifesto, arquivos e digests íntegros.",
)
def evidence(execution_id, verify):
    if not verify:
        raise click.ClickException("--verify is required for evidence inspection")
    try:
        manifest = _lifecycle_service(Path.cwd()).verify_evidence(execution_id)
    except (
        EvidenceError,
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    table = Table(title=f"Evidência verificada {execution_id}")
    table.add_column("Campo", style="cyan")
    table.add_column("Valor", style="bold green")
    table.add_row("Execution ID", manifest.execution_id)
    table.add_row("Result", manifest.final_result)
    table.add_row("Journal sequence", str(manifest.journal_final_sequence))
    table.add_row("Journal hash", manifest.journal_final_hash)
    table.add_row("Verified files", str(len(manifest.files)))
    console.print(table)

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

@main.command(
    name="cleanup-worktree",
    help="Remove explicitamente um worktree limpo sem apagar sua branch.",
)
@click.argument("execution_id")
def cleanup_worktree(execution_id: str) -> None:
    try:
        reference = _lifecycle_service(Path.cwd()).cleanup_worktree(execution_id)
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    console.print(
        f"[green]{_get_symbol(True)}[/green]Worktree de [bold]{execution_id}[/bold] "
        f"removido com status {reference.status.value}; branch preservada."
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

@main.command(help="Valida o journal canônico tamper-evident local de uma execução.")
@click.argument("execution_id")
@click.option("--export", type=click.Choice(["sarif", "json"], case_sensitive=False), help="Exporta os logs de auditoria no formato selecionado.")
def audit(execution_id: str, export: str | None) -> None:
    try:
        audit_mgr = AuditTrailManager(
            project_root=Path.cwd(),
            execution_id=execution_id,
        )
        if export:
            out = (
                audit_mgr.export_sarif()
                if export.lower() == "sarif"
                else audit_mgr.export_json()
            )
            click.echo(out)
            return
        _, message = audit_mgr.verify_integrity()
    except AuditTrailError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(
        f"[green]{_get_symbol(True)}[/green][bold]AUDIT SUCCESS:[/bold] {message}"
    )

@main.command(help="Reverte o commit de promoção canônico vinculado à execução.")
@click.argument("execution_id")
def rollback(execution_id: str) -> None:
    try:
        record = _lifecycle_service(Path.cwd()).rollback(execution_id)
    except (
        ExecutionLifecycleError,
        StateMachineError,
        StateStorageError,
    ) as exc:
        _raise_lifecycle_click_error(exc)
    if record.current_state is not ExecutionState.COMPENSATED:
        raise click.ClickException(
            f"rollback bloqueado em {record.current_state.value}; nenhuma compensação foi declarada"
        )
    console.print(
        f"[green]{_get_symbol(True)}[/green]Rollback de [bold]{execution_id}[/bold] "
        f"encerrado em {record.current_state.value}."
    )

if __name__ == "__main__":
    main()
