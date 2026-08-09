"""Adaptadores concretos de ferramentas (Serena, Terminal, Git)."""

from .git import GitAdapter
from .serena import SerenaAdapter
from .terminal import (
    CommandExecutionError,
    CommandRequest,
    CommandResult,
    CommandValidationError,
    EnvironmentNotAllowedError,
    ExecutableNotAllowedError,
    LegacyShellCommandError,
    TerminalAdapter,
    TerminalAdapterError,
    TerminalConfigurationError,
)

__all__ = [
    "CommandExecutionError",
    "CommandRequest",
    "CommandResult",
    "CommandValidationError",
    "EnvironmentNotAllowedError",
    "ExecutableNotAllowedError",
    "GitAdapter",
    "LegacyShellCommandError",
    "SerenaAdapter",
    "TerminalAdapter",
    "TerminalAdapterError",
    "TerminalConfigurationError",
]
