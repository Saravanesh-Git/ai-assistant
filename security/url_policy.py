"""URL and DNS validation used to prevent server-side request forgery."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class URLPolicyError(ValueError):
    """Raised when a URL targets a disallowed destination."""


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not any(
        (
            ip.is_private,
            ip.is_loopback,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def validate_public_url(url: str) -> str:
    if len(url) > 2048:
        raise URLPolicyError("URL is too long")
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise URLPolicyError("Only HTTP and HTTPS URLs are allowed")
    if not parsed.hostname or parsed.username or parsed.password:
        raise URLPolicyError("URL host is invalid")
    host = parsed.hostname.casefold().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise URLPolicyError("Localhost is blocked")
    try:
        addresses = {str(ipaddress.ip_address(host))}
    except ValueError:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            }
        except socket.gaierror as exc:
            raise URLPolicyError("URL host could not be resolved") from exc
    if not addresses or any(not _is_public(address) for address in addresses):
        raise URLPolicyError("Private, local, or reserved network targets are blocked")
    return url
