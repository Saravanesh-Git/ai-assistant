"""Provider-neutral language model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None
    argument_error: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    name: str
    result: Any = None
    call_id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class ModelResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    continuation: Any = field(default=None, repr=False)


class ProviderError(RuntimeError):
    """Sanitized provider failure safe to surface without request or secret data."""

    def __init__(
        self,
        category: str,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
        model: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code
        self.retry_after = retry_after
        self.model = model
        self.request_id = request_id


class LLMProvider(ABC):
    name = "abstract"
    available = False

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> str:
        """Generate a text response. Tool calls still require core validation."""

    async def generate_turn(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        continuation: Any = None,
        tool_results: Sequence[ToolResult] | None = None,
    ) -> ModelResponse:
        """Return one reasoning turn. Providers may override for function calling."""
        if continuation is not None or tool_results:
            raise RuntimeError(f"{self.name} does not support tool continuations")
        return ModelResponse(text=await self.generate(messages, tools))

    async def aclose(self) -> None:
        """Release provider-owned connections, when applicable."""
