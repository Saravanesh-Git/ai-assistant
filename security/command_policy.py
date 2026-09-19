"""Closed allowlists for process execution."""

from __future__ import annotations

import re


ALLOWED_APPLICATIONS: dict[str, tuple[str, ...]] = {
    "firefox": ("firefox",),
    "chrome": ("google-chrome",),
    "code": ("code",),
    "vscode": ("code",),
    "terminal": ("gnome-terminal",),
    "files": ("nautilus",),
    "calculator": ("gnome-calculator",),
}

# Explicit Windows targets work through WSL interoperability; never accept raw argv.
ALLOWED_APPLICATIONS.update({
    "windows_notepad": ("notepad.exe",),
    "windows_calculator": ("calc.exe",),
    "windows_files": ("explorer.exe",),
    "windows_terminal": ("wt.exe",),
    "windows_edge": ("msedge.exe",),
    "windows_chrome": ("chrome.exe",),
    "windows_code": ("Code.exe",),
    "notepad": ("notepad.exe",),
    "edge": ("msedge.exe",),
})

SAFE_COMMANDS: dict[str, tuple[str, ...]] = {
    "get_ip_address": ("hostname", "-I"),
    "get_kernel_version": ("uname", "-r"),
    "get_logged_in_user": ("id", "-un"),
    "get_current_directory": ("pwd",),
    "get_date": ("date", "--iso-8601=seconds"),
}

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class CommandPolicyError(ValueError):
    """Raised when an execution request is not explicitly allowlisted."""


def application_command(application: str) -> tuple[str, ...]:
    key = application.strip().casefold()
    if not _IDENTIFIER.fullmatch(key) or key not in ALLOWED_APPLICATIONS:
        raise CommandPolicyError("Application is not in the allowlist")
    return ALLOWED_APPLICATIONS[key]


def safe_command(command_id: str) -> tuple[str, ...]:
    key = command_id.strip().casefold()
    if not _IDENTIFIER.fullmatch(key) or key not in SAFE_COMMANDS:
        raise CommandPolicyError("Command ID is not in the allowlist")
    return SAFE_COMMANDS[key]
