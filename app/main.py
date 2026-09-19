"""Application entry point."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load a minimal KEY=VALUE dotenv file without executing shell syntax."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.replace("_", "").isalnum() and not key[0].isdigit():
            os.environ.setdefault(key, value.strip().strip('"\''))


def _handoff_to_project_venv() -> None:
    """Make the documented system-Python command work after isolated installation."""
    if importlib.util.find_spec("mcp") is not None:
        return
    project_root = Path(__file__).resolve().parents[1]
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.is_file():
        raise SystemExit("Dependencies are missing. Run ./scripts/install.sh first.")
    completed = subprocess.run(
        [str(venv_python), "-m", "app.main", *sys.argv[1:]],
        shell=False,
        cwd=project_root,
        check=False,
    )
    raise SystemExit(completed.returncode)


async def async_main() -> None:
    from app.cli.interface import confirm_action, run_cli, sudo_password
    from app.core.assistant import Assistant
    from app.core.config import load_settings
    from app.core.tool_manager import ToolManager
    from app.providers.factory import create_provider

    _load_dotenv()
    settings = load_settings()
    provider = create_provider(settings)
    async with ToolManager(settings) as manager:
        assistant = Assistant(manager, provider, confirm=confirm_action, authenticate=sudo_password)
        await run_cli(assistant, manager, settings)


def main() -> None:
    _handoff_to_project_venv()
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
