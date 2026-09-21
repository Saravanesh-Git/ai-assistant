import pytest

from app.core.assistant import Assistant
from app.core.config import Settings
from app.core.llm import LLMProvider, ModelResponse, ToolCall


class SequenceProvider(LLMProvider):
    name = "groq"
    available = True
    def __init__(self, responses):
        self.responses = list(responses)
        self.seen_tools = []
        self.seen_messages = []

    async def generate(self, messages, tools=None):
        return "unused"

    async def generate_turn(self, messages, tools=None, **kwargs):
        self.seen_tools.append(tuple(item["name"] for item in tools or ()))
        self.seen_messages.append(tuple(messages))
        return self.responses.pop(0)


class FakeTools:
    def __init__(self):
        self.calls = []
        self.settings = Settings(max_agent_tool_steps=6)

        def schema(props=None, required=None):
            return {
                "type": "object",
                "properties": props or {},
                "required": required or [],
            }

        self.tool_definitions = tuple(
            {"name":name, "description":name, "input_schema":tool_schema}
            for name, tool_schema in {
                "get_cpu_usage":schema(), "get_memory_usage":schema(),
                "list_directory":schema({"path":{"type":"string"}}, ["path"]),
                "open_application":schema({"application":{"type":"string"}}, ["application"]),
                "search_web":schema({"query":{"type":"string"}}, ["query"]),
                "run_command":schema({"command":{"type":"string"}}, ["command"]),
            }.items()
        )
    def validate_call(self, tool, arguments):
        definition = next(item for item in self.tool_definitions if item["name"] == tool)
        for required in definition["input_schema"].get("required", []):
            if required not in arguments:
                raise ValueError(f"{required} is required")

    async def call(self, tool, arguments, *, permission_result):
        self.calls.append((tool, arguments, permission_result))
        return {"tool":tool, **arguments}


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "arguments"), [
    ("get_cpu_usage", {}), ("get_memory_usage", {}),
    ("list_directory", {"path":"/tmp"}),
    ("open_application", {"application":"firefox"}),
    ("search_web", {"query":"FastAPI release"}),
])
async def test_model_tool_calls_go_only_through_validated_manager(tool, arguments):
    provider = SequenceProvider([
        ModelResponse(tool_calls=(ToolCall(tool, arguments),), continuation=["state"]),
        ModelResponse(text="Done"),
    ])
    tools = FakeTools()
    assistant = Assistant(tools, provider)
    assert await assistant.handle("Could you handle this natural language request?") == "Done"
    assert tools.calls == [(tool, arguments, "model_requested")]
    assert "run_command" not in provider.seen_tools[0]


@pytest.mark.asyncio
async def test_unknown_invalid_and_shell_calls_never_execute():
    provider = SequenceProvider([
        ModelResponse(tool_calls=(ToolCall("run_command", {"command":"id"}),
                                  ToolCall("unknown", {}),
                                  ToolCall("list_directory", {})), continuation=["state"]),
        ModelResponse(text="I could not run those calls."),
    ])
    tools = FakeTools()
    assistant = Assistant(tools, provider)
    assert await assistant.handle("Do something unspecified") == "I could not run those calls."
    assert tools.calls == []


@pytest.mark.asyncio
async def test_agent_loop_limit_stops_repeated_calls():
    provider = SequenceProvider([
        ModelResponse(tool_calls=(ToolCall("get_cpu_usage", {}),), continuation=[index])
        for index in range(3)
    ])
    tools = FakeTools()
    assistant = Assistant(tools, provider, max_tool_steps=2)
    reply = await assistant.handle("Please perform a longer analysis")
    assert "stopped after 2 tool calls" in reply
    assert len(tools.calls) == 2


@pytest.mark.asyncio
async def test_multi_tool_request_and_short_term_followup_context():
    provider = SequenceProvider([
        ModelResponse(tool_calls=(ToolCall("open_application", {"application":"code"}),
                                  ToolCall("get_cpu_usage", {})), continuation=["state"]),
        ModelResponse(text="VS Code is open. CPU usage is 12%."),
        ModelResponse(text="That CPU usage is low."),
    ])
    tools = FakeTools()
    assistant = Assistant(tools, provider)
    first = await assistant.handle("Open VS Code and then tell me my CPU usage")
    second = await assistant.handle("Is that high?")
    assert first == "VS Code is open. CPU usage is 12%."
    assert second == "That CPU usage is low."
    assert [call[0] for call in tools.calls] == ["open_application", "get_cpu_usage"]
    assert any(message.content == first for message in provider.seen_messages[-1])


@pytest.mark.asyncio
async def test_explicit_user_shell_command_bypasses_model_but_model_cannot_request_it():
    provider = SequenceProvider([ModelResponse(text="model should not run")])
    tools = FakeTools()
    assistant = Assistant(tools, provider)
    await assistant.handle("run printf hello")
    assert tools.calls[0][0] == "run_command"
    assert tools.calls[0][2] == "direct_request"
    assert provider.seen_messages == []

