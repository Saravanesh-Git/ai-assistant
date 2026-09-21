"""Validation and lightweight segmentation for browser PCM audio."""

from __future__ import annotations

import io
import math
import wave
from array import array
from collections import deque

PCM_RATE = 16_000
PCM_MIME_TYPE = "audio/pcm;rate=16000"
MAX_AUDIO_CHUNK_BYTES = 64 * 1024
FRAME_MS = 20
FRAME_BYTES = PCM_RATE * FRAME_MS // 1000 * 2
PRE_ROLL_FRAMES = 300 // FRAME_MS
END_SILENCE_FRAMES = 650 // FRAME_MS + 1
MIN_SPEECH_FRAMES = 250 // FRAME_MS + 1
MIN_TOTAL_FRAMES = 350 // FRAME_MS + 1
MAX_UTTERANCE_FRAMES = 20_000 // FRAME_MS


def validate_pcm_chunk(chunk: bytes) -> bytes:
    if not chunk:
        raise ValueError("Audio chunk is empty")
    if len(chunk) > MAX_AUDIO_CHUNK_BYTES:
        raise ValueError("Audio chunk is too large")
    if len(chunk) % 2:
        raise ValueError("PCM16 audio must contain complete 16-bit samples")
    return chunk


def pcm_rms(frame: bytes) -> int:
    samples = array("h")
    samples.frombytes(frame)
    if not samples:
        return 0
    return math.isqrt(sum(sample * sample for sample in samples) // len(samples))


def pcm_to_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(PCM_RATE)
        target.writeframes(pcm)
    return output.getvalue()


class UtteranceSegmenter:
    """Energy-based VAD with bounded pre-roll and utterance duration."""

    def __init__(self) -> None:
        self.remainder = bytearray()
        self.pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_FRAMES)
        self.recent_voice: deque[bool] = deque(maxlen=5)
        self.recording: list[bytes] | None = None
        self.speech_frames = 0
        self.silence_frames = 0
        self.noise_floor = 100.0

    def push(self, chunk: bytes) -> tuple[list[bytes], bool]:
        self.remainder.extend(validate_pcm_chunk(chunk))
        utterances: list[bytes] = []
        started = False
        while len(self.remainder) >= FRAME_BYTES:
            frame = bytes(self.remainder[:FRAME_BYTES])
            del self.remainder[:FRAME_BYTES]
            result, frame_started = self._frame(frame)
            started = started or frame_started
            if result is not None:
                utterances.append(result)
        return utterances, started

    def _frame(self, frame: bytes) -> tuple[bytes | None, bool]:
        level = pcm_rms(frame)
        threshold = max(500.0, self.noise_floor * 3.0)
        voiced = level >= threshold
        if self.recording is None:
            if not voiced:
                self.noise_floor = self.noise_floor * 0.95 + level * 0.05
            self.pre_roll.append(frame)
            self.recent_voice.append(voiced)
            if len(self.recent_voice) == 5 and sum(self.recent_voice) >= 3:
                self.recording = list(self.pre_roll)
                self.speech_frames = sum(self.recent_voice)
                self.silence_frames = 0
                return None, True
            return None, False

        self.recording.append(frame)
        if voiced:
            self.speech_frames += 1
            self.silence_frames = 0
        else:
            self.silence_frames += 1
        if (
            self.silence_frames >= END_SILENCE_FRAMES
            or len(self.recording) >= MAX_UTTERANCE_FRAMES
        ):
            return self._finalize(), False
        return None, False

    def flush(self) -> bytes | None:
        self.remainder.clear()
        return self._finalize()

    def _finalize(self) -> bytes | None:
        frames = self.recording or []
        valid = self.speech_frames >= MIN_SPEECH_FRAMES and len(frames) >= MIN_TOTAL_FRAMES
        result = b"".join(frames) if valid else None
        self.pre_roll.clear()
        self.recent_voice.clear()
        self.recording = None
        self.speech_frames = 0
        self.silence_frames = 0
        return result
