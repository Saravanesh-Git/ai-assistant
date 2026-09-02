"""Optional Ollama chat adapter; never starts Ollama or downloads a model."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Sequence

import httpx

from app.core.llm import LLMProvider, Message


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, *, base_url: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model.strip()
        self.timeout = timeout
        self.available = bool(self.model and self._detect_ollama())

    @staticmethod
    def _detect_ollama() -> bool:
        executable = shutil.which("ollama")
        if executable is None:
            return False
        try:
            result = subprocess.run(
                [executable, "--version"],
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    async def generate(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> str:
        if not self.available:
            raise RuntimeError("Ollama is unavailable or OLLAMA_MODEL is not configured")
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        content = data.get("message", {}).get("content")
        if not isinstance(content, str):
            raise RuntimeError("Ollama returned a malformed response")
        return content.strip()
