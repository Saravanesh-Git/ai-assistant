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

for package in ("mcp", "psutil", "httpx", "groq", "jsonschema", "starlette"):
    importlib.import_module(package)
print("Dependencies: OK")

from app.core.config import load_settings
from app.core.tool_manager import ToolManager
from app.main import _load_dotenv

_load_dotenv()

async def check_mcp():
    settings = load_settings()
    async with ToolManager(settings) as manager:
        required = {"get_system_info", "get_cpu_usage", "get_memory_usage", "open_browser_search", "search_web"}
        missing = required - set(manager.available_tools)
        if missing:
            raise SystemExit(f"MCP health check failed; missing tools: {', '.join(sorted(missing))}")
        await manager.call("get_system_info", {}, permission_result="healthcheck")
        print(f"MCP servers: OK ({len(manager.available_tools)} tools)")

asyncio.run(check_mcp())

settings = load_settings()
if settings.llm_provider == "groq":
    if not settings.groq_api_key:
        print("Groq: not configured (local command mode remains available)")
    else:
        try:
            from groq import Groq
            with Groq(api_key=settings.groq_api_key, max_retries=0,
                      timeout=settings.groq_timeout_seconds) as client:
                for model in {settings.groq_model, settings.groq_stt_model,
                              settings.groq_tts_model}:
                    if model:
                        client.models.retrieve(model)
            print(f"Groq: configured and reachable ({settings.groq_model})")
        except Exception:
            print("Groq: configured but unavailable; local command mode remains available")
else:
    print(f"Groq: not enabled (LLM_PROVIDER={settings.llm_provider})")

if settings.voice_enabled and settings.groq_api_key:
    print(f"Voice input: configured ({settings.groq_stt_model}, PCM16 mono 16 kHz)")
    if settings.voice_output_enabled and settings.groq_tts_model and settings.groq_tts_voice:
        print(f"Voice output: configured ({settings.groq_tts_model}, {settings.groq_tts_voice})")
    else:
        print("Voice output: disabled or incomplete")
elif settings.voice_enabled:
    print("Voice: enabled but unavailable until GROQ_API_KEY is configured")
else:
    print("Voice: disabled")

endpoint = settings.searxng_url.rstrip("/") + "/search?" + urllib.parse.urlencode({"q": "test", "format": "json"})
try:
    with urllib.request.urlopen(endpoint, timeout=2) as response:
        if response.status == 200:
            print("SearXNG: OK")
        else:
            print(f"SearXNG: unavailable (HTTP {response.status}); local tools remain available")
except (OSError, urllib.error.URLError):
    print("SearXNG: unavailable; browser searches still work. Configure SEARXNG_URL for structured search results")

try:
    with urllib.request.urlopen("http://127.0.0.1:8765/api/config", timeout=2) as response:
        payload = response.read(1024)
        print("Local API and browser UI: OK" if response.status == 200 and b"A.M.I.G.O." in payload
              else "Local API and browser UI: unexpected response")
except (OSError, urllib.error.URLError):
    print("Local API and browser UI: not running (start with .venv/bin/python -m app.web.server)")
PY
