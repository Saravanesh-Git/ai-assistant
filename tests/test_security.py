import socket
from pathlib import Path

import pytest

from security.path_policy import PathPolicy, PathPolicyError
from security.url_policy import URLPolicyError, validate_public_url


def test_legacy_roots_do_not_restrict_paths(tmp_path):
    root = tmp_path / 'legacy'
    root.mkdir()
    policy = PathPolicy([root])
    assert policy.resolve_allowed(root / '..' / 'outside', must_exist=False) == tmp_path / 'outside'
    assert policy.resolve_allowed('/etc', must_exist=False) == Path('/etc')
    assert policy.resolve_allowed('/root/test', must_exist=False) == Path('/root/test')


def test_user_can_access_hidden_and_any_extension(tmp_path):
    note = tmp_path / '.ssh' / 'sample.key'
    note.parent.mkdir()
    note.write_text('test fixture, not a real key')
    assert PathPolicy().validate_text_file(note, max_size=100) == note


def test_symlinks_use_os_permissions(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target, target_is_directory=True)
    assert PathPolicy().resolve_allowed(link) == link


def test_resource_limits_and_invalid_paths(tmp_path):
    note = tmp_path / 'note.conf'
    note.write_text('x' * 11)
    with pytest.raises(PathPolicyError, match='size limit'):
        PathPolicy().validate_text_file(note, max_size=10)
    for invalid in ('', '  ', 'x\x00y'):
        with pytest.raises(PathPolicyError):
            PathPolicy().resolve_allowed(invalid, must_exist=False)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1",
        "http://localhost",
        "http://10.0.0.1",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]",
    ],
)
def test_unsafe_urls_rejected(url: str) -> None:
    with pytest.raises(URLPolicyError):
        validate_public_url(url)


def test_dns_resolving_to_private_ip_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", 80))],
    )
    with pytest.raises(URLPolicyError):
        validate_public_url("http://internal.example")


def test_public_ip_allowed() -> None:
    assert validate_public_url("https://93.184.216.34/page") == "https://93.184.216.34/page"

