from pathlib import Path

import pytest

from app.core.assistant import Assistant
from app.core.router import IntentRouter
from app.core.permissions import PermissionManager
from app.providers.rule_based import RuleBasedProvider


@pytest.fixture(autouse=True)
def isolated_windows_profile(monkeypatch):
    monkeypatch.setattr("app.core.router.windows_profile", lambda: None)


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
        ("Search the web for OpenAI", "open_browser_search", {"query": "OpenAI"}),
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


def test_legacy_paths_do_not_change_home():
    router = IntentRouter(home=Path('/home/tester'), allowed_paths=[Path('/elsewhere')])
    assert router.route('show files in Downloads').arguments == {'path': '/home/tester/Downloads'}
    assert router.route('create file /opt/service/app.conf').arguments['path'] == '/opt/service/app.conf'


def test_any_application_is_routed(router):
    route = router.route('open custom-editor')
    assert route.tool == 'open_application'
    assert route.arguments == {'application': 'custom-editor'}


class FakeTools:
    def __init__(self) -> None:
        self.calls = []

    async def call(self, tool, arguments, *, permission_result):
        self.calls.append((tool, arguments, permission_result))
        return {"path": arguments["path"], "created": True}


@pytest.mark.asyncio
async def test_legacy_confirmation_switch_cannot_prompt_for_standard_action(router):
    tools = FakeTools()
    async def prompt(*args):
        pytest.fail('Normal actions must run directly')
    assistant = Assistant(tools, RuleBasedProvider(), router=router, confirm=prompt,
                          permissions=PermissionManager(confirm_actions=True))
    assert await assistant.handle('create folder test') == 'Created: /home/tester/test'
    assert tools.calls[0][2] == 'direct_request'


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


def test_home_controls_relative_paths(tmp_path):
    root = tmp_path / "home"
    router = IntentRouter(home=root, allowed_paths=[tmp_path / "ignored"])
    assert router.route("create folder test").arguments == {"path": str(root / "test")}
    assert router.route("create file testing.txt").arguments["path"] == str(root / "testing.txt")
    assert router.route("create folder child in test folder").arguments["path"] == str(root / "test/child")
    assert router.route("move a.txt to b.txt").arguments == {"source": str(root / "a.txt"), "destination": str(root / "b.txt")}


def test_windows_downloads_discovered_from_profile(tmp_path, monkeypatch):
    home, windows = tmp_path / "home", tmp_path / "windows"
    home.mkdir()
    (windows / "Downloads").mkdir(parents=True)
    monkeypatch.setattr("app.core.router.windows_profile", lambda: windows)
    router = IntentRouter(home=home)
    assert router.route("show files in Downloads").arguments["path"] == str(windows / "Downloads")


def test_creation_preserves_quoted_name_and_content(tmp_path):
    router = IntentRouter(home=tmp_path)
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
    assert router.route('run date; touch /tmp/unsafe').arguments['shell'] is False


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


@pytest.mark.parametrize(('text', 'tool', 'arguments'), [
    ('show files in /etc page 2', 'list_directory', {'path': '/etc', 'offset': 200}),
    ('show files', 'list_directory', {'path': '/home/tester'}),
    ('create file at /opt/project/settings.conf', 'create_text_file', {'path': '/opt/project/settings.conf', 'content': ''}),
    ('create folder reports at /tmp/team', 'create_directory', {'path': '/tmp/team/reports'}),
    ('show files in C:', 'list_directory', {'path': '/mnt/c'}),
    ('show files in root', 'list_directory', {'path': '/'}),
    ('find file settings in /etc', 'find_files', {'path': '/etc', 'name': 'settings'}),
    ('write file /tmp/demo.env with content KEY=value', 'write_text_file', {'path': '/tmp/demo.env', 'content': 'KEY=value', 'append': False}),
    ('copy /tmp/a to /mnt/d/a', 'copy_path', {'source': '/tmp/a', 'destination': '/mnt/d/a'}),
    ('open /tmp/notes.txt', 'open_path', {'path': '/tmp/notes.txt'}),
])
def test_wide_filesystem_routes(router, text, tool, arguments):
    route = router.route(text)
    assert route.tool == tool
    assert route.arguments == arguments


def test_explicit_administrator_and_shell_routes(router):
    assert router.route('sudo create folder /opt/demo').administrator
    assert router.route('create folder /opt/demo as administrator').administrator
    route = router.route('sudo apt update')
    assert route.administrator and route.arguments['command'] == 'apt update'
    assert router.route('run shell ls /etc | head').arguments['shell'] is True


def test_destination_first_and_on_phrases(router):
    assert router.route('create file in /tmp/project called settings.ini').arguments['path'] == '/tmp/project/settings.ini'
    assert router.route('create folder reports on Desktop').arguments['path'] == '/home/tester/Desktop/reports'
    assert router.route('list directory /etc').arguments['path'] == '/etc'
