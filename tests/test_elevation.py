from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from starlette.testclient import TestClient

from app.core.config import Settings
from app.core.elevation import ElevationRequired, AuthenticationRequired, ElevationError
from app.core.assistant import Assistant
from app.providers.rule_based import RuleBasedProvider
from app.web.server import create_app
from servers.linux_server.operations import execute_operation


class Manager:
    available_tools = ('create_directory', 'run_command')
    def __init__(self, settings):
        self.settings, self.calls = settings, []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def call(self, tool, arguments, **kwargs):
        self.calls.append((tool, arguments))
        if arguments.get('path', '').startswith('/root'):
            return {'elevation_required': True, 'reason': 'Permission denied: /root'}
        return {'path': arguments['path'], 'created': True}


def test_old_env_flags_are_ignored(monkeypatch):
    monkeypatch.setenv('ASSISTANT_ALLOWED_PATHS', '/wrong/home')
    monkeypatch.setenv('ASSISTANT_CONFIRM_ACTIONS', 'true')
    settings = Settings()
    assert settings.allowed_paths == (Path('/'),)
    assert settings.confirm_actions is False


def test_os_permission_error_becomes_elevation_proposal():
    with patch('servers.linux_server.file_tools.create_directory_data', side_effect=PermissionError(13, 'Permission denied', '/root')):
        result = execute_operation('create_directory', {'path': '/root/demo'}, Settings())
        assert result['elevation_required'] is True
        with pytest.raises(PermissionError):
            execute_operation('create_directory', {'path': '/root/demo'}, Settings(), elevated=True)


@pytest.mark.asyncio
async def test_root_action_stops_before_elevation():
    manager = Manager(Settings())
    assistant = Assistant(manager, RuleBasedProvider())
    with pytest.raises(ElevationRequired) as error:
        await assistant.handle('create folder /root/demo')
    assert error.value.arguments == {'path': '/root/demo'}
    assert len(manager.calls) == 1
    with pytest.raises(ElevationRequired):
        await assistant.handle('create folder /opt/demo as administrator')
    assert len(manager.calls) == 1  # explicit sudo does not attempt an ordinary mutation


def test_one_use_approval_is_bound_to_exact_operation_and_authentication():
    now = [0]
    app = create_app(Manager, clock=lambda: now[0])
    with patch('app.core.assistant.run_elevated', new_callable=AsyncMock) as elevated, TestClient(app, base_url='http://localhost:8765') as client:
        token = client.get('/api/config').json()['token']
        headers = {'x-assistant-token': token}
        assert client.post('/api/command', json={'message': 'create folder /root/demo'}).status_code == 403
        assert client.post('/api/command', headers={**headers, 'origin': 'https://evil.example'}, json={}).status_code == 403
        proposal = client.post('/api/command', headers=headers, json={'message': 'create folder /root/demo'}).json()
        assert proposal['kind'] == 'administrator'
        elevated.assert_not_awaited()
        elevated.side_effect = AuthenticationRequired('Enter your Linux sudo password.')
        auth = client.post('/api/command', headers=headers, json={'approval': proposal['approval'], 'accept': True,
            'tool': 'run_command', 'arguments': {'command': 'tampered'}}).json()
        assert auth['authentication_required'] is True
        assert elevated.call_args.args[:2] == ('create_directory', {'path': '/root/demo'})
        assert client.post('/api/command', headers=headers, json={'approval': proposal['approval'], 'accept': True}).status_code == 409
        elevated.side_effect = None
        elevated.return_value = {'path': '/root/demo', 'created': True}
        result = client.post('/api/command', headers=headers, json={'approval': auth['approval'], 'accept': True, 'password': 'test-only-secret'}).json()
        assert result['reply'] == 'Created: /root/demo'
        assert 'test-only-secret' not in str(result)
        assert elevated.call_args.args[-1] == 'test-only-secret'
        proposal = client.post('/api/command', headers=headers, json={'message': 'create folder /root/other'}).json()
        now[0] = 121
        assert client.post('/api/command', headers=headers, json={'approval': proposal['approval'], 'accept': True}).status_code == 409


def test_cancel_and_normal_requests_never_invoke_sudo():
    with patch('app.core.assistant.run_elevated', new_callable=AsyncMock) as elevated, TestClient(create_app(Manager), base_url='http://localhost:8765') as client:
        headers = {'x-assistant-token': client.get('/api/config').json()['token']}
        normal = client.post('/api/command', headers=headers, json={'message': 'create folder /tmp/demo'}).json()
        assert 'approval' not in normal
        proposal = client.post('/api/command', headers=headers, json={'message': 'create folder /root/demo'}).json()
        cancelled = client.post('/api/command', headers=headers, json={'approval': proposal['approval'], 'accept': False}).json()
        assert 'cancelled' in cancelled['reply']
        elevated.assert_not_awaited()


class FakeSudo:
    """Exercise the actual bridge's stream handshake without running sudo."""
    def __init__(self, mode):
        import asyncio
        self.mode, self.writes, self.returncode = mode, [], None
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.stdin = self
        if mode == 'cached':
            self.stdout.feed_data(b'AMIGO_WORKER_READY\n')
        elif mode == 'denied':
            self.stderr.feed_data(b'User is not in the sudoers file\n')
            self.finish()
        else:
            # Split prompt deliberately: sudo can emit it in multiple chunks.
            self.stderr.feed_data(b'AMIGO_SUDO_')
            self.stderr.feed_data(b'PASSWORD:')
    def write(self, data):
        import json
        self.writes.append(data)
        if data.startswith(b'{'):
            self.request = json.loads(data)
            self.stdout.feed_data(b'{"data":{"path":"/root/demo","created":true}}\n')
            self.finish()
        elif self.mode == 'wrong':
            self.stderr.feed_data(b'Sorry, try again.\nAMIGO_SUDO_PASSWORD:')
        else:
            self.stdout.feed_data(b'AMIGO_WORKER_READY\n')
    async def drain(self):
        pass
    def close(self):
        pass
    def finish(self):
        self.returncode = 0
        self.stdout.feed_eof()
        self.stderr.feed_eof()
    def terminate(self):
        self.finish()
    async def wait(self):
        return self.returncode


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,password', [('cached', None), ('authenticate', 'test-password')])
async def test_sudo_handshake_never_sends_operation_as_password(mode, password):
    from app.core.elevation import run_elevated
    process = FakeSudo(mode)
    with patch('app.core.elevation.shutil.which', return_value='/fake/sudo'), \
         patch('app.core.elevation.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process) as spawn:
        result = await run_elevated('create_directory', {'path': '/root/demo'}, Settings(), password)
    assert result['created'] is True
    assert process.request['arguments'] == {'path': '/root/demo'}
    assert 'password' not in process.request
    assert 'test-password' not in str(spawn.call_args.args)
    assert not any(value == 'test-password' for value in spawn.call_args.kwargs['env'].values())
    if password:
        assert process.writes[0] == b'test-password\n'
        assert process.writes[1].startswith(b'{')
    else:
        assert len(process.writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,password,error', [
    ('authenticate', None, AuthenticationRequired),
    ('wrong', 'wrong-password', AuthenticationRequired),
    ('denied', None, ElevationError),
])
async def test_sudo_authentication_failure_never_dispatches_operation(mode, password, error):
    from app.core.elevation import run_elevated
    process = FakeSudo(mode)
    with patch('app.core.elevation.shutil.which', return_value='/fake/sudo'), \
         patch('app.core.elevation.asyncio.create_subprocess_exec', new_callable=AsyncMock, return_value=process):
        with pytest.raises(error):
            await run_elevated('create_directory', {'path': '/root/demo'}, Settings(), password)
    assert not any(data.startswith(b'{') for data in process.writes)
    assert process.returncode is not None
