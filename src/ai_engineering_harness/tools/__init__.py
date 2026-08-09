"""Módulo Tools: Roteamento de ferramentas, permissões e adaptadores."""

from .operational import build_operational_tool_router
from .permissions import ToolPermissions
from .router import (
    ToolDefinition,
    ToolExecutionError,
    ToolPayloadValidationError,
    ToolRegistration,
    ToolRouter,
    ToolRouterError,
    ToolUnauthorizedError,
    ToolUnavailableError,
)

__all__ = [
    "ToolDefinition",
    "ToolExecutionError",
    "ToolPayloadValidationError",
    "ToolPermissions",
    "ToolRegistration",
    "ToolRouter",
    "ToolRouterError",
    "ToolUnauthorizedError",
    "ToolUnavailableError",
    "build_operational_tool_router",
]
