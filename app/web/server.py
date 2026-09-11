"""Loopback web UI with same-origin requests and one-use action approvals."""
from __future__ import annotations

import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from app.core.assistant import Assistant
from app.core.config import load_settings
from app.core.tool_manager import ToolManager
from app.providers.rule_based import RuleBasedProvider

STATIC = Path(__file__).parent / "static"


def create_app(manager_factory=ToolManager):
    token = secrets.token_urlsafe(32)
    pending = {}

    @asynccontextmanager
    async def lifespan(app):
        settings = load_settings()
        provider = RuleBasedProvider()
        if settings.llm_provider == "ollama":
            from app.providers.ollama import OllamaProvider
            optional = OllamaProvider(base_url=settings.ollama_url, model=settings.ollama_model)
            if optional.available:
                provider = optional
        async with manager_factory(settings) as manager:
            app.state.manager = manager
            app.state.provider = provider
            yield
        pending.clear()

    async def index(request):
        return FileResponse(STATIC / "index.html")

    async def config(request):
        return JSONResponse({"token": token, "tools": request.app.state.manager.available_tools})

    async def command(request: Request):
        if request.headers.get("x-assistant-token") != token:
            return JSONResponse({"error": "Invalid session token. Reload the page."}, status_code=403)
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "JSON required"}, status_code=415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                return JSONResponse({"error": "Request too large"}, status_code=413)
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        now = time.monotonic()
        for key in list(pending):
            if pending[key][0] < now:
                del pending[key]
        approved = None
        if "approval" in data:
            key = data["approval"]
            entry = pending.pop(key, None) if isinstance(key, str) else None
            if entry is None:
                return JSONResponse({"error": "Approval expired or already used."}, status_code=409)
            if data.get("accept") is not True:
                return JSONResponse({"reply": "Action cancelled."})
            _, message, approved = entry
        else:
            message = data.get("message")
            if not isinstance(message, str) or not message.strip() or len(message) > 8000:
                return JSONResponse({"error": "Enter a command of 1–8000 characters."}, status_code=400)
        proposal = None

        async def confirm(description, tool, arguments):
            nonlocal proposal
            if approved == (tool, arguments):
                return True
            proposal = (description, tool, arguments.copy())
            return False

        assistant = Assistant(request.app.state.manager, request.app.state.provider, confirm=confirm)
        reply = await assistant.handle(message)
        if proposal:
            if len(pending) >= 100:
                return JSONResponse({"error": "Too many pending actions."}, status_code=429)
            description, tool, arguments = proposal
            key = secrets.token_urlsafe(24)
            pending[key] = (now + 120, message, (tool, arguments))
            return JSONResponse({"approval": key, "description": description, "arguments": arguments})
        return JSONResponse({"reply": reply})

    app = Starlette(lifespan=lifespan, routes=[Route("/", index), Route("/api/config", config),
        Route("/api/command", command, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static")])

    async def local_only(request, call_next):
        host = request.headers.get("host", "")
        if host not in {"localhost:8765", "127.0.0.1:8765"}:
            return JSONResponse({"error": "Local access only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"http://{host}":
            return JSONResponse({"error": "Cross-origin access denied"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response
    app.add_middleware(BaseHTTPMiddleware, dispatch=local_only)
    return app


def main():
    from app.main import _load_dotenv
    import uvicorn
    _load_dotenv()
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
