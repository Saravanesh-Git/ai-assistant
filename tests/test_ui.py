from pathlib import Path
from unittest.mock import patch, Mock

import pytest
from starlette.testclient import TestClient

from app.web.server import create_app
from app.core.router import IntentRouter
from security.path_policy import PathPolicy, PathPolicyError
from servers.linux_server.file_tools import create_text_file_data, move_path_data
from servers.linux_server.application_tools import open_application_data


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


def test_web_approval_and_origin():
    app = create_app(Manager)
    with TestClient(app, base_url='http://localhost:8765') as client:
        assert client.get('/').status_code == 200
        assert client.get('/api/config', headers={'host': 'evil.example'}).status_code == 403
        token = client.get('/api/config').json()['token']
        headers = {'x-assistant-token': token}
        assert client.post('/api/command', json={'message': 'create folder demo'}).status_code == 403
        assert client.post('/api/command', headers={**headers, 'origin': 'https://evil.example'}, json={}).status_code == 403
        proposal = client.post('/api/command', headers=headers, json={'message': 'create folder demo'}).json()
        assert not app.state.manager.calls
        result = client.post('/api/command', headers=headers, json={'approval': proposal['approval'], 'accept': True})
        assert result.json()['reply'].startswith('Created:')
        assert len(app.state.manager.calls) == 1
        assert client.post('/api/command', headers=headers, json={'approval': proposal['approval'], 'accept': True}).status_code == 409
        proposal = client.post('/api/command', headers=headers, json={'message': 'create folder other'}).json()
        client.post('/api/command', headers=headers, json={'approval': proposal['approval'], 'accept': False})
        assert len(app.state.manager.calls) == 1
        assert client.post('/api/command', headers=headers, json=[]).status_code == 400


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
    with pytest.raises(PathPolicyError):
        create_text_file_data(str(tmp_path / 'outside.txt'), '', policy, 10)
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
    router = IntentRouter(allowed_paths=[tmp_path / 'Projects'])
    route = router.route('create file Projects/memory.txt with content hello\nworld')
    assert route.tool == 'create_text_file'
    assert route.arguments == {'path': str(tmp_path / 'Projects/memory.txt'), 'content': 'hello\nworld'}
    assert router.route('move Projects/a.txt to Projects/b.txt').tool == 'move_path'
    assert router.route('open windows calculator').arguments == {'application': 'windows_calculator'}


def test_windows_fixed_launch():
    with patch('servers.linux_server.application_tools.shutil.which', return_value='/mnt/c/Windows/System32/calc.exe'), patch('servers.linux_server.application_tools.subprocess.Popen', return_value=Mock(pid=1)) as launch:
        open_application_data('windows_calculator')
        assert launch.call_args.args[0] == ['/mnt/c/Windows/System32/calc.exe']
        assert launch.call_args.kwargs['shell'] is False
