"""Assistant orchestration: route, authorize, invoke, and format."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.llm import LLMProvider, Message
from app.core.permissions import PermissionManager
from app.core.router import IntentRouter
from app.core.tool_manager import ToolInvocationError, ToolManager, ToolUnavailableError

ConfirmCallback = Callable[[str, str, dict[str, Any]], Awaitable[bool]]


class Assistant:
    def __init__(
        self,
        tool_manager: ToolManager,
        provider: LLMProvider,
        *,
        router: IntentRouter | None = None,
        permissions: PermissionManager | None = None,
        confirm: ConfirmCallback | None = None,
    ) -> None:
        self.tools = tool_manager
        self.provider = provider
        configured_paths = getattr(getattr(tool_manager, "settings", None), "allowed_paths", ())
        self.router = router or IntentRouter(allowed_paths=configured_paths)
        self.permissions = permissions or PermissionManager()
        self.confirm = confirm

    async def handle(self, user_input: str) -> str:
        route = self.router.route(user_input)
        if route.intent == "empty":
            return "Please enter a request."
        if route.intent == "unsafe_path":
            return "That path is not allowed. Use one of your configured user folders."
        if route.intent == "unsupported_application":
            return "That application is not allowlisted. Supported apps: firefox, chrome, code, terminal, files, calculator."
        if route.tool is None:
            try:
                return await self.provider.generate([Message("user", user_input)])
            except Exception:
                return "I couldn't classify that request, and the optional LLM is unavailable."

        decision = self.permissions.check_permission(route.tool, route.arguments)
        if not decision.allowed:
            return "That capability is denied by the permission policy."
        permission_result = "read_allowed"
        if decision.requires_confirmation:
            if self.confirm is None or not await self.confirm(decision.description, route.tool, route.arguments):
                return "Action cancelled."
            permission_result = "user_allowed"

        try:
            data = await self.tools.call(
                route.tool,
                route.arguments,
                permission_result=permission_result,
            )
        except ToolUnavailableError:
            if route.tool == "search_web":
                return "Web search is unavailable. The local assistant is still functional."
            return f"The {route.tool.replace('_', ' ')} capability is unavailable."
        except (ToolInvocationError, TimeoutError) as exc:
            if route.tool == "search_web":
                return "Web search is unavailable. Check SEARXNG_URL; local tools still work."
            if route.tool == "list_directory":
                return f"I couldn't list that directory: {exc}"
            return f"I couldn't complete that action: {exc}"
        except Exception as exc:
            return f"I couldn't complete that action ({type(exc).__name__})."
        return self._format(route.tool, data)

    @staticmethod
    def _format(tool: str, data: Any) -> str:
        if not isinstance(data, dict):
            return str(data)
        if tool == "get_system_info":
            return (
                f"{data['os']} on {data['hostname']}\n"
                f"CPU: {data['cpu']} ({data['cpu_cores']} logical cores)\n"
                f"RAM: {data['ram_total']} | Kernel: {data['kernel']} | Uptime: {data['uptime']}"
            )
        if tool == "get_cpu_usage":
            loads = ", ".join(str(item) for item in data.get("load_average", [])) or "unavailable"
            return f"CPU usage is {data['cpu_percent']:.1f}% across {data['cores']} logical cores. Load average: {loads}."
        if tool == "get_memory_usage":
            return f"Memory usage is {data['percent']:.1f}%: {data['used']} used of {data['total']} ({data['available']} available)."
        if tool == "get_disk_usage":
            return f"Disk usage for {data['path']} is {data['percent']:.1f}%: {data['used']} used, {data['free']} free of {data['total']}."
        if tool == "get_battery_status":
            if not data.get("available"):
                return "No battery was detected."
            state = "plugged in" if data.get("plugged") else "on battery"
            return f"Battery is at {data['percent']:.1f}% ({state})."
        if tool == "list_directory":
            entries = data.get("entries", [])
            if not entries:
                return f"{data['path']} is empty."
            lines = [f"Contents of {data['path']}:"]
            lines.extend(f"  {'[dir]' if item['type'] == 'directory' else '[file]'} {item['name']}" for item in entries)
            return "\n".join(lines)
        if tool == "create_directory":
            verb = "Created" if data.get("created") else "Already exists"
            return f"{verb}: {data['path']}"
        if tool == "open_application":
            return f"Opened {data['application']}."
        if tool == "run_safe_command":
            return str(data.get("output", ""))
        if tool == "search_web":
            if data.get("unavailable"):
                return "Web search is unavailable. Check SEARXNG_URL; local tools still work."
            results = data.get("results", [])
            if not results:
                return f"No results found for “{data.get('query', '')}”."
            lines = [f"Search results for “{data.get('query', '')}”:" ]
            for index, item in enumerate(results, 1):
                lines.append(f"\n{index}. {item['title']}\n   {item['snippet']}\n   {item['url']}")
            return "\n".join(lines)
        if tool == "fetch_webpage":
            return str(data.get("text", ""))
        return str(data)
