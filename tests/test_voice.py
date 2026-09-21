from array import array

import pytest

from app.voice.audio import (
    END_SILENCE_FRAMES,
    FRAME_BYTES,
    MIN_SPEECH_FRAMES,
    UtteranceSegmenter,
    pcm_to_wav,
    validate_pcm_chunk,
)
from app.voice.protocol import TranscriptEvent
from app.voice.session import BufferedVoiceSession


def frame(level=0):
    return array("h", [level] * (FRAME_BYTES // 2)).tobytes()


def test_pcm_validation_wav_and_protocol():
    assert validate_pcm_chunk(b"\x00\x00") == b"\x00\x00"
    with pytest.raises(ValueError, match="empty"):
        validate_pcm_chunk(b"")
    with pytest.raises(ValueError, match="16-bit"):
        validate_pcm_chunk(b"\x00")
    wav = pcm_to_wav(frame(1000))
    assert wav.startswith(b"RIFF") and b"WAVE" in wav[:16]
    assert TranscriptEvent("open browser", True, "s:1").as_json() == {
        "type": "final", "text": "open browser", "utterance_id": "s:1"
    }


def test_segmenter_ignores_silence_and_finalizes_one_utterance():
    segmenter = UtteranceSegmenter()
    results, started = segmenter.push(frame() * 40)
    assert results == [] and started is False
    results, started = segmenter.push(frame(2500) * (MIN_SPEECH_FRAMES + 5))
    assert started is True and results == []
    results, _ = segmenter.push(frame() * END_SILENCE_FRAMES)
    assert len(results) == 1
    assert len(results[0]) >= (MIN_SPEECH_FRAMES + END_SILENCE_FRAMES) * FRAME_BYTES


def test_segmenter_rejects_too_short_speech_and_flushes_valid_partial():
    short = UtteranceSegmenter()
    results, _ = short.push(frame(2500) * 5 + frame() * END_SILENCE_FRAMES)
    assert results == []
    valid = UtteranceSegmenter()
    valid.push(frame(2500) * (MIN_SPEECH_FRAMES + 5))
    assert valid.flush()


class FakeSpeech:
    def __init__(self):
        self.calls = []
    async def transcribe(self, wav, utterance_id):
        self.calls.append((wav, utterance_id))
        return "Hey Amigo show CPU"


class FailingSpeech(FakeSpeech):
    async def transcribe(self, wav, utterance_id):
        self.calls.append((wav, utterance_id))
        raise RuntimeError("provider failure")


@pytest.mark.asyncio
async def test_buffered_session_makes_one_request_per_final_utterance():
    speech = FakeSpeech()
    session = BufferedVoiceSession(speech=speech)
    await session.__aenter__()
    for chunk in [frame(2500)] * (MIN_SPEECH_FRAMES + 5):
        await session.send_audio(chunk)
    for chunk in [frame()] * END_SILENCE_FRAMES:
        await session.send_audio(chunk)
    await session.end_audio()
    events = [event async for event in session.events()]
    await session.__aexit__(None, None, None)
    finals = [event for event in events if event["type"] == "final"]
    assert len(speech.calls) == 1
    assert len(finals) == 1
    assert finals[0]["text"] == "Hey Amigo show CPU"
    assert finals[0]["utterance_id"] == speech.calls[0][1]


@pytest.mark.asyncio
async def test_buffered_session_recovers_after_transcription_failure():
    speech = FailingSpeech()
    session = BufferedVoiceSession(speech=speech)
    await session.__aenter__()
    await session.send_audio(frame(2500) * (MIN_SPEECH_FRAMES + 5))
    await session.send_audio(frame() * END_SILENCE_FRAMES)
    await session.end_audio()
    events = [event async for event in session.events()]
    await session.__aexit__(None, None, None)
    assert len(speech.calls) == 1
    assert any(event["type"] == "error" and event["recoverable"] for event in events)
    assert events[-1]["state"] == "listening"
