"""Single-use sudo worker; not a persistent root service and not an MCP tool."""
from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path


def main():
    if os.geteuid() != 0:
        raise SystemExit('Administrator worker must be started by sudo')
    print('AMIGO_WORKER_READY', flush=True)
    raw = sys.stdin.buffer.readline(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise SystemExit('Request exceeds size limit')
    request = json.loads(raw)
    # -I prevents cwd/PYTHONPATH injection; only this trusted application's root
    # is added, and only the exact approved operation is dispatched.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from app.core.config import Settings
    from servers.linux_server.operations import execute_operation
    allowed_environment = {'PATH', 'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR',
                           'DBUS_SESSION_BUS_ADDRESS', 'WSL_INTEROP', 'WSL_DISTRO_NAME',
                           'ASSISTANT_WINDOWS_PROFILE'}
    os.environ.update({key: value for key, value in request.get('environment', {}).items()
                       if key in allowed_environment and isinstance(value, str)})
    settings = Settings(max_file_size=request['max_file_size'],
                        command_timeout_seconds=request['command_timeout_seconds'])
    signal.alarm(settings.command_timeout_seconds + 10)
    try:
        result = execute_operation(request['tool'], request['arguments'], settings, elevated=True)
        print(json.dumps({'data': result}), flush=True)
    except Exception as exc:
        message = str(exc)
        if isinstance(exc, PermissionError):
            message += ' Administrator access was also denied. For Windows drives, check Windows ACLs; Linux sudo cannot override them.'
        print(json.dumps({'error': message}), flush=True)
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
