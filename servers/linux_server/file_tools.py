"""Filesystem operations protected by the shared path policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from security.path_policy import PathPolicy


def list_directory_data(path: str, policy: PathPolicy) -> dict[str, Any]:
    directory = policy.resolve_allowed(path)
    if not directory.is_dir():
        raise ValueError("Path is not a directory")
    entries = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())):
        stat = child.stat(follow_symlinks=False)
        entries.append(
            {
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
                "size": None if child.is_dir() else stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    return {"path": str(directory), "entries": entries, "count": len(entries)}


def read_text_file_data(path: str, policy: PathPolicy, max_size: int) -> dict[str, Any]:
    file_path = policy.validate_text_file(path, max_size=max_size)
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("File is not valid UTF-8 text") from exc
    return {"path": str(file_path), "content": content, "size": file_path.stat().st_size}


def create_directory_data(path: str, policy: PathPolicy) -> dict[str, Any]:
    directory = policy.resolve_allowed(path, must_exist=False)
    existed = directory.exists()
    if existed and not directory.is_dir():
        raise ValueError("A non-directory already exists at this path")
    directory.mkdir(parents=True, exist_ok=True)
    return {"path": str(directory), "created": not existed}

