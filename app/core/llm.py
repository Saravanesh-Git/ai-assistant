"""Provider-neutral language model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None


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
