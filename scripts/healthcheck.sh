#!/usr/bin/env bash
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN=${PYTHON_BIN:-python3}
fi

cd "$PROJECT_ROOT"
"$PYTHON_BIN" - <<'PY'
import asyncio
import importlib
import urllib.error
import urllib.parse
import urllib.request

for package in ("mcp", "psutil", "httpx"):
    importlib.import_module(package)
print("Dependencies: OK")

from app.core.config import load_settings
from app.core.tool_manager import ToolManager

async def check_mcp():
    settings = load_settings()
    async with ToolManager(settings) as manager:
        required = {"get_system_info", "get_cpu_usage", "get_memory_usage", "search_web"}
        missing = required - set(manager.available_tools)
        if missing:
            raise SystemExit(f"MCP health check failed; missing tools: {', '.join(sorted(missing))}")
        await manager.call("get_system_info", {}, permission_result="healthcheck")
        print(f"MCP servers: OK ({len(manager.available_tools)} tools)")

asyncio.run(check_mcp())

settings = load_settings()
endpoint = settings.searxng_url.rstrip("/") + "/search?" + urllib.parse.urlencode({"q": "test", "format": "json"})
try:
    with urllib.request.urlopen(endpoint, timeout=2) as response:
        if response.status == 200:
            print("SearXNG: OK")
        else:
            print(f"SearXNG: unavailable (HTTP {response.status}); local tools remain available")
except (OSError, urllib.error.URLError):
    print("SearXNG: unavailable; configure SEARXNG_URL to enable web search")
PY

