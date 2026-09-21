"""Provider-neutral speech interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.llm import ProviderError


class SpeechError(ProviderError):
    pass


@dataclass(frozen=True, slots=True)
class SpeechAudio:
    data: bytes
    media_type: str = "audio/wav"


class SpeechProvider(ABC):
    @abstractmethod
    async def transcribe(self, wav_bytes: bytes, utterance_id: str) -> str:
        """Return one finalized transcript."""

    @abstractmethod
    async def synthesize(self, text: str) -> SpeechAudio:
        """Return browser-playable speech audio."""

    async def aclose(self) -> None:
        """Release provider-owned connections, when applicable."""
