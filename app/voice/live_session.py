"""Trusted server-side Gemini Live transcription session."""

from __future__ import annotations

from typing import Any, AsyncIterator

from app.voice.audio import PCM_MIME_TYPE, validate_pcm_chunk
from app.voice.protocol import TranscriptEvent


class VoiceUnavailableError(RuntimeError):
    pass


class GeminiLiveSession:
    """Streams PCM to Gemini and yields transcription only; no tools execute here.

    Final transcripts are sent through the normal Assistant HTTP command path so
    text and voice share the same reasoning, MCP validation, and approval policy.
    """

    def __init__(self, *, api_key: str, model: str, client: Any = None) -> None:
        if not api_key:
            raise VoiceUnavailableError("Gemini voice is not configured. Add GEMINI_API_KEY.")
        if not model:
            raise VoiceUnavailableError("GEMINI_LIVE_MODEL is not configured.")
        from google import genai

        self.model = model
        self._client = client or genai.Client(api_key=api_key)
        self._connection = None
        self._session = None

    async def __aenter__(self) -> "GeminiLiveSession":
        from google.genai import types

        config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=[]
            ),
            system_instruction=(
                "Transcribe the user's microphone accurately. Return transcription only. "
                "A separate trusted assistant core handles commands and tools."
            ),
        )
        try:
            self._connection = self._client.aio.live.connect(model=self.model, config=config)
            self._session = await self._connection.__aenter__()
        except Exception as exc:
            raise VoiceUnavailableError("I couldn't connect to Gemini Live.") from exc
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._connection is not None:
            await self._connection.__aexit__(exc_type, exc, traceback)

    async def send_audio(self, chunk: bytes) -> None:
        from google.genai import types

        if self._session is None:
            raise VoiceUnavailableError("Gemini Live session is not connected")
        await self._session.send_realtime_input(
            audio=types.Blob(data=validate_pcm_chunk(chunk), mime_type=PCM_MIME_TYPE)
        )

    async def end_audio(self) -> None:
        if self._session is not None:
            await self._session.send_realtime_input(audio_stream_end=True)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        if self._session is None:
            raise VoiceUnavailableError("Gemini Live session is not connected")
        async for response in self._session.receive():
            content = getattr(response, "server_content", None)
            if not content:
                continue
            interim = getattr(content, "interim_input_transcription", None)
            interim_text = getattr(interim, "text", "") if interim else ""
            if interim_text:
                yield TranscriptEvent(interim_text.strip(), False)
            final = getattr(content, "input_transcription", None)
            final_text = getattr(final, "text", "") if final else ""
            if final_text:
                yield TranscriptEvent(final_text.strip(), True)
