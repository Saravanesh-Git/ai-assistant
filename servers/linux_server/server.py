"""Local stdio tools with machine-wide paths and OS-level authorization."""
from __future__ import annotations

from functools import partial
from typing import Any
import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.core.config import load_settings
from servers.linux_server.operations import execute_operation
from servers.stdio_transport import run_server_stdio

settings = load_settings()
mcp = MCPServer('local-assistant-linux', instructions='Linux and Windows/WSL desktop operations. OS permissions apply; elevation is handled by the assistant core.')


async def _call(tool: str, **arguments) -> dict[str, Any]:
    try:
        return await anyio.to_thread.run_sync(partial(execute_operation, tool, arguments, settings))
    except (OSError, ValueError, RuntimeError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_system_info() -> dict[str, Any]:
    """Operating system and hardware information."""
    return await _call('get_system_info')


@mcp.tool()
async def get_cpu_usage() -> dict[str, Any]:
    """Current CPU utilization."""
    return await _call('get_cpu_usage')


@mcp.tool()
async def get_memory_usage() -> dict[str, Any]:
    """Physical memory utilization."""
    return await _call('get_memory_usage')


@mcp.tool()
async def get_disk_usage(path: str = '/') -> dict[str, Any]:
    """Disk utilization for any existing directory."""
    return await _call('get_disk_usage', path=path)


@mcp.tool()
async def get_battery_status() -> dict[str, Any]:
    """Battery status where available."""
    return await _call('get_battery_status')


@mcp.tool()
async def list_directory(path: str, offset: int = 0, limit: int = 200) -> dict[str, Any]:
    """List any directory with pagination and per-entry errors."""
    return await _call('list_directory', path=path, offset=offset, limit=limit)


@mcp.tool()
async def read_text_file(path: str) -> dict[str, Any]:
    """Read a UTF-8 file at any path, regardless of extension."""
    return await _call('read_text_file', path=path)


@mcp.tool()
async def create_directory(path: str) -> dict[str, Any]:
    """Create a directory and missing parents at any path."""
    return await _call('create_directory', path=path)


@mcp.tool()
async def create_text_file(path: str, content: str = '') -> dict[str, Any]:
    """Create a file of any extension, including missing parent directories."""
    return await _call('create_text_file', path=path, content=content)


@mcp.tool()
async def write_text_file(path: str, content: str, append: bool = False) -> dict[str, Any]:
    """Explicitly replace or append UTF-8 text in a file."""
    return await _call('write_text_file', path=path, content=content, append=append)


@mcp.tool()
async def move_path(source: str, destination: str) -> dict[str, Any]:
    """Move or rename a path without replacing an existing destination."""
    return await _call('move_path', source=source, destination=destination)


@mcp.tool()
async def copy_path(source: str, destination: str) -> dict[str, Any]:
    """Copy a file or directory, including between Linux and Windows drives."""
    return await _call('copy_path', source=source, destination=destination)


@mcp.tool()
async def find_files(name: str, path: str, limit: int = 100) -> dict[str, Any]:
    """Find matching filenames recursively; report skipped directories and truncation."""
    return await _call('find_files', name=name, path=path, limit=limit)


@mcp.tool()
async def open_application(application: str) -> dict[str, Any]:
    """Launch a known alias, any installed executable, or executable path."""
    return await _call('open_application', application=application)


@mcp.tool()
async def open_path(path: str) -> dict[str, Any]:
    """Open a file or directory in its desktop application."""
    return await _call('open_path', path=path)


@mcp.tool()
async def open_browser_search(query: str) -> dict[str, Any]:
    """Open a search in the desktop browser."""
    return await _call('open_browser_search', query=query)


@mcp.tool()
async def run_safe_command(command_id: str) -> dict[str, Any]:
    """Compatibility shortcut for predefined system queries."""
    return await _call('run_safe_command', command_id=command_id)


@mcp.tool()
async def run_command(command: str, cwd: str, shell: bool = False) -> dict[str, Any]:
    """Execute a direct user command. Shell syntax requires explicit shell=true."""
    return await _call('run_command', command=command, cwd=cwd, shell=shell)


def main() -> None:
    anyio.run(run_server_stdio, mcp)


if __name__ == '__main__':
    main()
