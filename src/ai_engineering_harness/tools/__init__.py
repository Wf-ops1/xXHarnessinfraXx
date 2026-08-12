"""Módulo Tools: registry operacional e adaptadores."""

from .operational import build_operational_tool_router
from .router import (
    ToolDefinition,
    ToolDispatchTarget,
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
    "ToolDispatchTarget",
    "ToolExecutionError",
    "ToolPayloadValidationError",
    "ToolRegistration",
    "ToolRouter",
    "ToolRouterError",
    "ToolUnauthorizedError",
    "ToolUnavailableError",
    "build_operational_tool_router",
]
