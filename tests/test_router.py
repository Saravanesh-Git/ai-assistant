from pathlib import Path

import pytest

from app.core.assistant import Assistant
from app.core.router import IntentRouter
from app.core.permissions import PermissionManager
from app.providers.rule_based import RuleBasedProvider


@pytest.fixture
def router() -> IntentRouter:
    return IntentRouter(home=Path("/home/tester"))


@pytest.mark.parametrize(
    ("message", "tool", "arguments"),
    [
        ("show cpu", "get_cpu_usage", {}),
        ("what is my cpu usage?", "get_cpu_usage", {}),
        ("check ram", "get_memory_usage", {}),
        ("how much disk space do I have?", "get_disk_usage", {"path": "/"}),
        ("open firefox", "open_application", {"application": "firefox"}),
        ("search Python", "open_browser_search", {"query": "Python"}),
        (
            "search the web for latest Python news",
            "open_browser_search",
            {"query": "latest Python news"},
        ),
        ("show me the current directory", "run_safe_command", {"command_id": "get_current_directory"}),
    ],
)
def test_common_routes(router: IntentRouter, message: str, tool: str, arguments: dict) -> None:
    route = router.route(message)
    assert route.tool == tool
    assert route.arguments == arguments


def test_directory_alias(router: IntentRouter) -> None:
    route = router.route("show files in Downloads")
    assert route.tool == "list_directory"
    assert route.arguments == {"path": "/home/tester/Downloads"}


def test_create_defaults_to_home_without_config(router: IntentRouter) -> None:
    route = router.route("create a folder called test")
    assert route.tool == "create_directory"
    assert route.arguments == {"path": "/home/tester/test"}


def test_configured_wsl_folder_overrides_missing_home_alias() -> None:
    router = IntentRouter(
        home=Path("/home/tester"),
        allowed_paths=[Path("/mnt/c/Users/Tester/Downloads"), Path("/home/tester/library")],
    )
    downloads = router.route("show files in Downloads")
    library = router.route("show files in library")
    assert downloads.arguments == {"path": "/mnt/c/Users/Tester/Downloads"}
    assert library.arguments == {"path": "/home/tester/library"}


def test_unknown_application_is_not_a_tool_call(router: IntentRouter) -> None:
    route = router.route("open dangerous-app")
    assert route.intent == "unsupported_application"
    assert route.tool is None


class FakeTools:
    def __init__(self) -> None:
        self.calls = []

    async def call(self, tool, arguments, *, permission_result):
        self.calls.append((tool, arguments, permission_result))
        return {"path": arguments["path"], "created": True}


@pytest.mark.asyncio
async def test_write_is_cancelled_without_confirmation(router: IntentRouter) -> None:
    tools = FakeTools()
    assistant = Assistant(tools, RuleBasedProvider(), router=router, permissions=PermissionManager(confirm_actions=True))
    response = await assistant.handle("create folder called test")
    assert response == "Action cancelled."
    assert tools.calls == []


@pytest.mark.asyncio
async def test_confirmed_write_reaches_tool_manager(router: IntentRouter) -> None:
    tools = FakeTools()

    async def approve(description, tool, arguments):
        return True

    assistant = Assistant(tools, RuleBasedProvider(), router=router, confirm=approve, permissions=PermissionManager(confirm_actions=True))
    response = await assistant.handle("create folder called test")
    assert response == "Created: /home/tester/test"
    assert tools.calls[0][2] == "user_allowed"


@pytest.mark.parametrize("command", [
    "create file testing.txt in test folder",
    "create file testing.txt in test",
    'create file "testing.txt" in "test"',
])
def test_file_destination_and_configured_default(tmp_path, command):
    home = tmp_path / "home"
    home.mkdir()
    (home / "test").mkdir()
    router = IntentRouter(home=home, allowed_paths=[home, tmp_path / "windows"])
    route = router.route(command)
    assert route.tool == "create_text_file"
    assert route.arguments == {"path": str(home / "test/testing.txt"), "content": ""}


def test_configured_root_controls_relative_paths(tmp_path):
    root = tmp_path / "work"
    router = IntentRouter(home=tmp_path / "home", allowed_paths=[root])
    assert router.route("create folder test").arguments == {"path": str(root / "test")}
    assert router.route("create file testing.txt").arguments["path"] == str(root / "testing.txt")
    assert router.route("create folder child in test folder").arguments["path"] == str(root / "test/child")
    assert router.route("move a.txt to b.txt").arguments == {"source": str(root / "a.txt"), "destination": str(root / "b.txt")}


def test_windows_downloads_under_allowed_parent(tmp_path):
    home, windows = tmp_path / "home", tmp_path / "windows"
    home.mkdir()
    (windows / "Downloads").mkdir(parents=True)
    router = IntentRouter(home=home, allowed_paths=[home, windows])
    assert router.route("show files in Downloads").arguments["path"] == str(windows / "Downloads")


def test_creation_preserves_quoted_name_and_content(tmp_path):
    router = IntentRouter(allowed_paths=[tmp_path])
    route = router.route('create file "notes in May.txt" in test folder with content words in text')
    assert route.arguments == {"path": str(tmp_path / "test/notes in May.txt"), "content": "words in text"}
    assert router.route("create file /tmp/a.txt in test folder").intent == "unsafe_path"


@pytest.mark.parametrize(('message', 'query'), [
    ('search for "CPU usage" in the web', 'CPU usage'),
    ('Hey Amigo, search the web for memory management', 'memory management'),
    ('look up battery technology', 'battery technology'),
    ('search for cats & dogs on the web', 'cats & dogs'),
])
def test_browser_search_precedes_system_keywords(router, message, query):
    route = router.route(message)
    assert route.tool == 'open_browser_search'
    assert route.arguments == {'query': query}


@pytest.mark.parametrize(('message', 'command'), [
    ('run date', 'get_date'), ('execute whoami', 'get_logged_in_user'),
    ('run uname -r', 'get_kernel_version'), ('run hostname -I', 'get_ip_address'),
])
def test_command_routes(router, message, command):
    assert router.route(message).arguments == {'command_id': command}
    assert router.route('run date; touch /tmp/unsafe').tool is None


def test_windows_paths_and_aliases(router):
    assert router.route(r'create file C:\Users\Me\Documents\note.txt').arguments['path'] == '/mnt/c/Users/Me/Documents/note.txt'
    assert router.route('open file explorer').arguments == {'application': 'windows_files'}
    assert router.route('open VS Code').arguments == {'application': 'code'}
    assert router.route('open windows edge').arguments == {'application': 'windows_edge'}
    assert router.route('create folder memory').tool == 'create_directory'
    assert router.route('show files in battery').tool == 'list_directory'


@pytest.mark.asyncio
async def test_direct_write_needs_no_confirmation(router):
    tools = FakeTools()
    async def unwanted_prompt(*args):
        pytest.fail('Direct commands must not ask for permission')
    assistant = Assistant(tools, RuleBasedProvider(), router=router, confirm=unwanted_prompt)
    assert await assistant.handle('create folder demo') == 'Created: /home/tester/demo'
    assert tools.calls[0][2] == 'direct_request'
    assert not PermissionManager().check_permission('unknown_tool', {}).allowed
