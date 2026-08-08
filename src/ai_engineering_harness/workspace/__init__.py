"""Validated external Git worktrees and platform-specific sandbox locations."""

from .git_worktree import (
    BaseCommitMismatchError,
    DetachedHeadError,
    DirtyRepositoryError,
    DirtyWorktreeError,
    ExternalWorktreeManager,
    GitCommandError,
    GitUnavailableError,
    InvalidGitRepositoryError,
    ProvisionedWorktree,
    WorktreeCleanupError,
    WorktreeCollisionError,
    WorktreeConfigurationError,
    WorktreeError,
    WorktreeReference,
    WorktreeReferenceError,
    WorktreeStatus,
    WorktreeValidationError,
)
from .sandbox import SandboxProvider

__all__ = [
    "BaseCommitMismatchError",
    "DetachedHeadError",
    "DirtyRepositoryError",
    "DirtyWorktreeError",
    "ExternalWorktreeManager",
    "GitCommandError",
    "GitUnavailableError",
    "InvalidGitRepositoryError",
    "ProvisionedWorktree",
    "SandboxProvider",
    "WorktreeCleanupError",
    "WorktreeCollisionError",
    "WorktreeConfigurationError",
    "WorktreeError",
    "WorktreeReference",
    "WorktreeReferenceError",
    "WorktreeStatus",
    "WorktreeValidationError",
]
