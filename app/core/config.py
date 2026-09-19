"""Environment-driven configuration with conservative defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


@dataclass(frozen=True, slots=True)
class Settings:
    # Legacy constructor fields remain compatible; environment allowlists and
    # confirm-all switches are intentionally ignored. OS permissions are authoritative.
    confirm_actions: bool = False
    allowed_paths: tuple[Path, ...] = (Path("/"),)
    searxng_url: str = field(default_factory=lambda: os.getenv("SEARXNG_URL", "http://localhost:8080"))
    command_timeout_seconds: int = field(
        default_factory=lambda: _int_env("COMMAND_TIMEOUT_SECONDS", 120, 5, 600)
    )
    max_file_size: int = field(
        default_factory=lambda: _int_env("MAX_FILE_SIZE", 2 * 1024 * 1024, 1024, 2 * 1024 * 1024)
    )
    max_web_response_size: int = field(
        default_factory=lambda: _int_env(
            "MAX_WEB_RESPONSE_SIZE", 2 * 1024 * 1024, 16 * 1024, 2 * 1024 * 1024
        )
    )
    web_timeout_seconds: int = field(
        default_factory=lambda: _int_env("WEB_TIMEOUT_SECONDS", 10, 1, 10)
    )
    max_concurrent_tools: int = field(
        default_factory=lambda: _int_env("MAX_CONCURRENT_TOOLS", 2, 1, 2)
    )
    history_limit: int = field(
        default_factory=lambda: _int_env("CONVERSATION_HISTORY_LIMIT", 12, 2, 50)
    )
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "").strip())
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "rule_based").lower())
    log_file: Path = field(default_factory=lambda: Path(os.getenv("LOG_FILE", "local-assistant.log")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    @property
    def lightweight_mode(self) -> bool:
        try:
            import psutil

            return psutil.virtual_memory().total <= 8 * 1024**3
        except Exception:
            return True


def load_settings() -> Settings:
    return Settings()
