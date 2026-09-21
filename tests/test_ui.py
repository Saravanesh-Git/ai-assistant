from unittest.mock import Mock, patch

import pytest
from starlette.testclient import TestClient

from app.core.router import IntentRouter
from app.voice.protocol import TranscriptEvent
from app.web.server import create_app
from security.path_policy import PathPolicy
from servers.linux_server.application_tools import open_application_data
from servers.linux_server.file_tools import create_text_file_data, move_path_data


class Manager:
    available_tools = ('create_directory',)
    calls = []
    def __init__(self, settings):
        self.settings = settings
        self.calls = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def call(self, tool, arguments, **kwargs):
        self.calls.append((tool, arguments))
        return {'path': arguments['path'], 'created': True}


class FakeVoice:
    instances = []
    def __init__(self, *, api_key, model):
        self.api_key_received = bool(api_key)
        self.model = model
        self.audio = []
        self.ended = False
        self.__class__.instances.append(self)
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def send_audio(self, chunk): self.audio.append(chunk)
    async def end_audio(self): self.ended = True
    async def events(self):
        yield TranscriptEvent('open the', False)
        yield TranscriptEvent('open the browser', True)


def test_file_creation_and_moves(tmp_path):
    root = tmp_path / 'Projects'
    root.mkdir()
    policy = PathPolicy([root])
    source, target = root / 'a.txt', root / 'b.txt'
    create_text_file_data(str(source), 'hello', policy, 10)
    with pytest.raises(FileExistsError):
        create_text_file_data(str(source), 'overwrite', policy, 10)
    with pytest.raises(ValueError):
        create_text_file_data(str(target), 'too long', policy, 1)
    create_text_file_data(str(tmp_path / 'outside.txt'), '', policy, 10)
    assert (tmp_path / 'outside.txt').exists()
    target.write_text('keep')
    with pytest.raises(FileExistsError):
        move_path_data(str(source), str(target), policy)
    assert source.read_text() == 'hello' and target.read_text() == 'keep'
    move_path_data(str(source), str(root / 'c.txt'), policy)
    assert not source.exists()
    folder = root / 'folder'
    folder.mkdir()
    (folder / 'note.txt').write_text('note')
    move_path_data(str(folder), str(root / 'renamed'), policy)
    assert (root / 'renamed/note.txt').read_text() == 'note'
    with pytest.raises(ValueError):
        move_path_data(str(root), str(root / 'oops'), policy)


def test_new_routes(tmp_path):
    router = IntentRouter(home=tmp_path)
    route = router.route('create file Projects/memory.txt with content hello\nworld')
    assert route.tool == 'create_text_file'
    assert route.arguments == {'path': str(tmp_path / 'Projects/memory.txt'), 'content': 'hello\nworld'}
    assert router.route('move Projects/a.txt to Projects/b.txt').tool == 'move_path'
    assert router.route('open windows calculator').arguments == {'application': 'windows_calculator'}


def test_windows_fixed_launch():
    with patch('servers.linux_server.application_tools.resolve_executable', return_value='/mnt/c/Windows/System32/calc.exe'), patch('servers.linux_server.application_tools.subprocess.Popen', return_value=Mock(pid=1)) as launch:
        open_application_data('windows_calculator')
        assert launch.call_args.args[0] == ['/mnt/c/Windows/System32/calc.exe']
        assert launch.call_args.kwargs['shell'] is False


def test_web_direct_actions_and_config(monkeypatch):
    monkeypatch.delenv('ASSISTANT_CONFIRM_ACTIONS', raising=False)
    app = create_app(Manager)
    with TestClient(app, base_url='http://localhost:8765') as client:
        config = client.get('/api/config').json()
        assert config['wake_phrase'] == 'Hey Amigo'
        assert config['confirm_actions'] is False
        headers = {'x-assistant-token': config['token']}
        response = client.post('/api/command', headers=headers, json={'message': 'create folder demo'})
        assert 'approval' not in response.json()
        assert response.json()['reply'].startswith('Created:')
        assert len(app.state.manager.calls) == 1
        assert client.get('/api/status').status_code == 403
        assert client.post('/api/command', headers=headers, json={'message': 'x' * 8001}).status_code == 400
        assert client.post('/api/command', headers=headers, json={'message': 'x' * 17000}).status_code == 413
        assert client.post('/api/command', headers=headers, content='text').status_code == 415
        assert 'A.M.I.G.O.' in client.get('/').text


def test_live_voice_websocket_is_backend_authenticated_and_separates_transcripts(monkeypatch):
    monkeypatch.setenv('VOICE_ENABLED', 'true')
    monkeypatch.setenv('GEMINI_API_KEY', 'backend-only-secret')
    FakeVoice.instances.clear()
    app = create_app(Manager, voice_factory=FakeVoice)
    with TestClient(app, base_url='http://localhost:8765') as client:
        config = client.get('/api/config').json()
        assert config['voice_available'] is True
        assert 'backend-only-secret' not in str(config)
        with client.websocket_connect(
            f"/api/voice?token={config['token']}",
            headers={"host":"localhost:8765", "origin":"http://localhost:8765"},
        ) as socket:
            assert socket.receive_json()['state'] == 'connected'
            socket.send_bytes(b'\x00\x00')
            assert socket.receive_json() == {'type':'interim', 'text':'open the'}
            assert socket.receive_json() == {'type':'final', 'text':'open the browser'}
    assert FakeVoice.instances[0].api_key_received is True
