"""Filesystem operations across the machine, governed by OS permissions."""
from __future__ import annotations

import errno
import os
import shutil
import stat
import time
import tempfile
from pathlib import Path
from typing import Any

from security.path_policy import PathPolicy


def list_directory_data(path: str, policy: PathPolicy, offset: int = 0, limit: int = 200) -> dict[str, Any]:
    directory = policy.resolve_allowed(path)
    if offset < 0 or not 1 <= limit <= 1000:
        raise ValueError('Use a nonnegative offset and a limit from 1 to 1000')
    entries = []
    # A broken link or one unreadable child must not hide the rest of a directory.
    with os.scandir(directory) as iterator:
        names = sorted(iterator, key=lambda item: item.name.casefold())
    for child in names[offset:offset + limit]:
        item = {'name': child.name, 'path': child.path}
        try:
            info = child.stat(follow_symlinks=False)
            kind = 'symlink' if stat.S_ISLNK(info.st_mode) else 'directory' if stat.S_ISDIR(info.st_mode) else 'file'
            item.update(type=kind, size=info.st_size, modified=info.st_mtime)
        except OSError as exc:
            item.update(type='unavailable', error=str(exc))
        entries.append(item)
    return {'path': str(directory), 'entries': entries, 'count': len(names),
            'offset': offset, 'next_offset': offset + limit if offset + limit < len(names) else None}


def read_text_file_data(path: str, policy: PathPolicy, max_size: int) -> dict[str, Any]:
    file_path = policy.validate_text_file(path, max_size=max_size)
    with file_path.open('rb') as stream:
        content = stream.read(max_size + 1)
    if len(content) > max_size:
        raise ValueError(f'File exceeds the {max_size}-byte response size limit')
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('This file is not UTF-8 text; open it with its associated application') from exc
    return {'path': str(file_path), 'content': text, 'size': len(content)}


def create_directory_data(path: str, policy: PathPolicy) -> dict[str, Any]:
    directory = policy.resolve_allowed(path, must_exist=False)
    try:
        directory.mkdir(parents=True)
        created = True
    except FileExistsError:
        if not stat.S_ISDIR(directory.stat().st_mode):
            raise ValueError('A non-directory already exists at this path')
        created = False
    return {'path': str(directory), 'created': created}


def create_text_file_data(path: str, content: str, policy: PathPolicy, max_size: int) -> dict[str, Any]:
    target = policy.resolve_allowed(path, must_exist=False)
    encoded = content.encode('utf-8')
    if len(encoded) > max_size:
        raise ValueError('Content exceeds the request size limit')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Any filename/extension is accepted. Explicit creation never overwrites.
    with target.open('xb') as stream:
        stream.write(encoded)
    return {'path': str(target), 'created': True}


def write_text_file_data(path: str, content: str, policy: PathPolicy, max_size: int, append: bool = False) -> dict[str, Any]:
    target = policy.resolve_allowed(path, must_exist=False)
    encoded = content.encode('utf-8')
    if len(encoded) > max_size:
        raise ValueError('Content exceeds the request size limit')
    try:
        if not stat.S_ISREG(target.stat().st_mode):
            raise ValueError('Path is not a regular file')
    except FileNotFoundError:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('ab' if append else 'wb') as stream:
        stream.write(encoded)
    return {'path': str(target), 'written': len(encoded), 'append': append}


def _rename_no_replace(source: Path, destination: Path) -> None:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise ValueError('Atomic no-replace moves are unavailable on this platform')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def copy_path_data(source: str, destination: str, policy: PathPolicy) -> dict[str, Any]:
    source_path = policy.resolve_allowed(source, must_exist=False)
    source_path.lstat()
    target = policy.resolve_allowed(destination, must_exist=False)
    if target == source_path or target.is_relative_to(source_path):
        raise ValueError('Destination must be outside the source')
    # Resolving here prevents copying a directory into itself through an alias.
    if target.resolve().is_relative_to(source_path.resolve()):
        raise ValueError('Destination must be outside the source')
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_symlink():
        os.symlink(os.readlink(source_path), target)
    elif source_path.is_dir():
        # copytree refuses an existing destination and preserves symlinks.
        shutil.copytree(source_path, target, symlinks=True)
    else:
        with source_path.open('rb') as incoming, target.open('xb') as outgoing:
            shutil.copyfileobj(incoming, outgoing)
    return {'source': str(source_path), 'destination': str(target), 'copied': True}


def move_path_data(source: str, destination: str, policy: PathPolicy) -> dict[str, Any]:
    source_path = policy.resolve_allowed(source, must_exist=False)
    source_path.lstat()
    target = policy.resolve_allowed(destination, must_exist=False)
    if source_path == Path('/') or target == Path('/'):
        raise ValueError('A filesystem root cannot be renamed')
    if source_path == target or target.resolve().is_relative_to(source_path.resolve()):
        raise ValueError('Destination must be a different path outside the source')
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _rename_no_replace(source_path, target)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # Copy into a private staging directory on the destination filesystem,
        # commit without replacement, then remove the source only after success.
        stage = Path(tempfile.mkdtemp(prefix='.amigo-move-', dir=target.parent))
        try:
            copy_path_data(str(source_path), str(stage / 'payload'), policy)
            _rename_no_replace(stage / 'payload', target)
        finally:
            shutil.rmtree(stage)
        try:
            if source_path.is_dir() and not source_path.is_symlink():
                shutil.rmtree(source_path)
            else:
                source_path.unlink()
        except OSError as cleanup_error:
            return {'source': str(source_path), 'destination': str(target),
                    'source_retained': True, 'cleanup_error': str(cleanup_error)}
    return {'source': str(source_path), 'destination': str(target)}


def find_files_data(name: str, path: str, policy: PathPolicy, limit: int = 100) -> dict[str, Any]:
    root = policy.resolve_allowed(path)
    if not name.strip() or not 1 <= limit <= 1000:
        raise ValueError('Enter a filename and a result limit from 1 to 1000')
    results, skipped, visited = [], 0, 0
    pending = [root]
    deadline = time.monotonic() + 5
    while pending and len(results) < limit and visited < 20000 and time.monotonic() < deadline:
        directory = pending.pop()
        try:
            with os.scandir(directory) as children:
                for child in children:
                    visited += 1
                    if name.casefold() in child.name.casefold():
                        results.append(child.path)
                    if child.is_dir(follow_symlinks=False):
                        pending.append(Path(child.path))
                    if len(results) >= limit or visited >= 20000 or time.monotonic() >= deadline:
                        return {'path': str(root), 'matches': results, 'skipped': skipped, 'truncated': True}
        except PermissionError:
            if directory == root:
                raise
            skipped += 1
        except OSError:
            skipped += 1
    return {'path': str(root), 'matches': results, 'skipped': skipped, 'truncated': bool(pending)}
