"""Gemini text and function-calling provider using Google's official SDK."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from app.core.llm import LLMProvider, Message, ModelResponse, ToolCall, ToolResult

SYSTEM_INSTRUCTION = """You are A.M.I.G.O. — Assistant for Managing Information & General Operations.
You are a concise, capable desktop agent for the user's local Linux/WSL environment.
Use available MCP-backed functions whenever the user asks for a real action or current system/web
information. Never claim success without a successful tool result. Never invent system data or web
results. Ask one concise clarification when required. Do not expose secrets or request passwords.
Never bypass permissions. You cannot execute shell commands: only declared functions exist, and
administrator approval is handled outside the model. Do not claim an application opened unless its
tool confirms it. Prefer brief direct answers for simple tasks and synthesize multiple tool results
when the request needs them."""


class GeminiProvider(LLMProvider):
    name = "gemini"
    available = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 60,
        client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        if not model:
            raise ValueError("GEMINI_MODEL must not be empty")
        from google import genai

        self.model = model
        self.timeout = timeout
        self._client = client or genai.Client(api_key=api_key)

    @staticmethod
    def _contents(messages: Sequence[Message]) -> list[Any]:
        from google.genai import types

        contents = []
        for message in messages:
            role = "model" if message.role == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=message.content)]))
        return contents

    @staticmethod
    def _tool_config(tools: Sequence[dict[str, Any]] | None) -> list[Any] | None:
        if not tools:
            return None
        from google.genai import types

        declarations = [
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters_json_schema=tool.get("input_schema") or {
                    "type": "object", "properties": {}
                },
            )
            for tool in tools
        ]
        return [types.Tool(function_declarations=declarations)]

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> str:
        response = await self.generate_turn(messages, tools)
        if response.tool_calls:
            raise RuntimeError("Gemini requested a tool outside the assistant agent loop")
        return response.text

    async def generate_turn(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
        *,
        continuation: Any = None,
        tool_results: Sequence[ToolResult] | None = None,
    ) -> ModelResponse:
        from google.genai import types

        contents = list(continuation) if continuation is not None else self._contents(messages)
        if tool_results:
            parts = []
            for item in tool_results:
                payload = {"error": item.error} if item.error else {"result": item.result}
                parts.append(types.Part.from_function_response(name=item.name, response=payload))
            contents.append(types.Content(role="user", parts=parts))
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            tools=self._tool_config(tools),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self.model, contents=contents, config=config
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise TimeoutError("Gemini did not respond before the configured timeout") from exc
        except Exception as exc:
            raise RuntimeError("Gemini is temporarily unavailable") from exc

        calls = tuple(
            ToolCall(
                name=str(call.name or ""),
                arguments=dict(call.args or {}),
                call_id=getattr(call, "id", None),
            )
            for call in (response.function_calls or [])
        )
        text = ""
        try:
            text = (response.text or "").strip()
        except (AttributeError, ValueError):
            pass
        candidate = response.candidates[0] if response.candidates else None
        content = getattr(candidate, "content", None)
        if content is not None:
            contents.append(content)
        if not calls and not text:
            raise RuntimeError("Gemini returned no usable response")
        return ModelResponse(text=text, tool_calls=calls, continuation=contents)
