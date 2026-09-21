import json
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.llm import Message, ProviderError, ToolCall, ToolResult
from app.providers.factory import create_provider
from app.providers.groq import SYSTEM_INSTRUCTION, GroqProvider, normalize_groq_error
from app.providers.rule_based import RuleBasedProvider
from app.voice.groq import GroqSpeechProvider


def response(*, text="", calls=()):
    tool_calls = [
        SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name=name, arguments=arguments),
        )
        for call_id, name, arguments in calls
    ]
    message = SimpleNamespace(content=text, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeCompletions:
    def __init__(self, responses=None, errors=None):
        self.responses = list(responses or [])
        self.errors = list(errors or [])
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.errors:
            error = self.errors.pop(0)
            if error is not None:
                raise error
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)
        self.closed = False

    async def close(self):
        self.closed = True


def test_groq_requires_backend_configuration():
    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        GroqProvider(api_key="", model="model", client=FakeClient(FakeCompletions()))
    provider = GroqProvider(
        api_key="secret", model="model", client=FakeClient(FakeCompletions())
    )
    assert provider.available and provider.name == "groq"
    assert "Never bypass permissions" in SYSTEM_INSTRUCTION


@pytest.mark.asyncio
async def test_groq_response_tool_mapping_and_continuation():
    completions = FakeCompletions(
        [
            response(calls=[("call-1", "get_cpu_usage", "{}")]),
            response(text="CPU usage is 12%."),
        ]
    )
    provider = GroqProvider(api_key="secret", model="model", client=FakeClient(completions))
    tools = ({"name": "get_cpu_usage", "description": "CPU", "input_schema": {"type": "object"}},)
    first = await provider.generate_turn([Message("user", "How busy is my CPU?")], tools)
    assert first.tool_calls == (ToolCall("get_cpu_usage", {}, "call-1"),)
    assert completions.requests[0]["tools"][0]["function"]["name"] == "get_cpu_usage"
    assert completions.requests[0]["messages"][0]["role"] == "system"
    second = await provider.generate_turn(
        [], tools, continuation=first.continuation,
        tool_results=[ToolResult("get_cpu_usage", {"cpu_percent": 12}, "call-1")],
    )
    assert second.text == "CPU usage is 12%."
    tool_message = next(
        item for item in completions.requests[1]["messages"] if item["role"] == "tool"
    )
    assert tool_message["tool_call_id"] == "call-1"
    assert json.loads(tool_message["content"])["result"]["cpu_percent"] == 12


@pytest.mark.asyncio
async def test_groq_multiple_and_malformed_tool_calls_are_preserved_safely():
    provider = GroqProvider(
        api_key="secret",
        model="model",
        client=FakeClient(FakeCompletions([response(calls=[
            ("one", "get_cpu_usage", "{}"),
            ("two", "list_directory", "not-json"),
        ])])),
    )
    result = await provider.generate_turn([Message("user", "check both")])
    assert len(result.tool_calls) == 2
    assert result.tool_calls[1].arguments == {}
    assert "valid JSON object" in result.tool_calls[1].argument_error


class FakeRateLimitError(Exception):
    status_code = 429
    response = SimpleNamespace(headers={"retry-after": "0"})


@pytest.mark.asyncio
async def test_groq_retries_once_and_normalizes_rate_limit(monkeypatch):
    completions = FakeCompletions(
        [response(text="ok")], errors=[FakeRateLimitError(), None]
    )
    provider = GroqProvider(
        api_key="do-not-leak", model="model", max_retries=1,
        client=FakeClient(completions),
    )
    monkeypatch.setattr("app.providers.groq.asyncio.sleep", lambda delay: _done())
    assert await provider.generate([Message("user", "hello")]) == "ok"
    assert len(completions.requests) == 2

    failing = GroqProvider(
        api_key="do-not-leak", model="model", max_retries=0,
        client=FakeClient(FakeCompletions(errors=[FakeRateLimitError()])),
    )
    with pytest.raises(ProviderError) as caught:
        await failing.generate([Message("user", "hello")])
    assert caught.value.category == "rate_limit"
    assert "do-not-leak" not in str(caught.value)


async def _done():
    return None


def test_factory_falls_back_when_groq_key_is_missing():
    provider = create_provider(Settings(llm_provider="groq", groq_api_key=""))
    assert isinstance(provider, RuleBasedProvider)
    assert "using local command mode" in provider.fallback_reason


@pytest.mark.parametrize(
    ("status", "category"),
    [(400, "invalid_request"), (401, "authentication"), (403, "permission"),
     (404, "invalid_model"), (422, "invalid_request"), (429, "rate_limit"),
     (500, "transient_provider")],
)
def test_groq_status_errors_are_classified_without_raw_details(status, category):
    error = RuntimeError("request-body-and-secret")
    error.status_code = status
    error.response = SimpleNamespace(headers={"x-request-id": "request-1"})
    normalized = normalize_groq_error(error, model="configured-model")
    assert normalized.category == category
    assert normalized.request_id == "request-1"
    assert "request-body-and-secret" not in str(normalized)


class FakeTranscriptions:
    def __init__(self):
        self.request = None
    async def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(text=" Hey Amigo ")


class FakeBinary:
    async def aread(self):
        return b"RIFF-audio"


class FakeSpeechEndpoint:
    def __init__(self):
        self.request = None
    async def create(self, **kwargs):
        self.request = kwargs
        return FakeBinary()


@pytest.mark.asyncio
async def test_groq_speech_transcription_and_synthesis():
    transcriptions = FakeTranscriptions()
    speech = FakeSpeechEndpoint()
    client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=transcriptions, speech=speech)
    )
    provider = GroqSpeechProvider(
        api_key="secret", stt_model="whisper", tts_model="orpheus",
        tts_voice="troy", client=client,
    )
    assert await provider.transcribe(b"wav", "u1") == "Hey Amigo"
    assert transcriptions.request["file"] == ("u1.wav", b"wav", "audio/wav")
    audio = await provider.synthesize("Done")
    assert audio.data == b"RIFF-audio"
    assert speech.request["voice"] == "troy"
    with pytest.raises(ProviderError, match="no response to speak"):
        await provider.synthesize("  ")
