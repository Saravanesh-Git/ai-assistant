"""Strictly allowlisted process launch operations."""

from __future__ import annotations

import subprocess
import os
import re
import shlex
import signal
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode
from typing import Any

from security.command_policy import ALLOWED_APPLICATIONS, application_command, safe_command
from security.desktop import is_wsl, resolve_executable, windows_to_wsl


def open_application_data(application: str) -> dict[str, Any]:
    application = application.strip().strip('"\'')
    application = application.casefold() if application.casefold() in ALLOWED_APPLICATIONS else windows_to_wsl(application)
    if is_wsl():
        application = {"calculator": "windows_calculator", "files": "windows_files",
                       "terminal": "windows_terminal", "chrome": "windows_chrome",
                       "edge": "windows_edge", "code": "windows_code",
                       "vscode": "windows_code"}.get(application, application)
    argv = application_command(application) if application in ALLOWED_APPLICATIONS else (application,)
    executable = resolve_executable(argv[0])
    if executable is None:
        hint = " Check Windows installation and WSL interoperability." if argv[0].endswith(".exe") else " Check that it is installed and available on PATH."
        raise FileNotFoundError(f"Application unavailable: {application}.{hint}")
    process = subprocess.Popen(
        [executable, *argv[1:]],
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    return {"application": application.strip().casefold(), "started": True, "pid": process.pid}


def open_browser_search_data(query: str) -> dict[str, Any]:
    """Open an encoded search in the host browser, independently of SearXNG."""
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("Search must contain 1–2000 characters")
    query = query.strip()
    url = "https://www.google.com/search?" + urlencode({"q": query})
    names = ("explorer.exe", "wslview") if is_wsl() else ("xdg-open",)
    for name in names:
        executable = resolve_executable(name)
        if not executable:
            continue
        try:
            process = subprocess.Popen(
                [executable, url], shell=False, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True,
            )
            try:
                code = process.wait(timeout=0.5)
                # Explorer can return 1 after handing off to an existing window.
                if code != 0 and not (name == "explorer.exe" and code == 1):
                    continue
            except subprocess.TimeoutExpired:
                pass
            return {"query": query, "url": url, "opened": True}
        except OSError:
            continue
    return {"query": query, "url": url, "opened": False}


def run_safe_command_data(command_id: str) -> dict[str, Any]:
    argv = safe_command(command_id)
    result = subprocess.run(
        list(argv),
        shell=False,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Safe command failed with exit code {result.returncode}")
    return {"command_id": command_id.strip().casefold(), "output": result.stdout.strip()}


def command_requests_admin(command: str, shell: bool = False) -> bool:
    # Explicit privilege launchers never bypass the app's approval flow, including
    # a sudo word in an explicitly requested shell pipeline.
    if shell:
        return bool(re.search(r'(?<![\w-])(?:sudo|pkexec|doas|su)(?=\s|$)', command))
    parts = shlex.split(command)
    return bool(parts and Path(parts[0]).name in {'sudo', 'su', 'pkexec', 'doas'})


def run_command_data(command: str, cwd: str, shell: bool = False, timeout: int = 120,
                     elevated: bool = False) -> dict[str, Any]:
    if not command.strip() or '\x00' in command:
        raise ValueError('Enter a command without NUL characters')
    if command_requests_admin(command, shell) and not elevated:
        return {'elevation_required': True, 'reason': 'This command explicitly requests administrator privileges.'}
    # Shell syntax runs only when the user explicitly asks for "run shell ...".
    argv = ['/bin/bash', '-c', command] if shell else shlex.split(command)
    if not argv:
        raise ValueError('Enter a command')
    if not shell:
        argv[0] = windows_to_wsl(argv[0])
    started = time.monotonic()
    stopped = None
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(argv, cwd=cwd, shell=False, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr, start_new_session=True)
        while process.poll() is None:
            if time.monotonic() - started > timeout:
                stopped = f'Command stopped after {timeout} seconds'
            if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > 1024 * 1024:
                stopped = 'Command stopped after exceeding the 1 MB output limit'
            if stopped:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                except ProcessLookupError:
                    process.wait()
                break
            time.sleep(.03)
        stdout.seek(0)
        stderr.seek(0)
        output = stdout.read(65536).decode('utf-8', errors='replace')
        error = stderr.read(65536).decode('utf-8', errors='replace')
    result = {'command': command, 'output': output, 'stderr': error,
              'returncode': process.returncode, 'stopped': stopped}
    # A failed command can have partial effects. An elevated retry is always
    # presented as a new, explicit approval with that information.
    if process.returncode and not elevated and re.search(r'permission denied|operation not permitted|must be (?:run as )?root|requires? (?:root|superuser)', error, re.I):
        result.update(elevation_required=True,
                      reason='The command reported insufficient permissions. It may have partially completed; approval will rerun this exact command as administrator.')
    return result


def open_path_data(path: str) -> dict[str, Any]:
    path = windows_to_wsl(path)
    Path(path).stat()
    if is_wsl():
        executable = resolve_executable('explorer.exe')
        # wslpath handles mounted drives and Linux paths (\\wsl.localhost\\...).
        conversion = subprocess.run(['wslpath', '-w', path], capture_output=True, text=True,
                                    timeout=5, check=True, shell=False)
        argument = conversion.stdout.strip()
    else:
        executable = resolve_executable('xdg-open')
        argument = path
    if not executable:
        raise FileNotFoundError('No desktop file opener was found')
    process = subprocess.Popen([executable, argument], shell=False, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    return {'path': path, 'opened': True, 'pid': process.pid}
