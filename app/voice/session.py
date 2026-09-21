"""Buffered utterance session for the authenticated browser voice socket."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Self

from app.voice.audio import UtteranceSegmenter, pcm_to_wav
from app.voice.protocol import TranscriptEvent, error_event, status_event
from app.voice.service import SpeechProvider


class VoiceUnavailableError(RuntimeError):
    pass


class BufferedVoiceSession:
    def __init__(self, *, speech: SpeechProvider) -> None:
        self.speech = speech
        self.segmenter = UtteranceSegmenter()
        self.session_id = secrets.token_urlsafe(8)
        self.sequence = 0
        self._utterances: asyncio.Queue[tuple[str, bytes] | None] = asyncio.Queue(maxsize=2)
        self._events: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._ended = False

    async def __aenter__(self) -> Self:
        self._worker = asyncio.create_task(self._transcribe())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.end_audio()
        if self._worker is not None:
            await asyncio.gather(self._worker, return_exceptions=True)

    async def send_audio(self, chunk: bytes) -> None:
        if self._ended:
            return
        utterances, started = self.segmenter.push(chunk)
        if started:
            await self._events.put(status_event("recording", "Listening"))
        for pcm in utterances:
            await self._enqueue(pcm)

    async def _enqueue(self, pcm: bytes) -> None:
        self.sequence += 1
        utterance_id = f"{self.session_id}:{self.sequence}"
        try:
            self._utterances.put_nowait((utterance_id, pcm_to_wav(pcm)))
        except asyncio.QueueFull:
            await self._events.put(
                error_event("Voice is busy transcribing. Please repeat that request.", recoverable=True)
            )

    async def end_audio(self) -> None:
        if self._ended:
            return
        self._ended = True
        pcm = self.segmenter.flush()
        if pcm:
            await self._enqueue(pcm)
        await self._utterances.put(None)

    async def _transcribe(self) -> None:
        while True:
            item = await self._utterances.get()
            if item is None:
                break
            utterance_id, wav = item
            await self._events.put(status_event("transcribing", "Transcribing"))
            try:
                text = await self.speech.transcribe(wav, utterance_id)
                if text:
                    await self._events.put(TranscriptEvent(text, True, utterance_id).as_json())
            except Exception:  # noqa: BLE001 - keep the long-lived microphone session recoverable
                await self._events.put(
                    error_event(
                        "I couldn't transcribe that audio. Voice is still listening.",
                        recoverable=True,
                    )
                )
            await self._events.put(status_event("listening", "Voice ready"))
        await self._events.put(None)

    async def events(self) -> AsyncIterator[dict[str, object]]:
        while True:
            event = await self._events.get()
            if event is None:
                break
            yield event
