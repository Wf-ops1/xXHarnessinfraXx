"""Contratos e transporte HTTP para provedores reais de modelos."""

from __future__ import annotations

import json
import math
import queue
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from ai_engineering_harness.security.redaction import RedactionContext, Redactor

ProviderErrorCategory = Literal[
    "auth",
    "rate_limit",
    "timeout",
    "invalid_request",
    "unavailable",
    "invalid_response",
    "cancelled",
    "not_implemented",
]
APIStyle = Literal["responses", "chat_completions"]


class ToolCall(BaseModel):
    """Tool call validada devolvida por um provider."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, JsonValue]

    @model_validator(mode="after")
    def require_strict_json_arguments(self) -> ToolCall:
        _ensure_strict_json_value(self.arguments, path="tool arguments")
        return self


class ProviderContinuationState(BaseModel):
    """Provider-native response items retained only in memory for continuation."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    api_style: APIStyle
    output_items: tuple[dict[str, JsonValue], ...] = Field(
        min_length=1,
        exclude=True,
        repr=False,
    )

    @field_validator("output_items", mode="before")
    @classmethod
    def freeze_output_items(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_strict_json_items(self) -> ProviderContinuationState:
        for index, item in enumerate(self.output_items):
            _ensure_strict_json_value(
                item,
                path=f"provider continuation[{index}]",
            )
        return self


class LLMResponse(BaseModel):
    """Resposta normalizada; todos os metadados vêm do servidor."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    content: str
    provider: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    tool_calls: tuple[ToolCall, ...] = ()
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    request_id: str | None = None
    response_id: str = Field(min_length=1)
    structured_output: JsonValue | None = None
    continuation_state: ProviderContinuationState | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )

    @model_validator(mode="after")
    def require_consistent_usage_and_json(self) -> LLMResponse:
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError(
                "total_tokens must equal prompt_tokens + completion_tokens"
            )
        if self.structured_output is not None:
            _ensure_strict_json_value(
                self.structured_output,
                path="structured output",
            )
        return self


class ModelToolResult(BaseModel):
    """JSON-native result bound to one provider tool-call identity."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    result: JsonValue

    @model_validator(mode="after")
    def require_strict_json_result(self) -> ModelToolResult:
        _ensure_strict_json_value(self.result, path="tool result")
        return self


class ModelToolConversationTurn(BaseModel):
    """One completed model turn and all results returned for its tool calls."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    response: LLMResponse
    tool_results: tuple[ModelToolResult, ...]

    @field_validator("tool_results", mode="before")
    @classmethod
    def freeze_tool_results(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_exact_tool_results(self) -> ModelToolConversationTurn:
        calls = tuple((call.call_id, call.name) for call in self.response.tool_calls)
        results = tuple((result.call_id, result.name) for result in self.tool_results)
        if not calls:
            raise ValueError("a conversation turn requires at least one tool call")
        if calls != results:
            raise ValueError("tool results must match model tool calls in order")
        return self


class ModelToolConversation(BaseModel):
    """Provider-neutral in-memory conversation used for native tool continuation."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    initial_prompt: str = Field(min_length=1)
    turns: tuple[ModelToolConversationTurn, ...] = Field(min_length=1)

    @field_validator("turns", mode="before")
    @classmethod
    def freeze_turns(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_unique_call_ids(self) -> ModelToolConversation:
        call_ids = tuple(
            call.call_id
            for turn in self.turns
            for call in turn.response.tool_calls
        )
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("tool call IDs must be unique across conversation turns")
        return self


class CancellationToken:
    """Sinal cooperativo thread-safe para cancelar uma chamada de modelo."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(timeout)


class ProviderError(RuntimeError):
    """Erro público classificado, sem payload sensível bruto."""

    category: ClassVar[ProviderErrorCategory]
    retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        *,
        provider_id: str,
        request_id: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_id = provider_id
        self.request_id = request_id
        self.status_code = status_code


class ProviderAuthError(ProviderError):
    category = "auth"


class ProviderRateLimitError(ProviderError):
    category = "rate_limit"
    retryable = True


class ProviderTimeoutError(ProviderError):
    category = "timeout"
    retryable = True


class ProviderInvalidRequestError(ProviderError):
    category = "invalid_request"


class ProviderUnavailableError(ProviderError):
    category = "unavailable"
    retryable = True


class ProviderResponseError(ProviderError):
    category = "invalid_response"


class ProviderCancelledError(ProviderError):
    category = "cancelled"


class ProviderNotImplementedError(ProviderError):
    category = "not_implemented"


class BaseLLMProvider(ABC):
    """Interface abstrata para provedores de LLM."""

    def __init__(self, provider_id: str, model_name: str):
        self.provider_id = provider_id
        self.model_name = model_name

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def call_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    def continue_tools(
        self,
        conversation: ModelToolConversation,
        tools: list[dict[str, Any]],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        """Continue a typed tool conversation or fail explicitly when unsupported."""
        raise ProviderNotImplementedError(
            "provider não implementa continuação nativa de tools",
            provider_id=self.provider_id,
        )

    @abstractmethod
    def structured_output(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        raise NotImplementedError


class OpenAICompatibleHTTPProvider(BaseLLMProvider):
    """Transporte real para Responses API ou Chat Completions compatível."""

    _POLL_SECONDS = 0.02
    _MAX_ERROR_CHARS = 2_000

    def __init__(
        self,
        provider_id: str,
        model_name: str,
        *,
        base_url: str,
        api_style: APIStyle,
        api_key: str | None,
        redaction_context: RedactionContext | None = None,
        requires_api_key: bool,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.25,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(provider_id=provider_id, model_name=model_name)
        if not base_url.strip():
            raise ValueError("base_url não pode ser vazia")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds deve ser positivo")
        if max_retries < 0:
            raise ValueError("max_retries não pode ser negativo")
        if backoff_seconds < 0:
            raise ValueError("backoff_seconds não pode ser negativo")

        self.base_url = base_url.rstrip("/")
        self.api_style = api_style
        self._api_key = api_key
        if redaction_context is not None and not isinstance(redaction_context, RedactionContext):
            raise TypeError("redaction_context must be a RedactionContext or None")
        context = redaction_context or RedactionContext()
        self._redaction_context = (
            context._with_secret("PROVIDER_API_KEY", api_key) if api_key else context
        )
        self._requires_api_key = requires_api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._transport = transport

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        body = self._base_body(prompt, system_prompt)
        response, request_id = self._request(body, cancellation_token)
        return self._parse_response(response, request_id=request_id)

    def call_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        body = self._base_body(prompt, system_prompt)
        self._attach_tools(body, tools)
        response, request_id = self._request(body, cancellation_token)
        return self._parse_response(response, request_id=request_id)

    def continue_tools(
        self,
        conversation: ModelToolConversation,
        tools: list[dict[str, Any]],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        body = self._continuation_body(conversation)
        self._attach_tools(body, tools)
        response, request_id = self._request(body, cancellation_token)
        return self._parse_response(response, request_id=request_id)

    def structured_output(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        try:
            Draft202012Validator.check_schema(response_schema)
        except SchemaError as exc:
            raise ProviderInvalidRequestError(
                self._redact(f"JSON Schema inválido: {exc.message}"),
                provider_id=self.provider_id,
            ) from exc

        body = self._base_body(prompt, None)
        schema_format = {
            "type": "json_schema",
            "name": "harness_response",
            "strict": True,
            "schema": response_schema,
        }
        if self.api_style == "responses":
            body["text"] = {"format": schema_format}
        else:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    key: value for key, value in schema_format.items() if key != "type"
                },
            }

        response, request_id = self._request(body, cancellation_token)
        parsed = self._parse_response(response, request_id=request_id)
        try:
            structured = _strict_json_loads(parsed.content)
            Draft202012Validator(response_schema).validate(structured)
            _ensure_strict_json_value(structured, path="structured output")
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise ProviderResponseError(
                self._redact(f"structured output inválido: {exc}"),
                provider_id=self.provider_id,
                request_id=parsed.request_id,
            ) from exc
        return parsed.model_copy(update={"structured_output": structured})

    def _base_body(self, prompt: str, system_prompt: str | None) -> dict[str, Any]:
        if not prompt:
            raise ProviderInvalidRequestError(
                "prompt não pode ser vazio",
                provider_id=self.provider_id,
            )
        if self.api_style == "responses":
            body: dict[str, Any] = {
                "model": self.model_name,
                "input": prompt,
                "store": False,
            }
            if system_prompt:
                body["instructions"] = system_prompt
            return body

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return {"model": self.model_name, "messages": messages}

    def _continuation_body(
        self,
        conversation: ModelToolConversation,
    ) -> dict[str, Any]:
        if self.api_style == "responses":
            input_items: list[dict[str, Any]] = [
                {"role": "user", "content": conversation.initial_prompt}
            ]
            for turn in conversation.turns:
                continuation_state = turn.response.continuation_state
                if (
                    continuation_state is not None
                    and continuation_state.api_style == "responses"
                    and turn.response.provider == self.provider_id
                ):
                    input_items.extend(
                        _copy_strict_json_object(
                            item,
                            path="provider continuation",
                        )
                        for item in continuation_state.output_items
                    )
                else:
                    if turn.response.content:
                        input_items.append(
                            {"role": "assistant", "content": turn.response.content}
                        )
                    input_items.extend(
                        {
                            "type": "function_call",
                            "call_id": call.call_id,
                            "name": call.name,
                            "arguments": _strict_json_dumps(call.arguments),
                        }
                        for call in turn.response.tool_calls
                    )
                input_items.extend(
                    {
                        "type": "function_call_output",
                        "call_id": result.call_id,
                        "output": _strict_json_dumps(result.result),
                    }
                    for result in turn.tool_results
                )
            return {
                "model": self.model_name,
                "input": input_items,
                "store": False,
            }

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": conversation.initial_prompt}
        ]
        for turn in conversation.turns:
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.response.content or None,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": _strict_json_dumps(call.arguments),
                            },
                        }
                        for call in turn.response.tool_calls
                    ],
                }
            )
            messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": result.call_id,
                    "content": _strict_json_dumps(result.result),
                }
                for result in turn.tool_results
            )
        return {"model": self.model_name, "messages": messages}

    def _attach_tools(
        self,
        body: dict[str, Any],
        tools: list[dict[str, Any]],
    ) -> None:
        normalised = [self._normalise_tool(tool) for tool in tools]
        if self.api_style == "chat_completions":
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        key: value for key, value in tool.items() if key != "type"
                    },
                }
                for tool in normalised
            ]
            return
        body["tools"] = normalised

    def _normalise_tool(self, tool: dict[str, Any]) -> dict[str, Any]:
        candidate = tool.get("function") if tool.get("type") == "function" else tool
        if not isinstance(candidate, dict):
            raise self._invalid_tool("definição de function ausente")
        name = candidate.get("name")
        parameters = candidate.get("parameters")
        description = candidate.get("description", "")
        if not isinstance(name, str) or not name:
            raise self._invalid_tool("nome ausente")
        if not isinstance(parameters, dict):
            raise self._invalid_tool(f"parameters inválido para {name}")
        if not isinstance(description, str):
            raise self._invalid_tool(f"description inválida para {name}")
        try:
            Draft202012Validator.check_schema(parameters)
        except SchemaError as exc:
            raise self._invalid_tool(f"schema inválido para {name}: {exc.message}") from exc
        return {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": parameters,
            "strict": True,
        }

    def _invalid_tool(self, detail: str) -> ProviderInvalidRequestError:
        return ProviderInvalidRequestError(
            self._redact(f"tool inválida: {detail}"),
            provider_id=self.provider_id,
        )

    def _request(
        self,
        body: dict[str, Any],
        cancellation_token: CancellationToken | None,
    ) -> tuple[dict[str, Any], str | None]:
        self._raise_if_cancelled(cancellation_token)
        if self._requires_api_key and not self._api_key:
            raise ProviderAuthError(
                "credencial do provider não configurada",
                provider_id=self.provider_id,
            )

        last_error: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            self._raise_if_cancelled(cancellation_token)
            try:
                response = self._send_once(body, cancellation_token)
                raw_request_id = response.headers.get("x-request-id")
                request_id = self._redact(raw_request_id) if raw_request_id else None
                if not response.is_success:
                    raise self._http_error(response, request_id=request_id)
                try:
                    payload = _strict_json_loads(response.text)
                except ValueError as exc:
                    raise ProviderResponseError(
                        "provider retornou JSON inválido",
                        provider_id=self.provider_id,
                        request_id=request_id,
                        status_code=response.status_code,
                    ) from exc
                if not isinstance(payload, dict):
                    raise ProviderResponseError(
                        "provider retornou payload não-objeto",
                        provider_id=self.provider_id,
                        request_id=request_id,
                        status_code=response.status_code,
                    )
                self._raise_if_cancelled(cancellation_token)
                safe_payload = Redactor.redact_json(payload, context=self._redaction_context)
                if not isinstance(safe_payload, dict):  # pragma: no cover - payload invariant
                    raise ProviderResponseError(
                        "provider retornou payload não-objeto",
                        provider_id=self.provider_id,
                        request_id=request_id,
                        status_code=response.status_code,
                    )
                return safe_payload, request_id
            except ProviderError as exc:
                last_error = exc
            except httpx.TimeoutException as exc:
                last_error = ProviderTimeoutError(
                    self._redact(f"timeout no provider: {exc}"),
                    provider_id=self.provider_id,
                )
            except (httpx.RequestError, OSError) as exc:
                last_error = ProviderUnavailableError(
                    self._redact(f"provider indisponível: {exc}"),
                    provider_id=self.provider_id,
                )

            if not last_error.retryable or attempt >= self.max_retries:
                raise last_error
            self._wait_backoff(attempt, cancellation_token)

        raise AssertionError("loop de retry terminou sem resultado")

    def _send_once(
        self,
        body: dict[str, Any],
        cancellation_token: CancellationToken | None,
    ) -> httpx.Response:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        client = httpx.Client(
            timeout=self.timeout_seconds,
            transport=self._transport,
            headers=headers,
        )
        if cancellation_token is None:
            try:
                return client.post(self._endpoint, json=body)
            finally:
                client.close()

        result_queue: queue.Queue[httpx.Response | httpx.HTTPError | OSError] = queue.Queue(maxsize=1)

        def send() -> None:
            try:
                result_queue.put(client.post(self._endpoint, json=body))
            except (httpx.HTTPError, OSError) as exc:
                result_queue.put(exc)
            finally:
                client.close()

        worker = threading.Thread(target=send, name=f"{self.provider_id}-request", daemon=True)
        worker.start()
        while True:
            try:
                result = result_queue.get(timeout=self._POLL_SECONDS)
            except queue.Empty:
                if cancellation_token.is_cancelled:
                    client.close()
                    raise ProviderCancelledError(
                        "chamada do provider cancelada",
                        provider_id=self.provider_id,
                    )
                continue
            if isinstance(result, Exception):
                raise result
            return result

    @property
    def _endpoint(self) -> str:
        suffix = "responses" if self.api_style == "responses" else "chat/completions"
        return f"{self.base_url}/{suffix}"

    def _wait_backoff(
        self,
        attempt: int,
        cancellation_token: CancellationToken | None,
    ) -> None:
        delay = self.backoff_seconds * (2**attempt)
        if cancellation_token is not None:
            if cancellation_token.wait(delay):
                raise ProviderCancelledError(
                    "chamada do provider cancelada durante retry",
                    provider_id=self.provider_id,
                )
        elif delay:
            time.sleep(delay)

    def _raise_if_cancelled(self, cancellation_token: CancellationToken | None) -> None:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise ProviderCancelledError(
                "chamada do provider cancelada",
                provider_id=self.provider_id,
            )

    def _http_error(self, response: httpx.Response, *, request_id: str | None) -> ProviderError:
        status = response.status_code
        detail = self._redact(response.text)
        message = f"provider HTTP {status}: {detail}"
        error_type: type[ProviderError]
        if status in {401, 403}:
            error_type = ProviderAuthError
        elif status == 429:
            error_type = ProviderRateLimitError
        elif status in {408, 504}:
            error_type = ProviderTimeoutError
        elif status >= 500 or status in {409, 425}:
            error_type = ProviderUnavailableError
        else:
            error_type = ProviderInvalidRequestError
        return error_type(
            message,
            provider_id=self.provider_id,
            request_id=request_id,
            status_code=status,
        )

    def _parse_response(self, payload: Mapping[str, Any], *, request_id: str | None) -> LLMResponse:
        try:
            if self.api_style == "responses":
                return self._parse_responses_api(payload, request_id=request_id)
            return self._parse_chat_completions(payload, request_id=request_id)
        except ProviderResponseError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderResponseError(
                self._redact(f"resposta incompatível do provider: {exc}"),
                provider_id=self.provider_id,
                request_id=request_id,
            ) from exc

    def _parse_responses_api(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str | None,
    ) -> LLMResponse:
        status = payload.get("status")
        if status != "completed":
            raise ProviderResponseError(
                self._redact(f"Responses API terminou com status {status!r}"),
                provider_id=self.provider_id,
                request_id=request_id,
            )
        response_id = self._required_string(payload, "id")
        model_name = self._required_string(payload, "model")
        usage = self._required_mapping(payload, "usage")
        prompt_tokens = self._required_non_negative_int(usage, "input_tokens")
        completion_tokens = self._required_non_negative_int(usage, "output_tokens")
        total_tokens = self._required_non_negative_int(usage, "total_tokens")
        output = payload.get("output")
        if not isinstance(output, list):
            raise TypeError("output ausente ou inválido")

        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in output:
            if not isinstance(item, dict):
                raise TypeError("item de output inválido")
            item_type = item.get("type")
            if item_type == "message":
                message_content = item.get("content")
                if not isinstance(message_content, list):
                    raise ValueError("content da mensagem inválido")
                for part in message_content:
                    if isinstance(part, dict) and part.get("type") == "output_text":
                        text = part.get("text")
                        if not isinstance(text, str):
                            raise ValueError("output_text inválido")
                        content_parts.append(text)
            elif item_type == "function_call":
                tool_calls.append(self._responses_tool_call(item))

        if not content_parts and not tool_calls:
            raise ValueError("resposta sem conteúdo ou tool call")
        return LLMResponse(
            content="".join(content_parts),
            provider=self.provider_id,
            model_name=model_name,
            tool_calls=tuple(tool_calls),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            request_id=request_id,
            response_id=response_id,
            continuation_state=ProviderContinuationState(
                api_style="responses",
                output_items=tuple(
                    _copy_strict_json_object(item, path="response output")
                    for item in output
                ),
            ),
        )

    def _parse_chat_completions(
        self,
        payload: Mapping[str, Any],
        *,
        request_id: str | None,
    ) -> LLMResponse:
        response_id = self._required_string(payload, "id")
        model_name = self._required_string(payload, "model")
        usage = self._required_mapping(payload, "usage")
        prompt_tokens = self._required_non_negative_int(usage, "prompt_tokens")
        completion_tokens = self._required_non_negative_int(usage, "completion_tokens")
        total_tokens = self._required_non_negative_int(usage, "total_tokens")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("choices ausente ou inválido")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise TypeError("message ausente ou inválida")
        content = message.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise TypeError("content inválido")
        raw_tool_calls = message.get("tool_calls", [])
        if not isinstance(raw_tool_calls, list):
            raise TypeError("tool_calls inválido")
        tool_calls = tuple(self._chat_tool_call(item) for item in raw_tool_calls)
        if not content and not tool_calls:
            raise ValueError("resposta sem conteúdo ou tool call")
        return LLMResponse(
            content=content,
            provider=self.provider_id,
            model_name=model_name,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            request_id=request_id,
            response_id=response_id,
        )

    def _responses_tool_call(self, item: Mapping[str, Any]) -> ToolCall:
        return ToolCall(
            call_id=self._required_string(item, "call_id"),
            name=self._required_string(item, "name"),
            arguments=self._parse_tool_arguments(item.get("arguments")),
        )

    def _chat_tool_call(self, item: Any) -> ToolCall:
        if not isinstance(item, dict):
            raise TypeError("tool call inválida")
        function = item.get("function")
        if not isinstance(function, dict):
            raise TypeError("function da tool call inválida")
        return ToolCall(
            call_id=self._required_string(item, "id"),
            name=self._required_string(function, "name"),
            arguments=self._parse_tool_arguments(function.get("arguments")),
        )

    @staticmethod
    def _parse_tool_arguments(raw_arguments: Any) -> dict[str, JsonValue]:
        if not isinstance(raw_arguments, str):
            raise TypeError("arguments da tool call não são JSON textual")
        arguments = _strict_json_loads(raw_arguments)
        if not isinstance(arguments, dict):
            raise TypeError("arguments da tool call não são objeto JSON")
        _ensure_strict_json_value(arguments, path="tool arguments")
        return arguments

    @staticmethod
    def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
        value = payload[key]
        if not isinstance(value, dict):
            raise TypeError(f"{key} não é objeto")
        return value

    @staticmethod
    def _required_string(payload: Mapping[str, Any], key: str) -> str:
        value = payload[key]
        if not isinstance(value, str) or not value:
            raise TypeError(f"{key} não é string não vazia")
        return value

    @staticmethod
    def _required_non_negative_int(payload: Mapping[str, Any], key: str) -> int:
        value = payload[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TypeError(f"{key} não é inteiro não negativo")
        return value

    def _redact(self, text: str) -> str:
        return Redactor.redact_text(text, context=self._redaction_context)[: self._MAX_ERROR_CHARS]


def _strict_json_loads(raw: str) -> JsonValue:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant is forbidden: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key is forbidden: {key}")
            result[key] = value
        return result

    return json.loads(
        raw,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicate_keys,
    )


def _strict_json_dumps(value: object) -> str:
    _ensure_strict_json_value(value, path="JSON value")
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _copy_strict_json_object(
    value: object,
    *,
    path: str,
) -> dict[str, JsonValue]:
    _ensure_strict_json_value(value, path=path)
    copied = _strict_json_loads(_strict_json_dumps(value))
    if not isinstance(copied, dict):
        raise TypeError(f"{path} is not an object")
    return copied


def _ensure_strict_json_value(value: object, *, path: str) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _ensure_strict_json_value(item, path=f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} contains a non-string object key")
            _ensure_strict_json_value(item, path=f"{path}.{key}")
        return
    raise ValueError(f"{path} contains non-JSON-native value {type(value).__name__}")
