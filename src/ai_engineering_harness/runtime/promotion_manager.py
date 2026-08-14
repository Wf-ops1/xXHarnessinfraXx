"""Fail-closed candidate creation and Git promotion for F3.7."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from ai_engineering_harness.security import (
    TrustBoundaryConfigurationError,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
)
from ai_engineering_harness.workspace import (
    ExternalWorktreeManager,
    ProvisionedWorktree,
)


class PromotionError(RuntimeError):
    """Base error for safe candidate or promotion operations."""


class PromotionConfigurationError(PromotionError, ValueError):
    """Raised when promotion inputs cannot identify an exact Git subject."""


class PromotionPrerequisiteError(PromotionError):
    """Raised before promotion when required Git state is absent or unsafe."""


class PromotionBaseChangedError(PromotionPrerequisiteError):
    """Raised when the original branch or base HEAD no longer matches the execution."""


class PromotionCommandError(PromotionError):
    """Raised when a bounded Git command fails without a synthetic fallback."""


class PromotionEffectAmbiguousError(PromotionError):
    """Raised when an interrupted promotion cannot be proven from Git state."""


@dataclass(frozen=True, slots=True)
class CandidateCommit:
    """One real candidate commit bound to its execution and immutable base."""

    execution_id: str
    base_commit_sha: str
    candidate_commit_sha: str
    original_branch: str
    worktree_branch: str
    worktree_path: Path


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """Observed result of a dry-run or a real cherry-pick."""

    candidate_commit_sha: str
    promotion_commit_sha: str | None
    original_branch: str
    dry_run: bool
    recovered: bool


class PromotionManager:
    """Create one candidate in an external worktree and promote it by cherry-pick."""

    _FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

    def __init__(
        self,
        project_root: Path,
        worktree_manager: ExternalWorktreeManager,
        *,
        git_executable: str = "git",
        command_timeout_seconds: float = 30.0,
        trust_boundary: TrustEvaluationResult | None = None,
    ) -> None:
        try:
            root = Path(project_root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PromotionConfigurationError(
                "project_root must resolve to an existing directory"
            ) from exc
        if not root.is_dir():
            raise PromotionConfigurationError("project_root must be a directory")
        if not isinstance(worktree_manager, ExternalWorktreeManager):
            raise PromotionConfigurationError(
                "worktree_manager must be an ExternalWorktreeManager"
            )
        if worktree_manager.project_root != root:
            raise PromotionConfigurationError(
                "worktree manager and promotion project roots must match"
            )
        if type(git_executable) is not str or not git_executable.strip():
            raise PromotionConfigurationError("git_executable must be non-empty")
        if (
            isinstance(command_timeout_seconds, bool)
            or not isinstance(command_timeout_seconds, (int, float))
            or command_timeout_seconds <= 0
        ):
            raise PromotionConfigurationError(
                "command_timeout_seconds must be positive"
            )
        self.project_root = root
        self.worktree_manager = worktree_manager
        self.git_executable = git_executable
        self.command_timeout_seconds = float(command_timeout_seconds)
        boundary = trust_boundary or worktree_manager.trust_boundary
        if not isinstance(boundary, TrustEvaluationResult):
            raise PromotionConfigurationError(
                "trust_boundary must be a TrustEvaluationResult"
            )
        try:
            boundary.require_root(root)
        except (TrustBoundaryConfigurationError, TrustCapabilityDeniedError) as exc:
            raise PromotionConfigurationError(
                "trust boundary must authorize the exact promotion root"
            ) from exc
        if Path(boundary.repository_root) != root:
            raise PromotionConfigurationError(
                "trust boundary belongs to another repository root"
            )
        if boundary != worktree_manager.trust_boundary:
            raise PromotionConfigurationError(
                "promotion and worktree managers must share one trust boundary"
            )
        self.trust_boundary = boundary

    def create_candidate(
        self,
        execution_id: str,
        *,
        message: str | None = None,
    ) -> CandidateCommit:
        """Create or recover the single squashed candidate commit for an execution."""

        worktree = self.worktree_manager.create_candidate_commit(
            execution_id,
            message=message,
        )
        return self._candidate_from_worktree(execution_id, worktree)

    def load_candidate(self, execution_id: str) -> CandidateCommit:
        """Reload and validate an already-published candidate reference."""

        worktree = self.worktree_manager.load_worktree(execution_id)
        return self._candidate_from_worktree(execution_id, worktree)

    def candidate_diff_digest(self, candidate: CandidateCommit) -> str:
        """Hash the exact binary-safe Git diff from execution base to candidate."""

        self._validate_candidate(candidate)
        result = self._run_git_bytes(
            (
                "diff",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-renames",
                candidate.base_commit_sha,
                candidate.candidate_commit_sha,
                "--",
            ),
            cwd=self.project_root,
        )
        if not result.stdout:
            raise PromotionPrerequisiteError(
                "candidate diff is empty despite a changed candidate tree"
            )
        return "sha256:" + hashlib.sha256(result.stdout).hexdigest()

    def promote(
        self,
        candidate: CandidateCommit,
        *,
        dry_run: bool,
        approval_granted: bool = False,
    ) -> PromotionResult:
        """Promote exactly ``candidate`` or prove a no-effect dry-run.

        A retry after an interrupted cherry-pick first reconciles the original Git state. It returns
        an existing promotion only when branch, parent and tree prove the exact candidate outcome.
        """

        self._validate_candidate(candidate)
        if dry_run:
            self._require_original_base(candidate)
            return PromotionResult(
                candidate_commit_sha=candidate.candidate_commit_sha,
                promotion_commit_sha=None,
                original_branch=candidate.original_branch,
                dry_run=True,
                recovered=False,
            )

        try:
            self.trust_boundary.require_promotion(
                approval_granted=approval_granted,
            )
        except TrustCapabilityDeniedError as exc:
            raise PromotionPrerequisiteError(str(exc)) from exc

        recovered = self.recover_promotion(candidate)
        if recovered is not None:
            return recovered

        result = self._run_git(
            ("cherry-pick", candidate.candidate_commit_sha),
            cwd=self.project_root,
            allowed_returncodes=(0, 1, 128),
        )
        if result.returncode != 0:
            self._run_git(
                ("cherry-pick", "--abort"),
                cwd=self.project_root,
                allowed_returncodes=(0, 128),
            )
            raise PromotionCommandError(
                f"git cherry-pick failed with exit code {result.returncode}"
            )
        promoted = self.recover_promotion(candidate)
        if promoted is None:
            raise PromotionEffectAmbiguousError(
                "cherry-pick returned success without a provable promotion commit"
            )
        return PromotionResult(
            candidate_commit_sha=promoted.candidate_commit_sha,
            promotion_commit_sha=promoted.promotion_commit_sha,
            original_branch=promoted.original_branch,
            dry_run=False,
            recovered=False,
        )

    def recover_promotion(
        self,
        candidate: CandidateCommit,
    ) -> PromotionResult | None:
        """Prove an exact prior cherry-pick, return no-effect base, or fail closed."""

        self._validate_candidate(candidate)
        branch, head, status = self._original_identity()
        if branch != candidate.original_branch:
            raise PromotionBaseChangedError("original branch changed before promotion")
        if status:
            raise PromotionEffectAmbiguousError(
                "original checkout is dirty during promotion recovery"
            )
        if head == candidate.base_commit_sha:
            return None

        parent = self._run_git(
            ("rev-parse", "--verify", f"{head}^"),
            cwd=self.project_root,
        ).stdout.strip().lower()
        promoted_tree = self._tree(head)
        candidate_tree = self._tree(candidate.candidate_commit_sha)
        promoted_identity = self._commit_identity(head)
        candidate_identity = self._commit_identity(candidate.candidate_commit_sha)
        if (
            parent != candidate.base_commit_sha
            or promoted_tree != candidate_tree
            or promoted_identity != candidate_identity
        ):
            raise PromotionBaseChangedError(
                "original HEAD advanced without the exact candidate cherry-pick"
            )
        return PromotionResult(
            candidate_commit_sha=candidate.candidate_commit_sha,
            promotion_commit_sha=head,
            original_branch=candidate.original_branch,
            dry_run=False,
            recovered=True,
        )

    def _candidate_from_worktree(
        self,
        execution_id: str,
        worktree: ProvisionedWorktree,
    ) -> CandidateCommit:
        reference = worktree.reference
        if worktree.trust_boundary is None:
            raise PromotionPrerequisiteError(
                "candidate worktree is missing its trust boundary"
            )
        expected_boundary = self.trust_boundary.bind_authorized_root(
            reference.worktree_path
        )
        if worktree.trust_boundary != expected_boundary:
            raise PromotionPrerequisiteError(
                "candidate worktree trust boundary does not match promotion root"
            )
        candidate_sha = reference.worktree_head_sha
        if reference.execution_id != execution_id or candidate_sha is None:
            raise PromotionPrerequisiteError(
                "worktree reference does not identify the requested candidate"
            )
        candidate = CandidateCommit(
            execution_id=execution_id,
            base_commit_sha=reference.base_commit_sha,
            candidate_commit_sha=candidate_sha,
            original_branch=reference.original_branch,
            worktree_branch=reference.worktree_branch,
            worktree_path=reference.worktree_path,
        )
        self._validate_candidate(candidate)
        status = self._run_git(
            ("status", "--porcelain=v1", "--untracked-files=all"),
            cwd=candidate.worktree_path,
        ).stdout
        if status.strip():
            raise PromotionPrerequisiteError("candidate worktree must be clean")
        return candidate

    def _validate_candidate(self, candidate: CandidateCommit) -> None:
        if not isinstance(candidate, CandidateCommit):
            raise PromotionConfigurationError("candidate must be a CandidateCommit")
        for value, label in (
            (candidate.base_commit_sha, "base commit"),
            (candidate.candidate_commit_sha, "candidate commit"),
        ):
            if type(value) is not str or self._FULL_SHA.fullmatch(value) is None:
                raise PromotionConfigurationError(f"{label} must be a full lowercase SHA")
        if (
            type(candidate.original_branch) is not str
            or not candidate.original_branch.strip()
            or candidate.original_branch != candidate.original_branch.strip()
        ):
            raise PromotionConfigurationError("original_branch must be trimmed")
        parent = self._run_git(
            ("rev-parse", "--verify", f"{candidate.candidate_commit_sha}^"),
            cwd=self.project_root,
        ).stdout.strip().lower()
        if parent != candidate.base_commit_sha:
            raise PromotionPrerequisiteError(
                "candidate commit must be the single child of the execution base"
            )
        if self._tree(candidate.candidate_commit_sha) == self._tree(
            candidate.base_commit_sha
        ):
            raise PromotionPrerequisiteError("candidate commit contains no tree change")

    def _require_original_base(self, candidate: CandidateCommit) -> None:
        branch, head, status = self._original_identity()
        if branch != candidate.original_branch or head != candidate.base_commit_sha:
            raise PromotionBaseChangedError(
                "original branch or HEAD changed before promotion"
            )
        if status:
            raise PromotionPrerequisiteError(
                "original checkout must be clean before promotion"
            )

    def _original_identity(self) -> tuple[str, str, str]:
        root = self._run_git(
            ("rev-parse", "--show-toplevel"),
            cwd=self.project_root,
        ).stdout.strip()
        try:
            resolved_root = Path(root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PromotionPrerequisiteError(
                "original Git root cannot be resolved"
            ) from exc
        if resolved_root != self.project_root:
            raise PromotionPrerequisiteError(
                "project_root is not the exact original Git root"
            )
        branch_result = self._run_git(
            ("symbolic-ref", "--quiet", "--short", "HEAD"),
            cwd=self.project_root,
            allowed_returncodes=(0, 1),
        )
        if branch_result.returncode != 0:
            raise PromotionBaseChangedError("original checkout is detached")
        head = self._run_git(
            ("rev-parse", "--verify", "HEAD^{commit}"),
            cwd=self.project_root,
        ).stdout.strip().lower()
        status = self._run_git(
            ("status", "--porcelain=v1", "--untracked-files=all"),
            cwd=self.project_root,
        ).stdout.strip()
        return branch_result.stdout.strip(), head, status

    def _tree(self, commit_sha: str) -> str:
        return self._run_git(
            ("rev-parse", "--verify", f"{commit_sha}^{{tree}}"),
            cwd=self.project_root,
        ).stdout.strip().lower()

    def _commit_identity(self, commit_sha: str) -> str:
        return self._run_git(
            (
                "show",
                "--no-patch",
                "--format=%an%x00%ae%x00%aI%x00%B",
                commit_sha,
            ),
            cwd=self.project_root,
        ).stdout

    def _run_git(
        self,
        arguments: Collection[str],
        *,
        cwd: Path,
        allowed_returncodes: Collection[int] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        try:
            self.trust_boundary.require_executable(self.git_executable)
        except TrustCapabilityDeniedError as exc:
            raise PromotionPrerequisiteError(
                "Git executable is not allowed by the trust boundary"
            ) from exc
        try:
            result = subprocess.run(
                (self.git_executable, *arguments),
                cwd=cwd,
                check=False,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout_seconds,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except FileNotFoundError as exc:
            raise PromotionCommandError("configured Git executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise PromotionCommandError("Git promotion command timed out") from exc
        except OSError as exc:
            raise PromotionCommandError("Git promotion command could not start") from exc
        if result.returncode not in allowed_returncodes:
            operation = " ".join(tuple(arguments)[:2])
            raise PromotionCommandError(
                f"Git operation {operation!r} failed with exit code {result.returncode}"
            )
        return result

    def _run_git_bytes(
        self,
        arguments: Collection[str],
        *,
        cwd: Path,
        allowed_returncodes: Collection[int] = (0,),
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            self.trust_boundary.require_executable(self.git_executable)
        except TrustCapabilityDeniedError as exc:
            raise PromotionPrerequisiteError(
                "Git executable is not allowed by the trust boundary"
            ) from exc
        try:
            result = subprocess.run(
                (self.git_executable, *arguments),
                cwd=cwd,
                check=False,
                shell=False,
                capture_output=True,
                text=False,
                timeout=self.command_timeout_seconds,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except FileNotFoundError as exc:
            raise PromotionCommandError("configured Git executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise PromotionCommandError("Git promotion command timed out") from exc
        except OSError as exc:
            raise PromotionCommandError("Git promotion command could not start") from exc
        if result.returncode not in allowed_returncodes:
            operation = " ".join(tuple(arguments)[:2])
            raise PromotionCommandError(
                f"Git operation {operation!r} failed with exit code {result.returncode}"
            )
        return result


__all__ = [
    "CandidateCommit",
    "PromotionBaseChangedError",
    "PromotionCommandError",
    "PromotionConfigurationError",
    "PromotionEffectAmbiguousError",
    "PromotionError",
    "PromotionManager",
    "PromotionPrerequisiteError",
    "PromotionResult",
]
