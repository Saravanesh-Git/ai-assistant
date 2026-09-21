"""Groq text and local function-calling provider."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from app.core.llm import (
    LLMProvider,
    Message,
    ModelResponse,
    ProviderError,
    ToolCall,
    ToolResult,
)

SYSTEM_INSTRUCTION = """You are A.M.I.G.O. — Assistant for Managing Information & General Operations.
You are a concise, capable desktop agent for the user's local Linux/WSL environment.
Use available MCP-backed functions whenever the user asks for a real action or current system/web
information. Never claim success without a successful tool result. Never invent system data or web
results. Ask one concise clarification when required. Do not expose secrets or request passwords.
Never bypass permissions. You cannot execute shell commands: only declared functions exist, and
administrator approval is handled outside the model. Do not claim an application opened unless its
tool confirms it. Prefer brief direct answers for simple tasks and synthesize multiple tool results
when the request needs them."""

LOGGER = logging.getLogger("local_assistant.provider")
T = TypeVar("T")


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        return headers.get(name)
    except (AttributeError, TypeError):
        return None


def _retry_after(exc: BaseException) -> float | None:
    raw = _header(getattr(exc, "response", None), "retry-after")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except (TypeError, ValueError):
        return None


def normalize_groq_error(exc: BaseException, *, model: str) -> ProviderError:
    """Map SDK/network failures to secret-free provider errors."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    request_id = _header(response, "x-request-id") or getattr(exc, "request_id", None)
    retry_after = _retry_after(exc)
    if name in {"AuthenticationError"} or status == 401:
        category, message = "authentication", "Groq rejected the configured API key."
    elif name in {"PermissionDeniedError"} or status == 403:
        category, message = "permission", "The Groq project cannot use the configured model."
    elif name in {"NotFoundError"} or status == 404:
        category, message = "invalid_model", f"The configured Groq model {model!r} is unavailable."
    elif name in {"BadRequestError", "UnprocessableEntityError"} or status in {400, 413, 422}:
        category, message = "invalid_request", "Groq could not process the model request."
    elif name == "RateLimitError" or status == 429:
        category, message = "rate_limit", "Groq's rate limit was reached."
    elif name == "APITimeoutError" or isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        category, message = "timeout", "Groq did not respond before the configured timeout."
    elif name == "APIConnectionError":
        category, message = "connection", "A.M.I.G.O. could not connect to Groq."
    elif status == 498 or (isinstance(status, int) and status >= 500):
        category, message = "transient_provider", "Groq is temporarily unavailable."
    else:
        category, message = "transient_provider", "Groq returned an unexpected provider error."
    return ProviderError(
        category,
        message,
        status_code=status if isinstance(status, int) else None,
        retry_after=retry_after,
        model=model,
        request_id=str(request_id) if request_id else None,
    )


def _is_retryable(error: ProviderError) -> bool:
    return error.category in {"rate_limit", "timeout", "connection", "transient_provider"}


async def call_with_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    model: str,
    max_retries: int,
) -> T:
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except ProviderError:
            raise
        except Exception as exc:
            error = normalize_groq_error(exc, model=model)
            delay = error.retry_after
            can_retry = attempt < max_retries and _is_retryable(error)
            if delay is not None and delay > 5:
                can_retry = False
            LOGGER.warning(
                "groq_request_failed category=%s status=%s model=%s request_id=%s attempt=%s retry_after=%s",
                error.category,
                error.status_code,
                model,
                error.request_id,
                attempt + 1,
                delay,
            )
            if not can_retry:
                raise error from exc
            await asyncio.sleep(delay if delay is not None else 0.5 * (2**attempt) + random.random() * 0.1)
    raise AssertionError("retry loop exhausted")


class GroqProvider(LLMProvider):
    name = "groq"
    available = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 60,
        max_retries: int = 1,
        client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        if not model:
            raise ValueError("GROQ_MODEL must not be empty")
        if client is None:
            from groq import AsyncGroq

            client = AsyncGroq(api_key=api_key, timeout=timeout, max_retries=0)
        self.model = model
        self.timeout = timeout
        self.max_retries = max(0, min(int(max_retries), 2))
        self._client = client

    @staticmethod
    def _messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            *({"role": item.role, "content": item.content} for item in messages),
        ]

    @staticmethod
    def _tools(tools: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "parameters": item.get("input_schema")
                    or {"type": "object", "properties": {}},
                },
            }
            for item in tools
        ]

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> str:
        response = await self.generate_turn(messages, tools)
        if response.tool_calls:
            raise ProviderError(
                "malformed_response",
                "Groq requested a tool outside the assistant agent loop.",
                model=self.model,
            )
        return response.text

    async def generate_turn(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        continuation: Any = None,
        tool_results: Sequence[ToolResult] | None = None,
    ) -> ModelResponse:
        chat_messages = list(continuation) if continuation is not None else self._messages(messages)
        for item in tool_results or ():
            payload = {"error": item.error} if item.error else {"result": item.result}
            chat_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.call_id,
                    "name": item.name,
                    "content": json.dumps(payload, default=str, separators=(",", ":")),
                }
            )
        request: dict[str, Any] = {"model": self.model, "messages": chat_messages}
        declared_tools = self._tools(tools)
        if declared_tools:
            request.update({"tools": declared_tools, "tool_choice": "auto"})

        async def create() -> Any:
            return await self._client.chat.completions.create(**request)

        response = await call_with_retry(create, model=self.model, max_retries=self.max_retries)
        choices = getattr(response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        if message is None:
            raise ProviderError(
                "malformed_response", "Groq returned no usable response.", model=self.model
            )
        content = getattr(message, "content", None)
        text = content.strip() if isinstance(content, str) else ""
        calls: list[ToolCall] = []
        native_calls: list[dict[str, Any]] = []
        for call in getattr(message, "tool_calls", None) or ():
            function = getattr(call, "function", None)
            raw_name = str(getattr(function, "name", "") or "")
            raw_call_id = str(getattr(call, "id", "") or "")
            name = raw_name or "unknown_tool"
            call_id = raw_call_id or f"invalid-{len(calls) + 1}"
            raw_arguments = getattr(function, "arguments", "{}")
            error = None
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                if not isinstance(arguments, dict):
                    raise TypeError("arguments must be a JSON object")
            except (TypeError, ValueError, json.JSONDecodeError):
                arguments = {}
                error = "Tool arguments were not a valid JSON object"
            if not raw_name:
                error = "Tool call did not include a function name"
            if not raw_call_id:
                error = "Tool call did not include a call ID"
            calls.append(ToolCall(name, arguments, call_id, error))
            native_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": raw_arguments
                        if isinstance(raw_arguments, str)
                        else json.dumps(raw_arguments, default=str),
                    },
                }
            )
        assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
        if native_calls:
            assistant_message["tool_calls"] = native_calls
        chat_messages.append(assistant_message)
        if not calls and not text:
            raise ProviderError(
                "malformed_response", "Groq returned no usable response.", model=self.model
            )
        return ModelResponse(text=text, tool_calls=tuple(calls), continuation=chat_messages)

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
