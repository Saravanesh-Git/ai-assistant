"""No-model fallback provider."""

from __future__ import annotations

from typing import Any, Sequence

from app.core.llm import LLMProvider, Message


class RuleBasedProvider(LLMProvider):
    name = "rule_based"
    available = True

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> str:
        return (
            "I can handle system usage, battery and disk checks; list allowed user folders; "
            "create folders; launch allowlisted apps; and search the web. Try “show cpu” or "
            "“search the web for FastAPI”."
        )

