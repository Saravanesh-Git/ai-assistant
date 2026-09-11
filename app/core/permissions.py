"""Central permission classification and confirmation decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class PermissionLevel(IntEnum):
    READ = 1
    WRITE = 2
    EXECUTE = 3


TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    "get_system_info": PermissionLevel.READ,
    "get_cpu_usage": PermissionLevel.READ,
    "get_memory_usage": PermissionLevel.READ,
    "get_disk_usage": PermissionLevel.READ,
    "get_battery_status": PermissionLevel.READ,
    "list_directory": PermissionLevel.READ,
    "read_text_file": PermissionLevel.READ,
    "search_web": PermissionLevel.READ,
    "fetch_webpage": PermissionLevel.READ,
    "run_safe_command": PermissionLevel.READ,
    "create_directory": PermissionLevel.WRITE,
    "create_text_file": PermissionLevel.WRITE,
    "move_path": PermissionLevel.WRITE,
    "open_application": PermissionLevel.EXECUTE,
}


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    level: PermissionLevel | None
    requires_confirmation: bool
    description: str


class PermissionManager:
    def check_permission(self, tool: str, arguments: dict[str, Any]) -> PermissionDecision:
        level = TOOL_PERMISSIONS.get(tool)
        if level is None:
            return PermissionDecision(False, None, False, "Unknown tools are denied")
        description = self.describe(tool, arguments)
        return PermissionDecision(True, level, level >= PermissionLevel.WRITE, description)

    @staticmethod
    def describe(tool: str, arguments: dict[str, Any]) -> str:
        if tool == "open_application":
            return f"Open {arguments.get('application', 'an application')}"
        if tool == "create_text_file":
            return f"Create text file {arguments.get('path', '')}"
        if tool == "move_path":
            return f"Move {arguments.get('source', '')} to {arguments.get('destination', '')}"
        if tool == "create_directory":
            return f"Create folder {arguments.get('path', '')}"
        return tool.replace("_", " ").capitalize()

