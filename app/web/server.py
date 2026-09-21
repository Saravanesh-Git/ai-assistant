"""A.M.I.G.O. loopback UI with direct commands and optional action approvals."""
from __future__ import annotations

import asyncio
import json
import platform
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.core.assistant import Assistant
from app.core.config import load_settings
from app.core.elevation import AuthenticationRequired, ElevationRequired
from app.core.tool_manager import ToolManager
from app.providers.factory import create_provider
from app.voice import GeminiLiveSession, VoiceUnavailableError
from app.voice.protocol import error_event, status_event
from security.desktop import is_wsl, resolve_executable

STATIC = Path(__file__).parent / "static"


def create_app(manager_factory=ToolManager, *, clock=time.monotonic, voice_factory=GeminiLiveSession):
    token = secrets.token_urlsafe(32)
    pending = {}

    @asynccontextmanager
    async def lifespan(app):
        settings = load_settings()
        provider = await asyncio.to_thread(create_provider, settings)
        async with manager_factory(settings) as manager:
            app.state.manager = manager
            app.state.provider = provider
            app.state.assistant = Assistant(manager, provider)
            app.state.command_lock = asyncio.Lock()
            app.state.desktop = {
                "platform": "Windows + WSL" if is_wsl() else platform.system(),
                "windows_available": bool(is_wsl() and resolve_executable("explorer.exe")),
            }
            yield
        pending.clear()

    async def index(request):
        return FileResponse(STATIC / "index.html")

    async def config(request):
        settings = request.app.state.manager.settings
        return JSONResponse({"token": token, "tools": request.app.state.manager.available_tools,
                             "name": "A.M.I.G.O.", "wake_phrase": "Hey Amigo",
                             "provider": request.app.state.provider.name,
                             "provider_fallback": getattr(request.app.state.provider, "fallback_reason", None),
                             "requested_provider": settings.llm_provider,
                             "voice_enabled": settings.voice_enabled,
                             "voice_available": bool(settings.voice_enabled and settings.gemini_api_key),
                             "voice_output_enabled": settings.voice_output_enabled,
                             "confirm_actions": False,
                             "access_mode": "os_permissions", "default_directory": str(Path.home()),
                             "allowed_paths": ["/ (all Linux / WSL paths)", "/mnt (mounted Windows drives)"],
                             **request.app.state.desktop})

    async def status(request):
        if request.headers.get("x-assistant-token") != token:
            return JSONResponse({"error": "Invalid session token"}, status_code=403)
        manager = request.app.state.manager
        names = ("get_cpu_usage", "get_memory_usage", "get_disk_usage")
        results = await asyncio.gather(*(
            manager.call(name, {}, permission_result="dashboard_read") for name in names
        ), return_exceptions=True)
        return JSONResponse({name: None if isinstance(result, BaseException) else result
                             for name, result in zip(names, results)})

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
        now = clock()
        for key in list(pending):
            if pending[key][0] < now:
                del pending[key]
        assistant = request.app.state.assistant

        def propose(tool, arguments, reason, authentication=False):
            if len(pending) >= 100:
                return JSONResponse({"error": "Too many pending administrator requests."}, status_code=429)
            key = secrets.token_urlsafe(24)
            # Bind approval to the exact operation and absolute paths, not text
            # that could be reparsed differently after filesystem changes.
            pending[key] = (clock() + 120, tool, arguments.copy())
            return JSONResponse({"approval": key, "kind": "administrator",
                                 "description": reason, "tool": tool, "arguments": arguments,
                                 "authentication_required": authentication})

        if "approval" in data:
            key = data["approval"]
            entry = pending.pop(key, None) if isinstance(key, str) else None
            if entry is None:
                return JSONResponse({"error": "Approval expired or already used."}, status_code=409)
            if data.get("accept") is not True:
                return JSONResponse({"reply": "Administrator action cancelled."})
            _, tool, arguments = entry
            password = data.pop("password", None)
            if password is not None and (not isinstance(password, str) or len(password) > 1024 or "\n" in password or "\r" in password):
                return JSONResponse({"error": "Invalid password input"}, status_code=400)
            try:
                async with request.app.state.command_lock:
                    reply = await assistant.execute_approved(tool, arguments, password)
            except AuthenticationRequired as exc:
                return propose(tool, arguments, str(exc), authentication=True)
            finally:
                password = None
                body.clear()
        else:
            message = data.get("message")
            if not isinstance(message, str) or not message.strip() or len(message) > 8000:
                return JSONResponse({"error": "Enter a command of 1–8000 characters."}, status_code=400)
            try:
                async with request.app.state.command_lock:
                    reply = await assistant.handle(message)
            except ElevationRequired as exc:
                return propose(exc.tool, exc.arguments, exc.reason)
        return JSONResponse({"reply": reply})

    async def voice(websocket: WebSocket):
        host = websocket.headers.get("host", "")
        origin = websocket.headers.get("origin")
        if (host not in {"localhost:8765", "127.0.0.1:8765"}
                or (origin and origin != f"http://{host}")
                or websocket.query_params.get("token") != token):
            await websocket.close(code=1008)
            return
        settings = websocket.app.state.manager.settings
        await websocket.accept()
        if not settings.voice_enabled:
            await websocket.send_json(error_event("Voice is disabled in configuration.", recoverable=False))
            await websocket.close(code=1000)
            return
        try:
            session = voice_factory(api_key=settings.gemini_api_key,
                                    model=settings.gemini_live_model)
            async with session:
                await websocket.send_json(status_event("connected", "Voice connected"))

                async def send_audio():
                    try:
                        while True:
                            message = await websocket.receive()
                            if message["type"] == "websocket.disconnect":
                                break
                            chunk = message.get("bytes")
                            if chunk is not None:
                                await session.send_audio(chunk)
                    finally:
                        await session.end_audio()

                sender = asyncio.create_task(send_audio())
                event_iterator = session.events().__aiter__()
                try:
                    while not sender.done():
                        next_event = asyncio.create_task(event_iterator.__anext__())
                        done, _ = await asyncio.wait(
                            {sender, next_event}, return_when=asyncio.FIRST_COMPLETED
                        )
                        if sender in done:
                            next_event.cancel()
                            break
                        try:
                            event = next_event.result()
                        except StopAsyncIteration:
                            break
                        await websocket.send_json(event.as_json())
                finally:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        except (VoiceUnavailableError, ValueError) as exc:
            try:
                await websocket.send_json(error_event(str(exc), recoverable=True))
            except (RuntimeError, WebSocketDisconnect):
                pass
        except Exception:
            try:
                await websocket.send_json(error_event(
                    "Gemini Live disconnected. Voice will reconnect; text is still available.",
                    recoverable=True,
                ))
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            try:
                await websocket.close()
            except RuntimeError:
                pass

    app = Starlette(lifespan=lifespan, routes=[Route("/", index), Route("/api/config", config),
        Route("/api/status", status),
        Route("/api/command", command, methods=["POST"]),
        WebSocketRoute("/api/voice", voice),
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
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self' ws://localhost:8765 ws://127.0.0.1:8765; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response
    app.add_middleware(BaseHTTPMiddleware, dispatch=local_only)
    return app


def main():
    import uvicorn

    from app.main import _load_dotenv
    _load_dotenv()
    uvicorn.run(create_app(), host="127.0.0.1", port=8765, access_log=False)


if __name__ == "__main__":
    main()
