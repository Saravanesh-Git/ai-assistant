"""Assistant orchestration: route, authorize, invoke, and format."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import Settings
from app.core.elevation import (
    AuthenticationRequired,
    ElevationError,
    ElevationRequired,
    run_elevated,
)
from app.core.llm import LLMProvider, Message, ToolResult
from app.core.permissions import PermissionManager
from app.core.router import IntentRouter
from app.core.tool_manager import ToolInvocationError, ToolManager, ToolUnavailableError

ConfirmCallback = Callable[[str, str, dict[str, Any]], Awaitable[bool]]

MODEL_DENIED_TOOLS = frozenset({"run_command", "run_safe_command"})
_MULTI_ACTION = re.compile(
    r"\b(?:and then|then|after that|also|and\s+(?:open|tell|show|check|get|search|create|list|read|find|copy|move|run))\b",
    re.I,
)
_DIRECT_COMMAND = re.compile(r"^(?:please\s+)?(?:run|execute|sudo)\b", re.I)
_SENSITIVE_FILE_AI = re.compile(r"\b(?:read|summari[sz]e|analy[sz]e|explain|review)\b.*\bfile\b", re.I)


class Assistant:
    def __init__(
        self,
        tool_manager: ToolManager,
        provider: LLMProvider,
        *,
        router: IntentRouter | None = None,
        permissions: PermissionManager | None = None,
        confirm: ConfirmCallback | None = None,
        authenticate: Callable[[], Awaitable[str]] | None = None,
        history_limit: int | None = None,
        max_tool_steps: int | None = None,
    ) -> None:
        self.tools = tool_manager
        self.provider = provider
        self.router = router or IntentRouter()
        self.permissions = permissions or PermissionManager()
        self.confirm = confirm
        self.authenticate = authenticate
        settings = getattr(tool_manager, "settings", None)
        self.history = deque(maxlen=history_limit or getattr(settings, "history_limit", 12))
        self.max_tool_steps = max_tool_steps or getattr(settings, "max_agent_tool_steps", 6)

    async def handle(self, user_input: str) -> str:
        route = self.router.route(user_input)
        if route.intent == "empty":
            return "I'm here. Enter a request."
        if route.intent == "unsafe_path":
            return "I couldn't understand that path. Use an absolute Linux path, a Windows drive path, or a path relative to your home."
        if self.provider.name != "rule_based" and not self._use_fast_path(user_input, route):
            try:
                reply = await self._handle_with_model(user_input)
                self._remember(user_input, reply)
                return reply
            except ElevationRequired:
                raise
            except TimeoutError:
                return "I couldn't reach Gemini before the request timed out. Your local system commands are still available."
            except Exception:
                return "I couldn't reach Gemini right now. Your local system commands are still available."
        if route.tool is None:
            try:
                reply = await self.provider.generate([*self.history, Message("user", user_input)])
                self._remember(user_input, reply)
                return reply
            except Exception:
                return "I couldn't classify that request, and the optional AI provider is unavailable."
        decision = self.permissions.check_permission(route.tool, route.arguments)
        if not decision.allowed:
            return "That capability is not registered."
        try:
            if route.administrator:
                raise ElevationRequired(route.tool, route.arguments, "You requested administrator execution.")
            data = await self.tools.call(route.tool, route.arguments, permission_result="direct_request")
            if isinstance(data, dict) and data.get("elevation_required"):
                raise ElevationRequired(route.tool, route.arguments, data.get("reason", "OS permission denied"))
            reply = self._format(route.tool, data)
            self._remember(user_input, reply)
            return reply
        except ElevationRequired as proposal:
            if self.confirm is None:
                raise
            description = f"Administrator access required: {proposal.reason}\n{proposal.tool}: {proposal.arguments}"
            if not await self.confirm(description, proposal.tool, proposal.arguments):
                return "Administrator action cancelled."
            try:
                return await self.execute_approved(proposal.tool, proposal.arguments)
            except AuthenticationRequired:
                if self.authenticate is None:
                    return "sudo requires authentication. Use the browser interface or a terminal with password input."
                password = await self.authenticate()
                try:
                    return await self.execute_approved(proposal.tool, proposal.arguments, password)
                except AuthenticationRequired:
                    return "sudo did not accept the password. Request the action again to retry."
                finally:
                    password = None
        except ToolUnavailableError:
            return f"The {route.tool.replace('_', ' ')} capability is unavailable."
        except (ToolInvocationError, OSError, ValueError, TimeoutError) as exc:
            return f"I couldn't complete that action: {exc}"
        except Exception as exc:
            return f"I couldn't complete that action ({type(exc).__name__})."

    def _use_fast_path(self, user_input: str, route: Any) -> bool:
        if route.tool is None or _MULTI_ACTION.search(user_input):
            return False
        # Shell execution is available only when directly and deterministically requested.
        if route.tool == "run_command":
            return bool(_DIRECT_COMMAND.match(user_input.strip()))
        # Exact router matches stay low latency; natural questions go to Gemini.
        simple = len(user_input.split()) <= 7
        return simple and route.confidence >= 0.9

    def _remember(self, user_input: str, reply: str) -> None:
        self.history.append(Message("user", user_input))
        self.history.append(Message("assistant", reply))

    def _model_tools(self, user_input: str) -> tuple[dict[str, Any], ...]:
        definitions = getattr(self.tools, "tool_definitions", ())
        allowed = []
        for definition in definitions:
            name = definition.get("name")
            if name in MODEL_DENIED_TOOLS:
                continue
            if name == "read_text_file" and not _SENSITIVE_FILE_AI.search(user_input):
                continue
            if self.permissions.check_permission(str(name), {}).allowed:
                allowed.append(definition)
        return tuple(allowed)

    async def _handle_with_model(self, user_input: str) -> str:
        messages = [*self.history, Message("user", user_input)]
        tools = self._model_tools(user_input)
        response = await self.provider.generate_turn(messages, tools)
        steps = 0
        while response.tool_calls:
            results = []
            for call in response.tool_calls:
                steps += 1
                if steps > self.max_tool_steps:
                    return f"I stopped after {self.max_tool_steps} tool calls to avoid an agent loop."
                definition = next((item for item in tools if item.get("name") == call.name), None)
                decision = self.permissions.check_permission(call.name, call.arguments)
                if definition is None or not decision.allowed:
                    results.append(ToolResult(call.name, call_id=call.call_id,
                                              error="Unknown or unavailable tool"))
                    continue
                validator = getattr(self.tools, "validate_call", None)
                try:
                    if validator:
                        validator(call.name, call.arguments)
                    data = await self.tools.call(
                        call.name, call.arguments, permission_result="model_requested"
                    )
                    if isinstance(data, dict) and data.get("elevation_required"):
                        raise ElevationRequired(
                            call.name, call.arguments,
                            data.get("reason", "OS permission denied"),
                        )
                    results.append(ToolResult(call.name, result=data, call_id=call.call_id))
                except ElevationRequired:
                    raise
                except (ToolUnavailableError, ToolInvocationError, OSError, ValueError, TimeoutError) as exc:
                    results.append(ToolResult(call.name, call_id=call.call_id,
                                              error=f"{type(exc).__name__}: {exc}"))
            response = await self.provider.generate_turn(
                messages, tools, continuation=response.continuation, tool_results=results
            )
        return response.text or "The request completed, but Gemini returned no text response."

    async def execute_approved(self, tool: str, arguments: dict, password: str | None = None) -> str:
        """Called only with an exact, server-held approval (or CLI confirmation)."""
        settings = getattr(self.tools, "settings", None) or Settings()
        try:
            data = await run_elevated(tool, arguments, settings, password)
            logger = getattr(self.tools, "logger", None)
            if logger:
                logger.info("administrator_action", extra={"tool": tool, "status": "success", "permission_result": "administrator_approved"})
            return self._format(tool, data)
        except ElevationError as exc:
            return f"Administrator action failed: {exc}"

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
            lines.extend(f"  [{item['type']}] {item['name']}" + (f" — {item['error']}" if item.get('error') else '') for item in entries)
            if data.get('next_offset') is not None:
                lines.append(f"More entries: show files in \"{data['path']}\" page {data['next_offset'] // 200 + 1}")
            return "\n".join(lines)
        if tool == "create_directory":
            verb = "Created" if data.get("created") else "Already exists"
            return f"{verb}: {data['path']}"
        if tool == "create_text_file":
            return f"Created file: {data['path']}"
        if tool == "write_text_file":
            return f"{'Appended to' if data.get('append') else 'Wrote'}: {data['path']}"
        if tool == "copy_path":
            return f"Copied {data['source']} to {data['destination']}"
        if tool == "find_files":
            lines = [f"Matches under {data['path']}:", *data['matches']]
            if not data['matches']:
                lines.append("No matching names found in the scanned directories.")
            if data.get('skipped'):
                lines.append(f"Skipped {data['skipped']} unreadable directories. Add 'as administrator' to search them with approval.")
            if data.get('truncated'):
                lines.append("Search reached its time/result limit. Search a narrower directory to continue.")
            return "\n".join(lines)
        if tool == "open_path":
            return f"Opened: {data['path']}"
        if tool == "run_command":
            result = (data.get('output', '') + data.get('stderr', '')).strip()
            result += f"\nExit code: {data.get('returncode', 'unknown')}"
            if data.get('stopped'):
                result += "\n" + data['stopped']
            return result.strip()
        if tool == "move_path":
            if data.get('source_retained'):
                return f"Copied to {data['destination']}, but could not fully remove the source at {data['source']}: {data['cleanup_error']}. Check both paths before requesting removal."
            return f"Moved {data['source']} to {data['destination']}"
        if tool == "open_application":
            return f"Launched {data['application'].replace('_', ' ')}."
        if tool == "open_browser_search":
            if data.get("opened"):
                return f"Opened your browser to search for “{data['query']}”."
            return f"I couldn't launch a browser on this desktop. Open your search here:\n{data['url']}"
        if tool == "read_text_file":
            return f"{data['path']}\n{data['content']}"
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
