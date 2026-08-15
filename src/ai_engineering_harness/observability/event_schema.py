"""Compatibility import for the former independent tracing envelope."""

from ai_engineering_harness.contracts.events import ExecutionEvent

HarnessTraceEvent = ExecutionEvent

__all__ = ["HarnessTraceEvent"]
