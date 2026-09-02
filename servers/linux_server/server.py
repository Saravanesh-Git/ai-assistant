"""Local stdio MCP server exposing safe Linux capabilities."""

from __future__ import annotations

from typing import Any

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.core.config import load_settings
from security.path_policy import PathPolicy
from servers.linux_server.application_tools import open_application_data, run_safe_command_data
from servers.linux_server.file_tools import (
    create_directory_data,
    list_directory_data,
    read_text_file_data,
)
from servers.linux_server.system_tools import (
    get_battery_status_data,
    get_cpu_usage_data,
    get_disk_usage_data,
    get_memory_usage_data,
    get_system_info_data,
)
from servers.stdio_transport import run_server_stdio

settings = load_settings()
path_policy = PathPolicy(settings.allowed_paths)
mcp = MCPServer(
    "local-assistant-linux",
    instructions="Safe, allowlisted Linux system, file, and application tools.",
)


@mcp.tool()
async def get_system_info() -> dict[str, Any]:
    """Return basic operating system and hardware information."""
    return get_system_info_data()


@mcp.tool()
async def get_cpu_usage() -> dict[str, Any]:
    """Return current CPU utilization and load averages."""
    return get_cpu_usage_data()


@mcp.tool()
async def get_memory_usage() -> dict[str, Any]:
    """Return current physical memory utilization."""
    return get_memory_usage_data()


@mcp.tool()
async def get_disk_usage(path: str = "/") -> dict[str, Any]:
    """Return disk utilization for an existing directory."""
    try:
        return get_disk_usage_data(path)
    except (OSError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_battery_status() -> dict[str, Any]:
    """Return battery status, or available=false on desktop systems."""
    return get_battery_status_data()


@mcp.tool()
async def list_directory(path: str) -> dict[str, Any]:
    """List one configured user directory without reading file contents."""
    try:
        return list_directory_data(path, path_policy)
    except (OSError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def read_text_file(path: str) -> dict[str, Any]:
    """Read a small UTF-8 text file inside a configured user directory."""
    try:
        return read_text_file_data(path, path_policy, settings.max_file_size)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def create_directory(path: str) -> dict[str, Any]:
    """Create a directory only inside a configured user directory."""
    try:
        return create_directory_data(path, path_policy)
    except (OSError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def open_application(application: str) -> dict[str, Any]:
    """Launch an installed desktop application from a closed allowlist."""
    try:
        return open_application_data(application)
    except (OSError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def run_safe_command(command_id: str) -> dict[str, Any]:
    """Run one predefined read-only command by ID; raw commands are never accepted."""
    try:
        return run_safe_command_data(command_id)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


def main() -> None:
    anyio.run(run_server_stdio, mcp)


if __name__ == "__main__":
    main()
