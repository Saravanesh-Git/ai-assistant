import errno
from pathlib import Path
from unittest.mock import patch
import pytest

from app.core.config import Settings
from security.path_policy import PathPolicy
from servers.linux_server.file_tools import (create_text_file_data, list_directory_data,
    copy_path_data, move_path_data, write_text_file_data, find_files_data, _rename_no_replace)
from servers.linux_server.application_tools import run_command_data
from servers.linux_server.operations import execute_operation


def test_create_any_extension_and_missing_parents_outside_legacy_roots(tmp_path):
    policy = PathPolicy([tmp_path / 'legacy'])
    target = tmp_path / 'another' / 'nested' / '.env'
    create_text_file_data(str(target), 'VALUE=1', policy, 100)
    assert target.read_text() == 'VALUE=1'
    with pytest.raises(FileExistsError):
        create_text_file_data(str(target), 'VALUE=2', policy, 100)
    write_text_file_data(str(target), '\nNEXT=2', policy, 100, append=True)
    assert target.read_text() == 'VALUE=1\nNEXT=2'
    write_text_file_data(str(target), 'REPLACED=3', policy, 100)
    assert target.read_text() == 'REPLACED=3'


def test_listing_broken_links_and_pagination(tmp_path):
    for name in ('a', 'b', 'c'):
        (tmp_path / name).touch()
    (tmp_path / 'broken').symlink_to(tmp_path / 'missing')
    first = list_directory_data(str(tmp_path), PathPolicy(), limit=2)
    assert first['count'] == 4 and first['next_offset'] == 2
    second = list_directory_data(str(tmp_path), PathPolicy(), offset=2, limit=2)
    assert {item['name'] for item in first['entries'] + second['entries']} == {'a', 'b', 'c', 'broken'}
    assert any(item['type'] == 'symlink' for item in second['entries'])


def test_copy_and_cross_device_move_without_overwrite(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'note').write_text('retained')
    target = tmp_path / 'destination'
    def rename(old, new):
        if old == source:
            raise OSError(errno.EXDEV, 'Cross-device link')
        return _rename_no_replace(old, new)
    with patch('servers.linux_server.file_tools._rename_no_replace', side_effect=rename):
        move_path_data(str(source), str(target), PathPolicy())
    assert not source.exists()
    assert (target / 'note').read_text() == 'retained'
    source.mkdir()
    (source / 'different').write_text('preserve')
    with patch('servers.linux_server.file_tools._rename_no_replace', side_effect=rename):
        with pytest.raises(FileExistsError):
            move_path_data(str(source), str(target), PathPolicy())
    assert (source / 'different').read_text() == 'preserve'
    assert not list(tmp_path.glob('.amigo-move-*'))


def test_find_reports_matches_and_does_not_follow_symlink_cycles(tmp_path):
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested' / 'note.conf').write_text('test')
    (tmp_path / 'nested' / 'loop').symlink_to(tmp_path)
    result = find_files_data('note', str(tmp_path), PathPolicy())
    assert result['matches'] == [str(tmp_path / 'nested/note.conf')]
    assert result['truncated'] is False


def test_commands_run_without_shell_unless_explicit(tmp_path):
    result = run_command_data('printf %s "literal;$(touch nope)"', str(tmp_path))
    assert result['output'] == 'literal;$(touch nope)'
    assert not (tmp_path / 'nope').exists()
    result = run_command_data('printf hello | tr a-z A-Z', str(tmp_path), shell=True)
    assert result['output'] == 'HELLO'
    for text, shell in [('sudo touch /root/demo', False), ('sudo touch /root/demo | cat', True)]:
        with patch('servers.linux_server.application_tools.subprocess.Popen') as launch:
            result = run_command_data(text, str(tmp_path), shell=shell)
            assert result['elevation_required']
            launch.assert_not_called()


def test_os_denial_is_not_misreported_as_missing_path(tmp_path):
    blocked = tmp_path / 'blocked'
    blocked.mkdir()
    blocked.chmod(0)
    try:
        result = execute_operation('create_text_file', {'path': str(blocked / 'note.conf'), 'content': ''}, Settings())
        assert result['elevation_required'] is True
        assert 'Permission denied' in result['reason']
    finally:
        blocked.chmod(0o700)


def test_shell_privilege_detection_checks_commands_not_echo_arguments(tmp_path):
    from servers.linux_server.application_tools import command_requests_admin
    assert not command_requests_admin('echo "sudo is a command"', shell=True)
    assert command_requests_admin('echo ready; sudo id', shell=True)
    assert command_requests_admin('echo ready\nsudo id', shell=True)
    assert command_requests_admin('env MODE=test sudo id', shell=True)
