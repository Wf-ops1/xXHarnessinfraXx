"""Executor de personas de agentes conectados ao Models Router e Tool Router."""

from pathlib import Path
from typing import Any

from ai_engineering_harness.contracts import CompiledGraphArtifact
from ai_engineering_harness.governance import TrustMode
from ai_engineering_harness.models.provider import CancellationToken, LLMResponse
from ai_engineering_harness.models.router import ModelRouter
from ai_engineering_harness.tools.router import ToolRouter

from .node_executors import ToolEffectDurabilityError, ToolEffectRecorder
from .tool_loop import EffectiveToolPolicy, ToolLoopExecutor, ToolLoopResult


class AgentExecutor:
    """Executa o raciocínio da persona atribuída ao nó (Winston, Amelia, etc.) e interage via ToolRouter."""

    def __init__(self, agent_name: str, router: ModelRouter, tool_router: ToolRouter | None = None, project_root: Path | None = None):
        self.agent_name = agent_name
        self.router = router
        self.tool_router = tool_router
        self.project_root = project_root
        self.system_prompt = self._load_agent_system_prompt()

    def _load_agent_system_prompt(self) -> str:
        role_map = {
            "Winston": "architecture_analyst",
            "Amelia": "code_agent",
            "Sally": "requirement_analyst",
            "Paige": "knowledge_updater",
            "Test": "test_agent",
            "Security": "security_agent"
        }
        role_folder = role_map.get(self.agent_name, self.agent_name.lower())

        if self.project_root:
            candidates = [
                self.project_root / "src" / "ai_engineering_harness" / "defaults" / "agents" / role_folder / "system_prompt.md",
                self.project_root / ".harness" / "agents" / role_folder / "system_prompt.md",
            ]
            for c in candidates:
                if c.exists():
                    return c.read_text(encoding="utf-8")

        return f"Você é {self.agent_name}, executando uma etapa do grafo agentic do BMad Method."

    def execute_node(
        self,
        prompt: str,
        primary_provider: str | None = None,
        fallback_providers: list[str] | tuple[str, ...] | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        candidates = self.router.validate_route(primary_provider, fallback_providers)
        full_prompt = self._compose_prompt(prompt)
        return self.router.complete_with_fallback(
            prompt=full_prompt,
            primary_provider_id=candidates[0],
            fallback_provider_ids=candidates[1:],
            cancellation_token=cancellation_token,
        )

    def _compose_prompt(self, prompt: str) -> str:
        return f"{self.system_prompt}\n\n{prompt}"

    def execute_tool_loop(
        self,
        prompt: str,
        *,
        artifact: CompiledGraphArtifact,
        node_id: str,
        max_tool_steps: int,
        primary_provider: str | None = None,
        fallback_providers: list[str] | tuple[str, ...] | None = None,
        cancellation_token: CancellationToken | None = None,
        tool_effect_recorder: ToolEffectRecorder | None = None,
        trust_mode: TrustMode = "restricted",
    ) -> ToolLoopResult:
        if self.tool_router is None:
            raise PermissionError(
                f"[POLICY ERROR] Nenhum ToolRouter associado ao executor do agente '{self.agent_name}'."
            )
        loop = ToolLoopExecutor(
            self.router,
            self.tool_router,
            max_tool_steps=max_tool_steps,
        )
        policy = EffectiveToolPolicy.from_artifact(artifact, node_id)
        policy.require_dispatchable()
        tool_schemas = self.tool_router.prepare(
            policy.allowed_tools,
            effective_denied_tools=policy.denied_tools,
        )
        candidates = self.router.validate_route(primary_provider, fallback_providers)
        full_prompt = self._compose_prompt(prompt)
        return loop.execute(
            full_prompt,
            policy=policy,
            tool_schemas=tool_schemas,
            model_candidates=candidates,
            cancellation_token=cancellation_token,
            tool_effect_recorder=tool_effect_recorder,
            trust_mode=trust_mode,
        )

    def execute_tool(self, tool_name: str, payload: dict[str, Any]) -> Any:
        del tool_name, payload
        raise ToolEffectDurabilityError(
            "direct tool dispatch is disabled; use execute_tool_loop with a durable recorder"
        )
