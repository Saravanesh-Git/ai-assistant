from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from security.command_policy import CommandPolicyError
from security.path_policy import PathPolicy
from servers.linux_server.application_tools import open_application_data, run_safe_command_data
from servers.linux_server.file_tools import create_directory_data, list_directory_data, read_text_file_data
from servers.linux_server.system_tools import (
    get_battery_status_data,
    get_cpu_usage_data,
    get_disk_usage_data,
    get_memory_usage_data,
    get_system_info_data,
)


def test_system_tools_return_structured_data() -> None:
    info = get_system_info_data()
    cpu = get_cpu_usage_data()
    memory = get_memory_usage_data()
    disk = get_disk_usage_data("/")
    assert info["hostname"]
    assert info["cpu_cores"] >= 1
    assert 0 <= cpu["cpu_percent"] <= 100
    assert memory["total"].endswith(("MB", "GB", "TB"))
    assert disk["path"] == "/"


def test_no_battery_does_not_fail() -> None:
    with patch("servers.linux_server.system_tools.psutil.sensors_battery", return_value=None):
        assert get_battery_status_data() == {"available": False}


def test_file_tools(tmp_path: Path) -> None:
    root = tmp_path / "Projects"
    root.mkdir()
    policy = PathPolicy([root])
    created = create_directory_data(str(root / "demo"), policy)
    assert created["created"] is True
    note = root / "note.md"
    note.write_text("hello", encoding="utf-8")
    assert read_text_file_data(str(note), policy, 100)["content"] == "hello"
    listing = list_directory_data(str(root), policy)
    assert {item["name"] for item in listing["entries"]} == {"demo", "note.md"}


def test_application_uses_fixed_argv_without_shell() -> None:
    process = Mock(pid=4321)
    with (
        patch("servers.linux_server.application_tools.resolve_executable", return_value="/usr/bin/firefox"),
        patch("servers.linux_server.application_tools.subprocess.Popen", return_value=process) as popen,
    ):
        result = open_application_data("firefox")
    assert result["pid"] == 4321
    argv = popen.call_args.args[0]
    assert argv == ["/usr/bin/firefox"]
    assert popen.call_args.kwargs["shell"] is False


@pytest.mark.parametrize(
    "payload",
    [
        "firefox; rm -rf /",
        "$(rm -rf /)",
        "`rm -rf /`",
        "firefox && rm -rf /",
        "firefox || rm -rf /",
    ],
)
def test_application_command_injection_rejected(payload: str) -> None:
    with pytest.raises(FileNotFoundError):
        open_application_data(payload)


def test_safe_command_only_accepts_ids() -> None:
    with pytest.raises(CommandPolicyError):
        run_safe_command_data("uname -r; whoami")

