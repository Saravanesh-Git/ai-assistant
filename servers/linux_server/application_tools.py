"""Strictly allowlisted process launch operations."""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from security.command_policy import application_command, safe_command


def open_application_data(application: str) -> dict[str, Any]:
    argv = application_command(application)
    executable = shutil.which(argv[0])
    if executable is None:
        raise FileNotFoundError(f"Allowed application is not installed: {application.strip().casefold()}")
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

