"""Allowlist-based filesystem policy."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


SAFE_TEXT_EXTENSIONS = frozenset(
    {".txt", ".md", ".json", ".csv", ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml", ".toml"}
)
SENSITIVE_PARTS = frozenset(
    {".ssh", ".gnupg", ".gpg", "password-store", "keyrings", "mozilla", "chromium", "google-chrome"}
)
SENSITIVE_FILENAMES = frozenset(
    {"shadow", "gshadow", "id_rsa", "id_ed25519", "credentials", "login data", "key4.db", "secrets.json"}
)
PRIVATE_KEY_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


class PathPolicyError(ValueError):
    """Raised when a requested filesystem path violates policy."""


class PathPolicy:
    def __init__(self, allowed_roots: Iterable[Path | str]) -> None:
        roots = [Path(root).expanduser().resolve(strict=False) for root in allowed_roots]
        if not roots:
            raise ValueError("At least one allowed filesystem root is required")
        self.allowed_roots = tuple(dict.fromkeys(roots))

    def resolve_allowed(self, requested: str | Path, *, must_exist: bool = True) -> Path:
        if not str(requested).strip():
            raise PathPolicyError("Path cannot be empty")
        candidate = Path(os.path.expandvars(str(requested))).expanduser().resolve(strict=False)
        if not any(candidate == root or candidate.is_relative_to(root) for root in self.allowed_roots):
            raise PathPolicyError("Path is outside configured allowed directories")
        self._reject_sensitive(candidate)
        if must_exist and not candidate.exists():
            raise PathPolicyError("Path does not exist")
        return candidate

    def validate_text_file(self, requested: str | Path, *, max_size: int) -> Path:
        candidate = self.resolve_allowed(requested)
        if not candidate.is_file():
            raise PathPolicyError("Path is not a regular file")
        if candidate.suffix.lower() not in SAFE_TEXT_EXTENSIONS:
            raise PathPolicyError("File type is not allowed")
        if candidate.stat().st_size > max_size:
            raise PathPolicyError(f"File exceeds the {max_size}-byte size limit")
        return candidate

    @staticmethod
    def _reject_sensitive(candidate: Path) -> None:
        lower_parts = {part.casefold() for part in candidate.parts}
        name = candidate.name.casefold()
        if lower_parts & SENSITIVE_PARTS or name in SENSITIVE_FILENAMES:
            raise PathPolicyError("Sensitive paths are blocked")
        if name.endswith(PRIVATE_KEY_SUFFIXES) or name.startswith("id_"):
            raise PathPolicyError("Private-key files are blocked")

