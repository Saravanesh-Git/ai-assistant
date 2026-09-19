from pathlib import Path
import base64
import subprocess
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
         patch('servers.linux_server.application_tools.resolve_executable', return_value='powershell.exe'), \
         patch('servers.linux_server.application_tools.subprocess.run', return_value=Mock(returncode=0)) as launch:
        result = open_browser_search_data(query)
    argv = launch.call_args.args[0]
    assert argv[0] == 'powershell.exe'
    script = base64.b64decode(argv[-1]).decode('utf-16-le')
    assert '[Console]::In.ReadToEnd()' in script
    assert 'Start-Process -FilePath $url -ErrorAction Stop' in script
    assert query not in script
    assert parse_qs(urlsplit(launch.call_args.kwargs['input']).query) == {'q': [query]}
    assert launch.call_args.kwargs['shell'] is False
    assert result['opened'] is True


@pytest.mark.parametrize('failure', [1, OSError('unavailable'), subprocess.TimeoutExpired('powershell', 10)])
def test_windows_search_falls_back_to_browser_on_protocol_launch_failure(failure):
    with patch('servers.linux_server.application_tools.is_wsl', return_value=True), \
         patch('servers.linux_server.application_tools.resolve_executable',
               side_effect=lambda name: name if name in {'powershell.exe', 'msedge.exe'} else None) as resolve, \
         patch('servers.linux_server.application_tools.subprocess.run') as protocol, \
         patch('servers.linux_server.application_tools.subprocess.Popen',
               return_value=Mock(wait=Mock(return_value=0))) as browser:
        if isinstance(failure, Exception):
            protocol.side_effect = failure
        else:
            protocol.return_value = Mock(returncode=failure)
        assert open_browser_search_data('OpenAI')['opened'] is True
    assert browser.call_args.args[0] == ['msedge.exe', 'https://www.google.com/search?q=OpenAI']
    assert 'explorer.exe' not in [call.args[0] for call in resolve.call_args_list]


def test_windows_launchers_exiting_with_error_do_not_report_success():
    with patch('servers.linux_server.application_tools.is_wsl', return_value=True), \
         patch('servers.linux_server.application_tools.resolve_executable', side_effect=lambda name: name) as resolve, \
         patch('servers.linux_server.application_tools.subprocess.run', return_value=Mock(returncode=1)), \
         patch('servers.linux_server.application_tools.subprocess.Popen', return_value=Mock(wait=Mock(return_value=1))):
        assert open_browser_search_data('OpenAI')['opened'] is False
    assert [call.args[0] for call in resolve.call_args_list] == [
        'powershell.exe', 'wslview', 'msedge.exe', 'chrome.exe']


def test_wslview_success_uses_url_argument():
    with patch('servers.linux_server.application_tools.is_wsl', return_value=True), \
         patch('servers.linux_server.application_tools.resolve_executable',
               side_effect=lambda name: name if name == 'wslview' else None), \
         patch('servers.linux_server.application_tools.subprocess.run', return_value=Mock(returncode=0)) as launch:
        assert open_browser_search_data('OpenAI')['opened'] is True
    assert launch.call_args.args[0] == ['wslview', 'https://www.google.com/search?q=OpenAI']


def test_powershell_discovery_without_windows_path():
    executable = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
    with patch('security.desktop.is_wsl', return_value=True), \
         patch('security.desktop.shutil.which', return_value=None), \
         patch('security.desktop.windows_profile', return_value=None), \
         patch.object(Path, 'is_file', lambda path: str(path) == executable):
        assert resolve_executable('powershell.exe') == executable


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
