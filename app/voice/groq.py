"""Groq Whisper and Orpheus speech adapter."""

from __future__ import annotations

import inspect
from typing import Any

from app.core.llm import ProviderError
from app.providers.groq import call_with_retry
from app.voice.service import SpeechAudio, SpeechError, SpeechProvider


class GroqSpeechProvider(SpeechProvider):
    def __init__(
        self,
        *,
        api_key: str,
        stt_model: str,
        tts_model: str,
        tts_voice: str,
        timeout: float = 60,
        max_retries: int = 1,
        client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError("GROQ_API_KEY is required for voice")
        if not stt_model:
            raise ValueError("GROQ_STT_MODEL must not be empty")
        if client is None:
            from groq import AsyncGroq

            client = AsyncGroq(api_key=api_key, timeout=timeout, max_retries=0)
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.max_retries = max(0, min(int(max_retries), 2))
        self._client = client

    async def _call(self, operation: Any, model: str) -> Any:
        try:
            return await call_with_retry(
                operation, model=model, max_retries=self.max_retries
            )
        except ProviderError as exc:
            raise SpeechError(
                exc.category,
                str(exc),
                status_code=exc.status_code,
                retry_after=exc.retry_after,
                model=exc.model,
                request_id=exc.request_id,
            ) from exc

    async def transcribe(self, wav_bytes: bytes, utterance_id: str) -> str:
        if not wav_bytes:
            raise SpeechError("invalid_request", "The recorded utterance was empty.")

        async def create() -> Any:
            return await self._client.audio.transcriptions.create(
                file=(f"{utterance_id}.wav", wav_bytes, "audio/wav"),
                model=self.stt_model,
                response_format="json",
                temperature=0,
            )

        response = await self._call(create, self.stt_model)
        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise SpeechError(
                "malformed_response",
                "Groq speech-to-text returned no transcript.",
                model=self.stt_model,
            )
        return text.strip()

    async def synthesize(self, text: str) -> SpeechAudio:
        text = text.strip()
        if not text:
            raise SpeechError("invalid_request", "There is no response to speak.")
        if not self.tts_model or not self.tts_voice:
            raise SpeechError("configuration", "Groq voice output is not configured.")

        async def create() -> Any:
            return await self._client.audio.speech.create(
                model=self.tts_model,
                voice=self.tts_voice,
                input=text,
                response_format="wav",
            )

        response = await self._call(create, self.tts_model)
        reader = getattr(response, "aread", None) or getattr(response, "read", None)
        if reader is not None:
            data = reader()
            if inspect.isawaitable(data):
                data = await data
        else:
            data = getattr(response, "content", None)
        if not isinstance(data, bytes) or not data:
            raise SpeechError(
                "malformed_response",
                "Groq text-to-speech returned no audio.",
                model=self.tts_model,
            )
        return SpeechAudio(data)

    async def aclose(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
