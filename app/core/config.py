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


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


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
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", "").strip())
    groq_model: str = field(
        default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    )
    groq_stt_model: str = field(
        default_factory=lambda: os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip()
    )
    groq_tts_model: str = field(
        default_factory=lambda: os.getenv(
            "GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english"
        ).strip()
    )
    groq_tts_voice: str = field(
        default_factory=lambda: os.getenv("GROQ_TTS_VOICE", "troy").strip()
    )
    groq_timeout_seconds: int = field(
        default_factory=lambda: _int_env("GROQ_TIMEOUT_SECONDS", 60, 5, 180)
    )
    groq_max_retries: int = field(
        default_factory=lambda: _int_env("GROQ_MAX_RETRIES", 1, 0, 2)
    )
    max_agent_tool_steps: int = field(
        default_factory=lambda: _int_env("MAX_AGENT_TOOL_STEPS", 6, 1, 12)
    )
    voice_enabled: bool = field(default_factory=lambda: _bool_env("VOICE_ENABLED", True))
    voice_output_enabled: bool = field(
        default_factory=lambda: _bool_env("VOICE_OUTPUT_ENABLED", True)
    )
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
