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



def create_text_file_data(path: str, content: str, policy: PathPolicy, max_size: int) -> dict[str, Any]:
    from security.path_policy import SAFE_TEXT_EXTENSIONS
    target = policy.resolve_allowed(path, must_exist=False)
    if target.suffix.lower() not in SAFE_TEXT_EXTENSIONS:
        raise ValueError("File type is not allowed")
    if not target.parent.is_dir():
        raise ValueError(f"Destination folder does not exist: {target.parent}. Create the folder first.")
    encoded = content.encode("utf-8")
    if len(encoded) > max_size:
        raise ValueError("Content exceeds the file size limit")
    # Exclusive creation refuses overwrite, including a concurrently created file.
    with target.open("xb") as stream:
        stream.write(encoded)
    return {"path": str(target), "created": True}


def move_path_data(source: str, destination: str, policy: PathPolicy) -> dict[str, Any]:
    import ctypes
    import errno
    import os
    source_path = policy.resolve_allowed(source)
    target = policy.resolve_allowed(destination, must_exist=False)
    if source_path in policy.allowed_roots or target in policy.allowed_roots:
        raise ValueError("Configured roots cannot be moved or replaced")
    if source_path == target or target.is_relative_to(source_path):
        raise ValueError("Destination must be a different path outside the source")
    if source_path.is_dir():
        for directory, dirs, files in os.walk(source_path, followlinks=False):
            for name in dirs + files:
                child = Path(directory) / name
                if child.is_symlink():
                    raise ValueError("Moving directories containing symlinks is not supported")
                policy.resolve_allowed(child)
    elif not source_path.is_file():
        raise ValueError("Only regular files and directories can be moved")
    # Linux/WSL atomic no-replace rename, including directories. Fail closed on
    # unsupported filesystems; cross-device copy/delete needs a separate workflow.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise ValueError("Atomic moves are unavailable on this platform")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source_path), -100, os.fsencode(target), 1) != 0:
        error = ctypes.get_errno()
        if error == errno.EXDEV:
            raise ValueError("Cross-filesystem moves are not supported; use paths on the same drive")
        raise OSError(error, os.strerror(error))
    return {"source": str(source_path), "destination": str(target)}
