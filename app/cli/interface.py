"""Small dependency-free terminal UI."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from app.core.assistant import Assistant
from app.core.config import Settings
from app.core.tool_manager import ToolManager

BANNER = r"""
╭────────────────────────────────────────╮
│               A.M.I.G.O.               │
│         Personal command center        │
╰────────────────────────────────────────╯
"""


async def sudo_password() -> str:
    import asyncio
    import getpass
    return await asyncio.to_thread(getpass.getpass, "Linux sudo password: ")


async def confirm_action(description: str, tool: str, arguments: dict[str, Any]) -> bool:
    print(f"\nA.M.I.G.O. wants to:\n\n{description}\n\nAllow?")
    answer = input("[Y] Yes  [N] No > ")
    return answer.strip().casefold() in {"y", "yes"}


def _gpu_summary() -> str:
    drm = Path("/dev/dri")
    if any(drm.glob("renderD*")):
        return "Integrated/available"
    return "Not detected"


async def show_system_check(manager: ToolManager, settings: Settings, llm_name: str,
                            fallback_reason: str | None = None) -> None:
    try:
        info = await manager.call("get_system_info", {}, permission_result="startup_read")
        disk_info = await manager.call(
            "get_disk_usage", {"path": "/"}, permission_result="startup_read"
        )
        cpu = info.get("cpu", "Unknown")
        ram = info.get("ram_total", "Unknown")
        os_name = info.get("os", platform.system())
        disk = disk_info.get("free", "Unknown")
    except Exception:
        cpu, ram, os_name, disk = "Unavailable", "Unavailable", platform.platform(), "Unavailable"
    print("System Check")
    print("─" * 36)
    print(f"CPU: {cpu}")
    print(f"RAM: {ram}")
    print(f"GPU: {_gpu_summary()}")
    print(f"OS: {os_name}")
    print(f"Python: {platform.python_version()}")
    print(f"Available disk: {disk}")
    print(f"Mode: {'Lightweight' if settings.lightweight_mode else 'Standard'}")
    print(f"LLM: {llm_name}")
    if fallback_reason:
        print(f"AI note: {fallback_reason}")
    if manager.server_errors:
        print("Note: one or more optional capability servers are unavailable.")
    print("\nA.M.I.G.O. is ready. Type 'help' or 'exit'.\n")


async def run_cli(assistant: Assistant, manager: ToolManager, settings: Settings) -> None:
    print(BANNER)
    llm_label = assistant.provider.name if assistant.provider.available else "Unavailable (rules active)"
    await show_system_check(manager, settings, llm_label,
                            getattr(assistant.provider, "fallback_reason", None))
    while True:
        try:
            user_input = input("You > ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return
        command = user_input.strip().casefold()
        if command in {"exit", "quit", "/exit", "/quit"}:
            print("Goodbye.")
            return
        if command in {"help", "/help"}:
            print(
                "A.M.I.G.O. > Try: show system information; show cpu; check ram; disk space; "
                "show files in Downloads; create a folder called test; open firefox; "
                "search the web for FastAPI."
            )
            continue
        response = await assistant.handle(user_input)
        print(f"\nA.M.I.G.O. > {response}\n")
