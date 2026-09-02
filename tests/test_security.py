import socket
from pathlib import Path

import pytest

from security.path_policy import PathPolicy, PathPolicyError
from security.url_policy import URLPolicyError, validate_public_url


def test_allowed_path_and_traversal(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    policy = PathPolicy([root])
    assert policy.resolve_allowed(root) == root.resolve()
    with pytest.raises(PathPolicyError):
        policy.resolve_allowed(root / ".." / "outside", must_exist=False)


@pytest.mark.parametrize("path", ["/etc/shadow", "/root/test", "/usr/test"])
def test_arbitrary_system_paths_rejected(tmp_path: Path, path: str) -> None:
    policy = PathPolicy([tmp_path])
    with pytest.raises(PathPolicyError):
        policy.resolve_allowed(path, must_exist=False)


def test_sensitive_paths_rejected_even_inside_allowed_root(tmp_path: Path) -> None:
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    private_key = ssh / "id_rsa"
    private_key.write_text("secret", encoding="utf-8")
    policy = PathPolicy([tmp_path])
    with pytest.raises(PathPolicyError):
        policy.validate_text_file(private_key, max_size=100)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "escape"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathPolicyError):
        PathPolicy([root]).resolve_allowed(link)


def test_oversized_and_unsupported_files(tmp_path: Path) -> None:
    policy = PathPolicy([tmp_path])
    large = tmp_path / "large.txt"
    large.write_text("x" * 11, encoding="utf-8")
    with pytest.raises(PathPolicyError, match="size limit"):
        policy.validate_text_file(large, max_size=10)
    binary = tmp_path / "data.bin"
    binary.write_bytes(b"data")
    with pytest.raises(PathPolicyError, match="type"):
        policy.validate_text_file(binary, max_size=100)


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

