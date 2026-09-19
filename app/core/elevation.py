"""One-operation sudo bridge. Passwords are transient and never logged or stored."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from servers.linux_server.operations import OPERATIONS

READY = 'AMIGO_WORKER_READY'
PASSWORD_PROMPT = 'AMIGO_SUDO_PASSWORD:'


@dataclass
class ElevationRequired(Exception):
    tool: str
    arguments: dict[str, Any]
    reason: str


class AuthenticationRequired(Exception):
    pass


class ElevationError(RuntimeError):
    pass


async def run_elevated(tool: str, arguments: dict, settings: Settings, password: str | None = None) -> dict:
    if tool not in OPERATIONS:
        raise ElevationError('This operation does not support local administrator execution')
    if password is not None and (not isinstance(password, str) or len(password) > 1024 or '\n' in password or '\r' in password):
        raise ElevationError('Invalid sudo password input')
    sudo = shutil.which('sudo')
    if not sudo:
        raise ElevationError('sudo is not installed on this Linux/WSL system')
    worker = Path(__file__).resolve().parents[2] / 'servers/linux_server/elevated_worker.py'
    argv = [sudo, '-S', '-p', PASSWORD_PROMPT, '--', sys.executable, '-I', str(worker)]
    process = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env={**os.environ, 'LC_ALL': 'C'},
        limit=settings.max_file_size * 6 + 65536,
    )
    password_sent = False
    error_text = ''

    async def read_errors():
        nonlocal password_sent, password, error_text
        pending = ''
        while chunk := await process.stderr.read(1024):
            pending += chunk.decode('utf-8', errors='replace')
            while PASSWORD_PROMPT in pending:
                before, pending = pending.split(PASSWORD_PROMPT, 1)
                error_text = (error_text + before)[-4000:]
                if password is None or password_sent:
                    raise AuthenticationRequired('Enter your Linux sudo password.' if not password_sent else 'Sudo did not accept that password. Try again.')
                process.stdin.write((password + '\n').encode('utf-8'))
                await process.stdin.drain()
                password = None
                password_sent = True
            # Keep enough characters to recognize a prompt split across chunks.
            if len(pending) > len(PASSWORD_PROMPT):
                error_text = (error_text + pending[:-len(PASSWORD_PROMPT)])[-4000:]
                pending = pending[-len(PASSWORD_PROMPT):]
        error_text = (error_text + pending)[-4000:]

    async def exchange():
        # Request data is sent ONLY after authentication and worker startup. It can
        # never be misinterpreted as a password on authentication failure.
        first = await process.stdout.readline()
        if first.decode().strip() != READY:
            return None
        environment = {name: os.environ[name] for name in (
            'PATH', 'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS',
            'WSL_INTEROP', 'WSL_DISTRO_NAME', 'ASSISTANT_WINDOWS_PROFILE',
        ) if name in os.environ}
        payload = {'tool': tool, 'arguments': arguments, 'environment': environment,
                   'max_file_size': settings.max_file_size,
                   'command_timeout_seconds': settings.command_timeout_seconds}
        process.stdin.write(json.dumps(payload).encode('utf-8') + b'\n')
        await process.stdin.drain()
        process.stdin.close()
        response = await process.stdout.readline()
        return json.loads(response) if response else None

    tasks = [asyncio.create_task(read_errors()), asyncio.create_task(exchange())]
    try:
        _, result = await asyncio.wait_for(asyncio.gather(*tasks), settings.command_timeout_seconds + 30)
        await process.wait()
        if result is None:
            raise ElevationError(error_text.strip() or 'sudo could not start the administrator operation')
        if result.get('error'):
            raise ElevationError(result['error'])
        return result['data']
    except (asyncio.TimeoutError, json.JSONDecodeError) as exc:
        raise ElevationError('Administrator operation timed out or returned an invalid response. Check its result before retrying.') from exc
    finally:
        password = None
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if process.stdin:
            process.stdin.close()
        if process.returncode is None:
            try:
                process.terminate()
            except (ProcessLookupError, PermissionError):
                pass
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except (ProcessLookupError, PermissionError):
                    pass
