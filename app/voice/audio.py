"""Validation for browser-to-backend PCM audio chunks."""

PCM_RATE = 16_000
PCM_MIME_TYPE = "audio/pcm;rate=16000"
MAX_AUDIO_CHUNK_BYTES = 64 * 1024


def validate_pcm_chunk(chunk: bytes) -> bytes:
    if not chunk:
        raise ValueError("Audio chunk is empty")
    if len(chunk) > MAX_AUDIO_CHUNK_BYTES:
        raise ValueError("Audio chunk is too large")
    if len(chunk) % 2:
        raise ValueError("PCM16 audio must contain complete 16-bit samples")
    return chunk
