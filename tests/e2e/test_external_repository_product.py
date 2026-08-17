"""F7.1 product proof through an installed wheel and one external Git repository."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_BASE_APPLICATION = '''"""Small external application used by the F7.1 product proof."""


def feature_status() -> str:
    return "baseline-ready"
'''

_BASE_TEST = '''from demo_app.core import feature_status


def test_feature_status_is_ready() -> None:
    assert feature_status().endswith("-ready")
'''

_BUILD_ENTRYPOINT = '''"""Deterministic offline entrypoint for the canonical build gate."""

from pathlib import Path

from fixture_backend import build_sdist, build_wheel


def main() -> None:
    distribution = Path("dist")
    distribution.mkdir(exist_ok=True)
    build_sdist(str(distribution))
    build_wheel(str(distribution))


if __name__ == "__main__":
    main()
'''

_PROJECT_TOML = '''[build-system]
requires = []
build-backend = "fixture_backend"
backend-path = ["."]

[project]
name = "f71-external-fixture"
version = "0.1.0"
requires-python = ">=3.11"

[tool.setuptools.packages.find]
include = ["demo_app*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-p no:cacheprovider"
pythonpath = ["."]

[tool.mypy]
strict = true
exclude = ['^\\.harness/', '^build/', '^dist/']

[tool.ruff]
exclude = [".harness", "build", "dist"]
'''

_BUILD_BACKEND = '''"""Network-free PEP 517 wheel backend for the external F7.1 fixture."""

from __future__ import annotations

import base64
import hashlib
import tarfile
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

_DISTRIBUTION = "f71_external_fixture"
_VERSION = "0.1.0"


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    del config_settings
    filename = f"{_DISTRIBUTION}-{_VERSION}.tar.gz"
    target = Path(sdist_directory) / filename
    archive_root = f"{_DISTRIBUTION}-{_VERSION}"
    included_paths = (
        "demo_app/__init__.py",
        "demo_app/core.py",
        "build.py",
        "fixture_backend.py",
        "pyproject.toml",
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for relative_path in included_paths:
            archive.add(
                relative_path,
                arcname=f"{archive_root}/{relative_path}",
                recursive=False,
            )
    return filename


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    del config_settings, metadata_directory
    filename = f"{_DISTRIBUTION}-{_VERSION}-py3-none-any.whl"
    target = Path(wheel_directory) / filename
    dist_info = f"{_DISTRIBUTION}-{_VERSION}.dist-info"
    files = {
        "demo_app/__init__.py": Path("demo_app/__init__.py").read_bytes(),
        "demo_app/core.py": Path("demo_app/core.py").read_bytes(),
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\\n"
            "Name: f71-external-fixture\\n"
            f"Version: {_VERSION}\\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\\n"
            b"Generator: f71-fixture-backend\\n"
            b"Root-Is-Purelib: true\\n"
            b"Tag: py3-none-any\\n"
        ),
    }
    records = []
    for path, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        records.append(f"{path},sha256={digest},{len(content)}")
    record_path = f"{dist_info}/RECORD"
    files[record_path] = ("\\n".join([*records, f"{record_path},,"]) + "\\n").encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as wheel:
        for path, content in sorted(files.items()):
            wheel.writestr(path, content)
    return filename
'''

_GITIGNORE = '''.harness/artifacts/
.harness/state/executions/
.harness/state/locks/
.harness/state/worktree-references/
.mypy_cache/
.pytest_cache/
.ruff_cache/
__pycache__/
*.egg-info/
*.pyc
build/
dist/
'''

_GRAPH = '''graph:
  name: new-feature
  graph_schema_version: "1.0"
  definition_version: "7.1.0"
  entrypoint: implement_feature
  status: stable
  description: "F7.1 installed-wheel product proof"
nodes:
  - id: implement_feature
    type: agent
    role: code_agent
    input_contract: contracts/nodes/code_generation.py#CodeGenerationInput
    output_contract: contracts/nodes/code_generation.py#CodeGenerationOutput
    tool_permissions:
      - tool: apply_patch
        effect: allow
    on_success: review_feature
    on_failure: failed
  - id: review_feature
    type: human_approval
    approval_strategy: explicit
    on_success: completed
    on_failure: failed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies:
  - policies/tool_policy.yaml
  - policies/verification_policy.yaml
contracts:
  - contracts/nodes/code_generation.py#CodeGenerationInput
  - contracts/nodes/code_generation.py#CodeGenerationOutput
'''

_TOOL_POLICY = '''policy_id: f71-tool-policy
policy_schema_version: "1.0"
definition_version: "7.1.0"
roles_permissions:
  code_agent:
    allowed_tools:
      - apply_patch
    forbidden_tools: []
  architecture_analyst:
    allowed_tools: []
    forbidden_tools: []
  knowledge_updater:
    allowed_tools: []
    forbidden_tools: []
  production_operator:
    allowed_tools: []
    forbidden_tools: []
  requirement_analyst:
    allowed_tools: []
    forbidden_tools: []
  security_agent:
    allowed_tools: []
    forbidden_tools: []
  test_agent:
    allowed_tools: []
    forbidden_tools: []
'''

_VERIFICATION_POLICY = '''policy_id: f71-verification-policy
policy_schema_version: "1.0"
definition_version: "7.1.0"
applies_to:
  - new-feature
required_gates:
  - id: typecheck
    executor: deterministic
    command: "python -m mypy ."
    blocking: true
  - id: lint
    executor: deterministic
    command: "python -m ruff check ."
    blocking: true
  - id: unit_test
    executor: deterministic
    command: "python -m pytest --maxfail=1 -p no:cacheprovider"
    blocking: true
  - id: build
    executor: deterministic
    command: "python -m build"
    blocking: true
termination_rule: ALL_REQUIRED_GATES_PASSED
on_failure: route_to_failure_classifier
'''

_TOOL_REGISTRY_ENTRY = '''
  - id: apply_patch
    description: Applies one digest-bound patch inside the authorized F7.1 worktree.
    capability_status: declared
'''

_RUNNER = r'''
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import ai_engineering_harness
from ai_engineering_harness.contracts import ApprovalStatus
from ai_engineering_harness.contracts.evidence import EvidenceApplicability
from ai_engineering_harness.contracts.execution import ExecutionState
from ai_engineering_harness.models import (
    CancellationToken,
    LLMResponse,
    ModelRouter,
    ModelToolConversation,
    ToolCall,
)
from ai_engineering_harness.observability.audit import AuditTrailManager
from ai_engineering_harness.persistence import AtomicFileStateStorage
from ai_engineering_harness.runtime import (
    APPROVAL_REQUESTED,
    CANDIDATE_COMMIT_RECORDED,
    EXECUTION_APPROVED,
    PROMOTION_APPROVAL_REQUESTED,
    PROMOTION_APPROVED,
    PROMOTION_COMPLETED,
    ROLLBACK_COMPLETED,
    AgentNodeExecutor,
    ExecutionLifecycleService,
    GraphExecutionPausedResult,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    PromotionManager,
    RollbackManager,
)
from ai_engineering_harness.runtime.agent_executor import AgentExecutor
from ai_engineering_harness.runtime.tool_loop import ToolLoopError
from ai_engineering_harness.security import (
    PathGuard,
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
)
from ai_engineering_harness.tools import build_operational_tool_router
from ai_engineering_harness.tools.adapters import LocalEditingAdapter
from ai_engineering_harness.workspace import ExternalWorktreeManager


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result


def response(*, index: int, calls: tuple[ToolCall, ...] = (), content: str = "") -> LLMResponse:
    return LLMResponse(
        content=content,
        provider="local",
        model_name="f71-deterministic-test-provider",
        tool_calls=calls,
        prompt_tokens=4,
        completion_tokens=2,
        total_tokens=6,
        request_id=f"f71-request-{index}",
        response_id=f"f71-response-{index}",
    )


class DeterministicTestProvider:
    """A scripted provider that exists only inside this generated test runner."""

    provider_id = "local"
    model_name = "f71-deterministic-test-provider"

    def __init__(self, *, expected_sha256: str) -> None:
        self.expected_sha256 = expected_sha256
        self.initial_calls = 0
        self.continuations = 0

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        del prompt, system_prompt, cancellation_token
        raise AssertionError("F7.1 must use the governed tool loop")

    def call_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        del prompt, system_prompt, cancellation_token
        assert [tool["name"] for tool in tools] == ["apply_patch"]
        self.initial_calls += 1
        assert self.initial_calls == 1
        patch = (
            "--- a/demo_app/core.py\n"
            "+++ b/demo_app/core.py\n"
            "@@ -2,4 +2,4 @@\n"
            " \n"
            " \n"
            " def feature_status() -> str:\n"
            "-    return \"baseline-ready\"\n"
            "+    return \"feature-ready\"\n"
        )
        return response(
            index=1,
            calls=(
                ToolCall(
                    call_id="f71-apply-feature",
                    name="apply_patch",
                    arguments={
                        "path": "demo_app/core.py",
                        "patch": patch,
                        "expected_sha256": self.expected_sha256,
                    },
                ),
            ),
        )

    def continue_tools(
        self,
        conversation: ModelToolConversation,
        tools: list[dict[str, Any]],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        del tools, cancellation_token
        self.continuations += 1
        assert self.continuations == 1
        tool_result = conversation.turns[-1].tool_results[-1]
        assert tool_result.call_id == "f71-apply-feature"
        assert tool_result.name == "apply_patch"
        return response(index=2, content="feature implemented through the governed tool router")

    def structured_output(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        del prompt, response_schema, cancellation_token
        raise AssertionError("F7.1 tool node does not request structured provider output")


class TestProviderRegistry:
    def __init__(self, provider: DeterministicTestProvider) -> None:
        self.provider = provider

    def is_configured(self, provider_id: str) -> bool:
        return provider_id == "local"

    def configured_model(self, provider_id: str) -> str:
        assert provider_id == "local"
        return self.provider.model_name

    def create_provider(self, provider_id: str) -> DeterministicTestProvider:
        assert provider_id == "local"
        return self.provider


class InstalledWheelAgentBackend:
    def __init__(
        self,
        *,
        worktree: Path,
        provider: DeterministicTestProvider,
        tool_boundary: object,
    ) -> None:
        router = ModelRouter(
            allowed_providers=("local",),
            provider_registry=TestProviderRegistry(provider),
            default_primary_provider="local",
        )
        path_guard = PathGuard(worktree)
        tool_router = build_operational_tool_router(
            ("apply_patch",),
            local_adapter=LocalEditingAdapter(path_guard=path_guard),
            trust_boundary=tool_boundary,
        )
        self.executor = AgentExecutor(
            "Amelia",
            router,
            tool_router=tool_router,
            project_root=worktree,
        )
        self.tool_boundary = tool_boundary

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        try:
            result = self.executor.execute_tool_loop(
                "Implement the approved F7.1 feature in demo_app/core.py.",
                artifact=context.artifact,
                node_id=context.node.id,
                max_tool_steps=2,
                tool_effect_recorder=context.tool_effect_recorder,
                trust_boundary=self.tool_boundary,
            )
        except ToolLoopError as exc:
            return NodeExecutionResult.failed(
                {},
                code="tool_loop_failed",
                message="governed tool loop did not complete",
                retryable=False,
                model_calls=exc.model_call_records,
                tool_executions=exc.tool_executions,
            )
        return NodeExecutionResult.completed(
            {
                "modified_files": ["demo_app/core.py"],
                "summary": result.final_response.content,
                "success": True,
            },
            model_calls=result.model_call_records,
            tool_executions=result.tool_executions,
        )


def run_gate(worktree: Path, *argv: str) -> None:
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(worktree)
        if not existing_pythonpath
        else os.pathsep.join((str(worktree), existing_pythonpath))
    )
    result = subprocess.run(
        list(argv),
        cwd=worktree,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"gate {argv!r} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def main() -> None:
    repository = Path(sys.argv[1]).resolve(strict=True)
    artifact = Path(sys.argv[2]).resolve(strict=True)
    installed_environment = Path(sys.argv[3]).resolve(strict=True)
    source_checkout = Path(sys.argv[4]).resolve(strict=True)
    initial_sha = sys.argv[5]
    configured_sha = sys.argv[6]

    package_origin = Path(ai_engineering_harness.__file__).resolve(strict=True)
    assert installed_environment in package_origin.parents
    assert source_checkout not in package_origin.parents
    assert git(repository, "rev-parse", "HEAD").stdout.strip().lower() == configured_sha
    original_branch = git(repository, "branch", "--show-current").stdout.strip()
    baseline_content = (repository / "demo_app" / "core.py").read_bytes()
    assert hashlib.sha256(baseline_content).hexdigest()
    assert "baseline-ready" in baseline_content.decode("utf-8")
    assert git(repository, "rev-parse", "HEAD^").stdout.strip().lower() == initial_sha

    secret_names = ("PATH", "Path", "SYSTEMROOT", "SystemRoot")
    repository_boundary = TrustBoundaryEvaluator(
        repository,
        authorization=TrustAuthorization(
            repository_root=str(repository),
            executable_aliases=("git", "python"),
            secret_grants=tuple(
                SecretGrant(name=name, consumers=("terminal:python",))
                for name in secret_names
            ),
            promotion_allowed=True,
        ),
    ).evaluate()
    assert repository_boundary.mode == "trusted"
    assert repository_boundary.promotion_allowed is True

    execution_id = "exec-f71-external-product"
    worktrees = ExternalWorktreeManager(
        repository,
        "f71-external-product",
        external_base_dir=repository.parent / "f71-worktrees",
        trust_boundary=repository_boundary,
    )
    provisioned = worktrees.create_worktree(
        execution_id,
        expected_base_commit_sha=configured_sha,
    )
    worktree = provisioned.worktree_path
    assert worktree != repository
    assert git(worktree, "rev-parse", "HEAD").stdout.strip().lower() == configured_sha

    tool_boundary = TrustBoundaryEvaluator(
        worktree,
        authorization=TrustAuthorization(repository_root=str(worktree)),
    ).evaluate()
    assert tool_boundary.mode == "trusted"
    provider = DeterministicTestProvider(
        expected_sha256=hashlib.sha256(baseline_content).hexdigest()
    )
    backend = InstalledWheelAgentBackend(
        worktree=worktree,
        provider=provider,
        tool_boundary=tool_boundary,
    )
    storage = AtomicFileStateStorage(repository)
    promotion_manager = PromotionManager(
        repository,
        worktrees,
        trust_boundary=repository_boundary,
    )
    lifecycle = ExecutionLifecycleService(
        repository,
        storage,
        NodeExecutorRegistry(agent=AgentNodeExecutor(backend)),
        git_identity_provider=lambda: (configured_sha, original_branch),
        verification_worktree_provider=worktrees.load_worktree,
        promotion_manager=promotion_manager,
        trust_boundary=repository_boundary,
        worktree_manager=worktrees,
        rollback_manager=RollbackManager(
            repository,
            trust_boundary=repository_boundary,
        ),
    )

    paused = lifecycle.start(
        artifact,
        execution_id=execution_id,
        initial_input={
            "requirement_id": "f71-installed-wheel-feature",
            "architecture_spec": {"module": "demo_app.core"},
            "affected_files": ["demo_app/core.py"],
            "retry_context": None,
        },
        configuration={},
    )
    assert isinstance(paused, GraphExecutionPausedResult)
    assert paused.node_id == "review_feature"
    assert provider.initial_calls == 1
    assert provider.continuations == 1
    changed_content = (worktree / "demo_app" / "core.py").read_bytes()
    assert changed_content != baseline_content
    assert "feature-ready" in changed_content.decode("utf-8")
    assert (repository / "demo_app" / "core.py").read_bytes() == baseline_content
    assert git(repository, "rev-parse", "HEAD").stdout.strip().lower() == configured_sha

    workflow_approved = lifecycle.approve(
        execution_id,
        approver="f71-workflow-reviewer",
    )
    assert workflow_approved.approval_status is ApprovalStatus.APPROVED
    resumed = lifecycle.resume(execution_id)
    assert resumed.outcome == "success"
    assert storage.load_execution(execution_id).current_state is ExecutionState.VERIFYING

    preliminary_gates = (
        (sys.executable, "-m", "mypy", "."),
        (sys.executable, "-m", "ruff", "check", "."),
        (sys.executable, "-m", "pytest", "--maxfail=1", "-p", "no:cacheprovider"),
        (sys.executable, "-m", "build"),
    )
    for gate in preliminary_gates:
        run_gate(worktree, *gate)
    assert git(worktree, "rev-parse", "HEAD").stdout.strip().lower() == configured_sha

    candidate = lifecycle.prepare_candidate(
        execution_id,
        message="feat: deliver installed-wheel F7.1 feature",
    )
    assert candidate.candidate_commit_sha is not None
    candidate_sha = candidate.candidate_commit_sha
    changed_paths = tuple(
        path
        for path in git(
            worktree,
            "show",
            "--pretty=format:",
            "--name-only",
            candidate_sha,
        ).stdout.splitlines()
        if path
    )
    assert changed_paths == ("demo_app/core.py",)
    assert (repository / "demo_app" / "core.py").read_bytes() == baseline_content

    suite = lifecycle.verify(execution_id)
    assert suite.all_passed is True
    assert suite.verified_commit_sha == candidate_sha
    assert tuple(result.gate_id for result in suite.gate_results) == (
        "typecheck",
        "lint",
        "unit_test",
        "build",
    )
    assert all(result.status == "PASSED" for result in suite.gate_results)

    request = lifecycle.request_promotion_approval(
        execution_id,
        reason="F7.1 candidate, diff and four gates reviewed",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert request.status is ApprovalStatus.PENDING
    approved = lifecycle.approve(
        execution_id,
        approver="f71-promotion-reviewer",
        comment="Exact candidate, diff, suite and promotion plan approved",
    )
    assert approved.approval_status is ApprovalStatus.APPROVED
    assert (repository / "demo_app" / "core.py").read_bytes() == baseline_content

    promoted = lifecycle.promote(execution_id)
    assert promoted.current_state is ExecutionState.COMPLETED
    assert promoted.promotion_commit_sha is not None
    promotion_sha = promoted.promotion_commit_sha
    assert git(repository, "branch", "--show-current").stdout.strip() == original_branch
    assert git(repository, "rev-parse", "HEAD").stdout.strip().lower() == promotion_sha
    assert git(repository, "rev-parse", "HEAD^").stdout.strip().lower() == configured_sha
    assert (repository / "demo_app" / "core.py").read_bytes() == changed_content
    promoted_parent_count = git(
        repository,
        "rev-list",
        "--parents",
        "-n",
        "1",
        promotion_sha,
    ).stdout.split()
    assert len(promoted_parent_count) == 2

    manifest = lifecycle.verify_evidence(execution_id)
    assert manifest.final_result == "PROMOTED"
    assert manifest.base_commit_sha == configured_sha
    assert manifest.promotion.status is EvidenceApplicability.RECORDED
    assert manifest.promotion.commit_sha == promotion_sha
    assert manifest.diff.status is EvidenceApplicability.RECORDED
    assert manifest.approval.status is ApprovalStatus.APPROVED
    assert tuple(gate.gate_id for gate in manifest.gates) == (
        "typecheck",
        "lint",
        "unit_test",
        "build",
    )
    assert all(gate.status == "PASSED" for gate in manifest.gates)
    assert tuple((model.provider, model.model) for model in manifest.models) == (
        ("local", "f71-deterministic-test-provider"),
    )

    audit = AuditTrailManager(repository, execution_id, storage=storage)
    verified, message = audit.verify_integrity()
    assert verified is True
    assert "tamper-evident local" in message
    events_before_rollback = audit.load_events()
    assert tuple(event.sequence_number for event in events_before_rollback) == tuple(
        range(1, len(events_before_rollback) + 1)
    )
    event_types = tuple(event.event_type for event in events_before_rollback)
    required_order = (
        "TOOL_CALLED",
        "TOOL_COMPLETED",
        APPROVAL_REQUESTED,
        EXECUTION_APPROVED,
        CANDIDATE_COMMIT_RECORDED,
        PROMOTION_APPROVAL_REQUESTED,
        PROMOTION_APPROVED,
        PROMOTION_COMPLETED,
    )
    positions = tuple(event_types.index(event_type) for event_type in required_order)
    assert positions == tuple(sorted(positions))

    compensated = lifecycle.rollback(execution_id)
    assert compensated.current_state is ExecutionState.COMPENSATED
    rollback_sha = git(repository, "rev-parse", "HEAD").stdout.strip().lower()
    assert rollback_sha not in {configured_sha, candidate_sha, promotion_sha}
    assert git(repository, "rev-parse", "HEAD^").stdout.strip().lower() == promotion_sha
    assert (repository / "demo_app" / "core.py").read_bytes() == baseline_content
    assert git(repository, "diff", "--exit-code", configured_sha, "HEAD", "--", "demo_app/core.py").returncode == 0
    events_after_rollback = audit.load_events()
    assert sum(event.event_type == ROLLBACK_COMPLETED for event in events_after_rollback) == 1
    assert audit.verify_integrity()[0] is True
    assert git(repository, "status", "--porcelain").stdout == ""

    cleanup = worktrees.cleanup_worktree(execution_id)
    assert cleanup.status.value == "REMOVED"
    assert not worktree.exists()

    print(
        json.dumps(
            {
                "artifact": str(artifact),
                "audit_events": len(events_after_rollback),
                "candidate_sha": candidate_sha,
                "configured_sha": configured_sha,
                "gate_ids": [result.gate_id for result in suite.gate_results],
                "initial_sha": initial_sha,
                "package_origin": str(package_origin),
                "promotion_sha": promotion_sha,
                "rollback_sha": rollback_sha,
                "state": compensated.current_state.value,
                "tool_calls": provider.initial_calls,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
'''


def _run(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
    timeout: float = 240.0,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed: {argv!r}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=repository)


def _uv_executable() -> str:
    configured = os.environ.get("HARNESS_TEST_UV")
    if configured:
        candidate = Path(configured)
        assert candidate.is_file(), configured
        return str(candidate)
    discovered = shutil.which("uv")
    assert discovered is not None, "F7.1 requires uv on PATH or HARNESS_TEST_UV"
    return discovered


@pytest.mark.parametrize("workflow", ["new-feature"])
def test_installed_wheel_delivers_promotes_audits_and_reverts_external_repository(
    tmp_path: Path,
    workflow: str,
) -> None:
    command_temp = tmp_path / "command-temp"
    command_temp.mkdir()
    command_environment = os.environ.copy()
    for variable in ("TEMP", "TMP", "TMPDIR"):
        command_environment[variable] = str(command_temp)
    repository = tmp_path / "external-repository"
    (repository / "demo_app").mkdir(parents=True)
    (repository / "tests").mkdir()
    (repository / "demo_app" / "__init__.py").write_text("", encoding="utf-8")
    (repository / "demo_app" / "core.py").write_text(_BASE_APPLICATION, encoding="utf-8")
    (repository / "tests" / "test_core.py").write_text(_BASE_TEST, encoding="utf-8")
    (repository / "build.py").write_text(_BUILD_ENTRYPOINT, encoding="utf-8")
    (repository / "fixture_backend.py").write_text(_BUILD_BACKEND, encoding="utf-8")
    (repository / "pyproject.toml").write_text(_PROJECT_TOML, encoding="utf-8")
    (repository / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")

    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "F7.1 External Product Test")
    _git(repository, "config", "user.email", "f71-product@example.invalid")
    _git(repository, "add", "--all", "--", ".")
    _git(repository, "commit", "--quiet", "-m", "baseline Python repository")
    initial_sha = _git(repository, "rev-parse", "HEAD").stdout.strip().lower()
    assert len(initial_sha) == 40

    distribution = tmp_path / "distribution"
    distribution.mkdir()
    uv = _uv_executable()
    _run(
        [
            uv,
            "build",
            "--wheel",
            "--offline",
            "--out-dir",
            str(distribution),
        ],
        cwd=ROOT,
        environment=command_environment,
    )
    wheels = tuple(distribution.glob("*.whl"))
    assert len(wheels) == 1

    installed_environment = tmp_path / "installed-wheel-environment"
    installed_environment.mkdir()
    _run(
        [
            uv,
            "pip",
            "install",
            "--offline",
            "--target",
            str(installed_environment),
            "--no-deps",
            str(wheels[0]),
        ],
        cwd=tmp_path,
        environment=command_environment,
    )

    environment = command_environment.copy()
    environment["PYTHONPATH"] = str(installed_environment)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONSAFEPATH"] = "1"
    scripts_dir = Path(sys.executable).parent
    environment["PATH"] = os.pathsep.join((str(scripts_dir), environment.get("PATH", "")))

    init_result = _run(
        [sys.executable, "-m", "ai_engineering_harness.cli.main", "init"],
        cwd=repository,
        environment=environment,
    )
    assert "inicializada com sucesso" in init_result.stdout
    graph = repository / ".harness" / "graphs" / "specs" / f"{workflow}.yaml"
    assert "context_retrieval" in graph.read_text(encoding="utf-8")

    (repository / ".harness" / "trusted_repository").write_text(
        "F7.1 test-only trust marker; capabilities still require host authorization.\n",
        encoding="utf-8",
    )
    graph.write_text(_GRAPH, encoding="utf-8")
    (repository / ".harness" / "policies" / "tool_policy.yaml").write_text(
        _TOOL_POLICY,
        encoding="utf-8",
    )
    (repository / ".harness" / "policies" / "verification_policy.yaml").write_text(
        _VERIFICATION_POLICY,
        encoding="utf-8",
    )
    tool_registry = repository / ".harness" / "tools" / "tool_registry.yaml"
    packaged_registry = tool_registry.read_text(encoding="utf-8")
    assert "id: apply_patch" not in packaged_registry
    tool_registry.write_text(
        packaged_registry.rstrip() + "\n" + _TOOL_REGISTRY_ENTRY,
        encoding="utf-8",
    )
    code_agent = repository / ".harness" / "agents" / "code_agent" / "agent.yaml"
    packaged_agent = code_agent.read_text(encoding="utf-8")
    assert "  - file_writer\n" in packaged_agent
    assert "  - apply_patch\n" not in packaged_agent
    code_agent.write_text(
        packaged_agent.replace(
            "  - file_writer\n",
            "  - file_writer\n  - apply_patch\n",
        ),
        encoding="utf-8",
    )
    compile_result = _run(
        [
            sys.executable,
            "-m",
            "ai_engineering_harness.cli.main",
            "compile",
            str(graph),
            "--workflow",
            workflow,
        ],
        cwd=repository,
        environment=environment,
    )
    assert "Grafo compilado com sucesso" in compile_result.stdout
    compiled = tuple((repository / ".harness" / "state" / "compiled").glob("*.json"))
    assert len(compiled) == 1

    _git(repository, "add", "--all", "--", ".")
    _git(repository, "commit", "--quiet", "-m", "configure installed harness")
    configured_sha = _git(repository, "rev-parse", "HEAD").stdout.strip().lower()
    assert configured_sha != initial_sha
    assert _git(repository, "status", "--porcelain").stdout == ""

    runner = tmp_path / "run_installed_f71.py"
    runner.write_text(_RUNNER, encoding="utf-8")
    completed = _run(
        [
            sys.executable,
            str(runner),
            str(repository),
            str(compiled[0]),
            str(installed_environment),
            str(ROOT),
            initial_sha,
            configured_sha,
        ],
        cwd=tmp_path,
        environment=environment,
        timeout=360.0,
    )
    report = json.loads(completed.stdout.splitlines()[-1])

    assert report["initial_sha"] == initial_sha
    assert report["configured_sha"] == configured_sha
    assert report["state"] == "COMPENSATED"
    assert report["tool_calls"] == 1
    assert report["gate_ids"] == ["typecheck", "lint", "unit_test", "build"]
    assert Path(report["package_origin"]).is_relative_to(installed_environment)
    assert not Path(report["package_origin"]).is_relative_to(ROOT)
    assert len({report["candidate_sha"], report["promotion_sha"], report["rollback_sha"]}) == 3
    assert report["audit_events"] > 20
