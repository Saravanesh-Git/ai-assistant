"""MCP discovery and invocation across independent local stdio servers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.core.config import Settings


class ToolUnavailableError(RuntimeError):
    pass


class ToolInvocationError(RuntimeError):
    pass


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "tool": getattr(record, "tool", None),
            "status": getattr(record, "status", None),
            "execution_time": getattr(record, "execution_time", None),
            "permission_result": getattr(record, "permission_result", None),
            "error_type": getattr(record, "error_type", None),
        }
        return json.dumps(payload, separators=(",", ":"))


def configure_audit_logger(settings: Settings) -> logging.Logger:
    logger = logging.getLogger("local_assistant.audit")
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


class ToolManager:
    SERVER_MODULES = (
        "servers.linux_server.server",
        "servers.web_server.server",
    )

    def __init__(self, settings: Settings, *, project_root: Path | None = None) -> None:
        self.settings = settings
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self._stack = AsyncExitStack()
        self._clients: list[Client] = []
        self._tool_clients: dict[str, Client] = {}
        self._tool_definitions: dict[str, dict[str, Any]] = {}
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_tools)
        self.logger = configure_audit_logger(settings)
        self.server_errors: dict[str, str] = {}

    async def __aenter__(self) -> "ToolManager":
        server_errlog = self._stack.enter_context(open(os.devnull, "w", encoding="utf-8"))
        safe_env = {
            "SEARXNG_URL": self.settings.searxng_url,
            "MAX_FILE_SIZE": str(self.settings.max_file_size),
            "COMMAND_TIMEOUT_SECONDS": str(self.settings.command_timeout_seconds),
            "MAX_WEB_RESPONSE_SIZE": str(self.settings.max_web_response_size),
            "WEB_TIMEOUT_SECONDS": str(self.settings.web_timeout_seconds),
            "PYTHONPATH": str(self.project_root),
        }
        # MCP's default environment omits desktop/session variables needed for WSL
        # interop and Linux desktop launchers. Forward only these known settings.
        for name in ("PATH", "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR",
                     "DBUS_SESSION_BUS_ADDRESS", "WSL_INTEROP", "WSL_DISTRO_NAME",
                     "ASSISTANT_WINDOWS_PROFILE"):
            if name in os.environ:
                safe_env[name] = os.environ[name]
        for module in self.SERVER_MODULES:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", module],
                cwd=self.project_root,
                env=safe_env,
            )
            try:
                client = await self._stack.enter_async_context(
                    Client(
                        stdio_client(params, errlog=server_errlog),
                        read_timeout_seconds=float(max(self.settings.web_timeout_seconds, self.settings.command_timeout_seconds) + 10),
                    )
                )
                discovered = await client.list_tools()
                self._clients.append(client)
                for tool in discovered.tools:
                    if tool.name in self._tool_clients:
                        raise RuntimeError(f"Duplicate MCP tool name: {tool.name}")
                    self._tool_clients[tool.name] = client
                    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
                    self._tool_definitions[tool.name] = {
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": schema or {"type": "object", "properties": {}},
                    }
            except Exception as exc:
                self.server_errors[module] = type(exc).__name__
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self._stack.aclose()

    @property
    def available_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._tool_clients))

    @property
    def tool_definitions(self) -> tuple[dict[str, Any], ...]:
        """Provider-neutral MCP descriptions and JSON argument schemas."""
        return tuple(self._tool_definitions[name].copy() for name in sorted(self._tool_definitions))

    def validate_call(self, tool: str, arguments: dict[str, Any]) -> None:
        definition = self._tool_definitions.get(tool)
        if definition is None:
            raise ToolUnavailableError(f"Capability unavailable: {tool}")
        if not isinstance(arguments, dict):
            raise ToolInvocationError("Tool arguments must be an object")
        try:
            Draft202012Validator(definition["input_schema"]).validate(arguments)
        except ValidationError as exc:
            path = ".".join(str(item) for item in exc.absolute_path)
            location = f" at {path}" if path else ""
            raise ToolInvocationError(f"Invalid arguments for {tool}{location}: {exc.message}") from exc

    async def call(self, tool: str, arguments: dict[str, Any], *, permission_result: str) -> Any:
        client = self._tool_clients.get(tool)
        if client is None:
            raise ToolUnavailableError(f"Capability unavailable: {tool}")
        self.validate_call(tool, arguments)
        started = time.monotonic()
        status = "failure"
        error_type: str | None = None
        try:
            async with self._semaphore:
                result = await client.call_tool(tool, arguments)
            if result.is_error:
                message = "Tool execution failed"
                for content in result.content:
                    text = getattr(content, "text", None)
                    if text:
                        message = text
                        break
                prefix = f"Error executing tool {tool}: "
                while message.startswith(prefix):
                    message = message[len(prefix) :]
                raise ToolInvocationError(message)
            status = "success"
            if result.structured_content is not None:
                return result.structured_content
            for content in result.content:
                text = getattr(content, "text", None)
                if text is not None:
                    return text
            return None
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            self.logger.info(
                "tool_call",
                extra={
                    "tool": tool,
                    "status": status,
                    "execution_time": round(time.monotonic() - started, 4),
                    "permission_result": permission_result,
                    "error_type": error_type,
                },
            )
