"""Provider-neutral language model interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


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

