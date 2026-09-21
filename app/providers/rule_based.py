"""No-model fallback provider."""

from __future__ import annotations

from typing import Any, Sequence

from app.core.llm import LLMProvider, Message


class RuleBasedProvider(LLMProvider):
    name = "rule_based"
    available = True

    def __init__(self, fallback_reason: str | None = None) -> None:
        self.fallback_reason = fallback_reason

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> str:
        return (
            "I'm A.M.I.G.O. I can check your system, battery, and disk; list and read your files; "
            "create, write, find, copy, and move files anywhere your account can access; run commands; open desktop apps; and search in your browser. Try “show cpu” or "
            "“search the web for FastAPI”."
        )
