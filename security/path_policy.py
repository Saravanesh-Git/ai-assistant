"""Path normalization and resource checks; filesystem access follows OS permissions."""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Iterable

from security.desktop import windows_to_wsl


class PathPolicyError(ValueError):
    """Invalid path or unsupported file operation (not an access allowlist)."""


class PathPolicy:
    def __init__(self, allowed_roots: Iterable[Path | str] = ()) -> None:
        # Kept as a compatibility argument; legacy roots no longer restrict access.
        self.allowed_roots = (Path('/'),)

    def resolve_allowed(self, requested: str | Path, *, must_exist: bool = True) -> Path:
        value = str(requested)
        if not value.strip() or '\x00' in value:
            raise PathPolicyError('Enter a non-empty path without NUL characters')
        value = windows_to_wsl(os.path.expandvars(value))
        # Do not resolve symlinks or inspect parents here: inaccessible ancestors
        # must reach the operation so PermissionError can trigger elevation.
        candidate = Path(os.path.abspath(os.path.expanduser(value)))
        if must_exist:
            candidate.stat()  # Unlike exists(), preserves PermissionError on Python 3.14.
        return candidate

    def validate_text_file(self, requested: str | Path, *, max_size: int) -> Path:
        candidate = self.resolve_allowed(requested)
        info = candidate.stat()
        if not stat.S_ISREG(info.st_mode):
            raise PathPolicyError('Path is not a regular file')
        if info.st_size > max_size:
            raise PathPolicyError(f'File exceeds the {max_size}-byte response size limit')
        return candidate
