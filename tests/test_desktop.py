from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import Settings
from app.providers.factory import PROVIDERS, create_provider
from app.providers.rule_based import RuleBasedProvider
from security.desktop import windows_to_wsl, resolve_executable, windows_profile
from servers.linux_server.application_tools import open_browser_search_data, open_application_data


def test_windows_browser_search_uses_encoded_url_without_shell():
    query = 'cats & dogs; $(touch /tmp/nope) "中文"'
    with patch('servers.linux_server.application_tools.is_wsl', return_value=True), \
         patch('servers.linux_server.application_tools.resolve_executable', return_value='/mnt/c/Windows/explorer.exe'), \
         patch('servers.linux_server.application_tools.subprocess.Popen', return_value=Mock(wait=Mock(return_value=1))) as launch:
        result = open_browser_search_data(query)
    argv = launch.call_args.args[0]
    assert argv[0] == '/mnt/c/Windows/explorer.exe'
    assert len(argv) == 2
    assert parse_qs(urlsplit(argv[1]).query) == {'q': [query]}
    assert launch.call_args.kwargs['shell'] is False
    assert result['opened'] is True


def test_browser_missing_returns_usable_link():
    with patch('servers.linux_server.application_tools.resolve_executable', return_value=None):
        result = open_browser_search_data('hello')
    assert result == {'query': 'hello', 'url': 'https://www.google.com/search?q=hello', 'opened': False}
    with pytest.raises(ValueError):
        open_browser_search_data(' ')
    with pytest.raises(ValueError):
        open_browser_search_data('x' * 2001)


def test_browser_launch_failure_does_not_report_success():
    with patch('servers.linux_server.application_tools.is_wsl', return_value=False), \
         patch('servers.linux_server.application_tools.resolve_executable', return_value='/usr/bin/xdg-open'), \
         patch('servers.linux_server.application_tools.subprocess.Popen', return_value=Mock(wait=Mock(return_value=3))):
        assert open_browser_search_data('test')['opened'] is False


def test_wsl_defaults_to_windows_apps():
    with patch('servers.linux_server.application_tools.is_wsl', return_value=True), \
         patch('servers.linux_server.application_tools.resolve_executable', return_value='/mnt/c/Windows/System32/calc.exe'), \
         patch('servers.linux_server.application_tools.subprocess.Popen', return_value=Mock(pid=1)) as launch:
        assert open_application_data('calculator')['application'] == 'windows_calculator'
        assert launch.call_args.args[0] == ['/mnt/c/Windows/System32/calc.exe']


def test_executable_fallback_without_windows_path():
    with patch('security.desktop.is_wsl', return_value=True), \
         patch('security.desktop.shutil.which', return_value=None), \
         patch('security.desktop.windows_profile', return_value=None), \
         patch.object(Path, 'is_file', lambda path: str(path) == '/mnt/c/Windows/System32/calc.exe'):
        assert resolve_executable('calc.exe') == '/mnt/c/Windows/System32/calc.exe'
        assert resolve_executable('unknown.exe') is None


def test_windows_profile_discovery_and_path_conversion(monkeypatch):
    assert windows_to_wsl(r'D:\My files\notes.txt') == '/mnt/d/My files/notes.txt'
    assert windows_to_wsl('/home/me/notes.txt') == '/home/me/notes.txt'
    monkeypatch.delenv('ASSISTANT_WINDOWS_PROFILE', raising=False)
    windows_profile.cache_clear()
    try:
        with patch('security.desktop.is_wsl', return_value=True), \
             patch('security.desktop.shutil.which', return_value='cmd.exe'), \
             patch('security.desktop.subprocess.run', return_value=Mock(returncode=0, stdout='C:\\Users\\Me\r\n')) as run:
            assert windows_profile() == Path('/mnt/c/Users/Me')
            assert run.call_args.args[0] == ['cmd.exe', '/d', '/c', 'echo', '%USERPROFILE%']
    finally:
        windows_profile.cache_clear()


def test_provider_extension_and_fallback(monkeypatch):
    provider = RuleBasedProvider()
    monkeypatch.setitem(PROVIDERS, 'custom', lambda settings: provider)
    assert create_provider(Settings(llm_provider='custom')) is provider
    def broken(settings):
        raise RuntimeError('Provider cannot load')
    monkeypatch.setitem(PROVIDERS, 'broken', broken)
    assert create_provider(Settings(llm_provider='broken')).name == 'rule_based'
    assert create_provider(Settings(llm_provider='unknown')).name == 'rule_based'
