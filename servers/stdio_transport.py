"""Small stdio transport adapter for the official MCP server engine.

The SDK's built-in descriptor-claiming transport is preferred. This adapter uses
asyncio pipe readers and the same MCP message types, avoiding descriptor wrapping
issues observed on some Python 3.14/WSL combinations while keeping MCP framing and
the server implementation entirely in the official SDK.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

import anyio
from mcp import types
from mcp.shared.message import SessionMessage


@asynccontextmanager
async def compatible_stdio_server() -> AsyncIterator[tuple[object, object]]:
    read_sender, read_receiver = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_sender, write_receiver = anyio.create_memory_object_stream[SessionMessage](0)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    async def read_stdin() -> None:
        async with read_sender:
            while line := await reader.readline():
                try:
                    message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
                    await read_sender.send(SessionMessage(message))
                except Exception as exc:
                    await read_sender.send(exc)

    async def write_stdout() -> None:
        async with write_receiver:
            async for session_message in write_receiver:
                payload = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                sys.stdout.write(payload + "\n")
                sys.stdout.flush()

    reader_task = asyncio.create_task(read_stdin())
    writer_task = asyncio.create_task(write_stdout())
    try:
        yield read_receiver, write_sender
    finally:
        await write_sender.aclose()
        reader_task.cancel()
        writer_task.cancel()
        with suppress(asyncio.CancelledError):
            await reader_task
        with suppress(asyncio.CancelledError):
            await writer_task
        transport.close()


async def run_server_stdio(server: object) -> None:
    """Run an MCPServer over the compatibility stdio streams."""
    lowlevel = server._lowlevel_server  # MCPServer's documented high-level wrapper around Server.
    async with compatible_stdio_server() as (read_stream, write_stream):
        await lowlevel.run(read_stream, write_stream, lowlevel.create_initialization_options())

