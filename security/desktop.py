"""Desktop discovery shared by configuration, routing, and process launchers."""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


def is_wsl() -> bool:
    return bool(os.getenv("WSL_DISTRO_NAME") or "microsoft" in platform.release().lower())


def windows_to_wsl(value: str) -> str:
    """Translate drive-qualified Windows paths; never run user path text as code."""
    match = re.match(r"^([a-zA-Z]):[\\/](.*)$", value)
    if match:
        return f"/mnt/{match[1].lower()}/{match[2].replace(chr(92), '/')}"
    return value


@lru_cache(maxsize=1)
def windows_profile() -> Path | None:
    if not is_wsl():
        return None
    configured = os.getenv("ASSISTANT_WINDOWS_PROFILE", "").strip()
    if configured:
        return Path(windows_to_wsl(configured))
    executable = shutil.which("cmd.exe")
    if not executable and Path("/mnt/c/Windows/System32/cmd.exe").is_file():
        executable = "/mnt/c/Windows/System32/cmd.exe"
    if executable:
        try:
            # Fixed discovery command only: no user text reaches cmd.exe.
            result = subprocess.run(
                [executable, "/d", "/c", "echo", "%USERPROFILE%"],
                capture_output=True, text=True, timeout=3, check=False, shell=False,
            )
            value = result.stdout.strip()
            if result.returncode == 0 and re.match(r"^[A-Za-z]:[\\/]", value):
                return Path(windows_to_wsl(value))
        except (OSError, subprocess.SubprocessError, UnicodeError):
            pass
    return None


def resolve_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found or not is_wsl() or not name.lower().endswith(".exe"):
        return found
    # Fixed candidate directories support WSL installations without Windows PATH import.
    candidates = [Path("/mnt/c/Windows") / name, Path("/mnt/c/Windows/System32") / name]
    suffixes = {
        "msedge.exe": "Microsoft/Edge/Application/msedge.exe",
        "chrome.exe": "Google/Chrome/Application/chrome.exe",
        "Code.exe": "Microsoft VS Code/Code.exe",
    }
    if name in suffixes:
        candidates += [Path(root) / suffixes[name] for root in
                       ("/mnt/c/Program Files", "/mnt/c/Program Files (x86)")]
    profile = windows_profile()
    if profile:
        candidates.append(profile / "AppData/Local/Microsoft/WindowsApps" / name)
        if name in suffixes:
            candidates.extend([profile / "AppData/Local" / suffixes[name],
                               profile / "AppData/Local/Programs" / suffixes[name]])
    return next((str(path) for path in candidates if path.is_file()), None)
