"""Deterministic text/voice routing with machine-wide paths and explicit commands."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from security.command_policy import ALLOWED_APPLICATIONS, SAFE_COMMANDS
from security.desktop import windows_to_wsl, windows_profile


@dataclass(frozen=True, slots=True)
class Route:
    intent: str
    tool: str | None
    arguments: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    administrator: bool = False


class IntentRouter:
    _search = re.compile(
        r'^(?:please\s+)?(?:search(?:\s+the\s+web)?(?:\s+for)?|look\s+up|find(?:\s+(?:recent|latest))?\s+(?:news\s+)?(?:about|on))\s+(.+)$', re.I)

    def __init__(self, *, home: Path | None = None, allowed_paths: Iterable[Path | str] | None = None) -> None:
        # Legacy allowed_paths is ignored: it is neither a boundary nor a default directory.
        self.home = Path(os.path.abspath(home or Path.home()))
        self.default_directory = self.home
        self.path_aliases = {'home': self.home, 'my home': self.home, 'wsl home': self.home,
                             'root': Path('/'), 'wsl root': Path('/'), 'root home': Path('/root')}
        for name in ('Documents', 'Downloads', 'Desktop', 'Pictures', 'Projects'):
            self.path_aliases[name.casefold()] = self.home / name
        profile = windows_profile()
        if profile:
            self.path_aliases.update({'windows home': profile, 'windows': profile})
            for name in ('Documents', 'Downloads', 'Desktop', 'Pictures', 'Projects'):
                self.path_aliases['windows ' + name.casefold()] = profile / name
                if not (self.home / name).is_dir() and (profile / name).is_dir():
                    self.path_aliases[name.casefold()] = profile / name

    def route(self, message: str) -> Route:
        message = re.sub(r'^\s*hey[\s,]+amigo\b[\s,.!?]*', '', message, flags=re.I).strip()
        message = re.sub(r'^please\s+', '', message, flags=re.I)
        administrator = False
        if re.match(r'^sudo\s+', message, re.I):
            administrator = True
            message = re.sub(r'^sudo\s+', '', message, count=1, flags=re.I)
        if re.search(r'\s+(?:as (?:administrator|root)|with sudo)$', message, re.I):
            administrator = True
            message = re.sub(r'\s+(?:as (?:administrator|root)|with sudo)$', '', message, flags=re.I)
        route = self._route(message)
        # "sudo apt ..." also works without an extra "run" prefix.
        if administrator and route.tool is None and route.intent == 'unknown':
            route = Route('run_command', 'run_command', {'command': message, 'cwd': str(self.home)})
        return replace(route, administrator=administrator)

    def _route(self, message: str) -> Route:
        normalized = ' '.join(message.split())
        lower = normalized.casefold()
        if not normalized:
            return Route('empty', None)
        match = self._search.match(normalized)
        if match:
            query = re.sub(r'\s+(?:in|on)\s+the\s+web[.!?]?$', '', match[1], flags=re.I)
            return Route('web_search', 'open_browser_search', {'query': query.strip().rstrip('?.!').strip('\"\'“”')})

        match = re.fullmatch(r'(?:run|execute)\s+(?:command\s+)?(.+)', message, re.I | re.S)
        if match:
            command = match[1].strip()
            shell = bool(re.match(r'^shell\s+', command, re.I))
            if shell:
                command = re.sub(r'^shell\s+', '', command, count=1, flags=re.I)
            aliases = {'pwd': 'get_current_directory', 'date': 'get_date', 'whoami': 'get_logged_in_user',
                       'uname -r': 'get_kernel_version', 'hostname -i': 'get_ip_address'}
            key = aliases.get(command.lower(), command.lower())
            if not shell and key in SAFE_COMMANDS:
                return Route('run_safe_command', 'run_safe_command', {'command_id': key})
            return Route('run_command', 'run_command', {'command': command, 'cwd': str(self.home), 'shell': shell})

        match = re.fullmatch(r'(?:create|make)\s+(?:a\s+)?file(?:\s+called|\s+named)?\s+(.+?)(?:\s+with content\s+(.*))?', message, re.I | re.S)
        if match:
            path = self._creation_path(match[1])
            return self._path_route('create_text_file', path, content=match[2] or '')
        match = re.fullmatch(r'(write|overwrite|append)\s+(?:to\s+)?(?:file\s+)?(.+?)\s+with content\s+(.*)', message, re.I | re.S)
        if match:
            return self._path_route('write_text_file', self._safe_user_path(match[2]), content=match[3], append=match[1].lower() == 'append')
        match = re.fullmatch(r'(?:create|make)\s+(?:a\s+)?(?:folder|directory)(?:\s+called|\s+named)?\s+(.+)', message, re.I)
        if match:
            return self._path_route('create_directory', self._creation_path(match[1]))
        match = re.fullmatch(r'(move|rename|copy)\s+(.+?)\s+to\s+(.+)', message, re.I)
        if match:
            source, destination = self._safe_user_path(match[2]), self._safe_user_path(match[3])
            if source is None or destination is None:
                return Route('unsafe_path', None)
            tool = 'copy_path' if match[1].lower() == 'copy' else 'move_path'
            return Route(tool, tool, {'source': str(source), 'destination': str(destination)})
        match = re.fullmatch(r'(?:list|show)(?:\s+me)?(?:\s+the)?\s+(?:files|folders|contents|directory|directories)(?:\s+(?:in|of|at|under))?(?:\s+(.+?))?(?:\s+page\s+(\d+))?', message, re.I)
        if match:
            page = max(1, int(match[2] or 1))
            extra = {'offset': (page - 1) * 200} if page > 1 else {}
            return self._path_route('list_directory', self._safe_user_path(match[1] or 'home'), **extra)
        match = re.fullmatch(r'read\s+(?:file\s+)?(.+)', message, re.I)
        if match:
            return self._path_route('read_text_file', self._safe_user_path(match[1]))
        match = re.fullmatch(r'(?:find\s+(?:files?|folders?)|locate)\s+(.+?)(?:\s+(?:in|under|at)\s+(.+))?', message, re.I)
        if match:
            name = match[1].strip().strip('\"\'')
            path = self._safe_user_path(match[2] or 'home')
            return self._path_route('find_files', path, name=name)

        match = re.fullmatch(r'(?:open|launch|start)\s+(.+)', message, re.I)
        if match:
            target = match[1].strip().strip('\"\'')
            key = target.lower().rstrip('.!?')
            aliases = {'file explorer': 'windows_files', 'windows explorer': 'windows_files',
                       'vs code': 'code', 'visual studio code': 'code'}
            key = aliases.get(key, key)
            key = re.sub(r'^windows (calculator|notepad|files|terminal|edge|chrome|code)$', r'windows_\1', key)
            if key in ALLOWED_APPLICATIONS:
                return Route('open_application', 'open_application', {'application': key})
            path_like = target.startswith(('/', '~', '.')) or re.match(r'^[A-Za-z]:', target) or key in self.path_aliases
            if path_like:
                path = self._safe_user_path(target)
                if path and path.suffix.lower() in {'.exe', '.appimage'}:
                    return Route('open_application', 'open_application', {'application': str(path)})
                return self._path_route('open_path', path)
            return Route('open_application', 'open_application', {'application': target})

        if any(term in lower for term in ('system information', 'system info', 'computer information')):
            return Route('get_system_info', 'get_system_info')
        if re.search(r'\b(cpu|processor)\b', lower) and any(term in lower for term in ('usage', 'load', 'show', 'check', 'what')):
            return Route('get_cpu_usage', 'get_cpu_usage')
        if re.search(r'\b(ram|memory)\b', lower):
            return Route('get_memory_usage', 'get_memory_usage')
        if re.search(r'\b(disk|storage|drive)\b', lower) and any(term in lower for term in ('space', 'usage', 'free', 'available', 'how much')):
            return Route('get_disk_usage', 'get_disk_usage', {'path': '/'})
        if 'battery' in lower:
            return Route('get_battery_status', 'get_battery_status')
        if any(term in lower for term in ('current directory', 'working directory', 'where am i')):
            return Route('get_current_directory', 'run_safe_command', {'command_id': 'get_current_directory'})
        return Route('unknown', None, confidence=0.0)

    @staticmethod
    def _path_route(tool: str, path: Path | None, **arguments) -> Route:
        return Route(tool, tool, {'path': str(path), **arguments}) if path is not None else Route('unsafe_path', None)

    def _creation_path(self, value: str) -> Path | None:
        value = value.strip()
        destination_first = re.fullmatch(r'(?:in|at|under|on)\s+(.+?)\s+(?:named|called)\s+(.+)', value, re.I)
        if destination_first:
            parent = self._safe_user_path(destination_first[1])
            name = destination_first[2].strip().strip('"\'')
            if parent is None or Path(windows_to_wsl(name)).is_absolute():
                return None
            return self._safe_user_path(str(parent / name))
        value = re.sub(r'^at\s+', '', value, flags=re.I)
        match = re.fullmatch(r'(\"[^\"]+\"|\'[^\']+\'|.+?)(?:\s+(?:in|at|under|on)\s+(.+))?', value, re.I)
        if not match:
            return None
        name = match[1].strip().strip('\"\'')
        if match[2] is None:
            return self._safe_user_path(name)
        destination = match[2].strip()
        if not destination.startswith(('"', "'")):
            destination = re.sub(r'\s+(?:folder|directory)$', '', destination, flags=re.I)
        parent = self._safe_user_path(destination)
        normalized_name = windows_to_wsl(name)
        if parent is None or Path(normalized_name).is_absolute():
            return None
        return self._safe_user_path(str(parent / normalized_name))

    def _safe_user_path(self, value: str) -> Path | None:
        value = value.strip().strip('\"\'')
        if not value or '\x00' in value:
            return None
        # Common dictated path separators, plus C drive / C: drive-root aliases.
        value = re.sub(r'\s+(?:backslash|forward slash|slash)\s+', '/', value, flags=re.I)
        match = re.fullmatch(r'([a-z])(?:\s+drive|:)(?:[/\\](.*))?', value, re.I)
        if match:
            value = f'/mnt/{match[1].lower()}/{(match[2] or "").replace(chr(92), "/")}'
        value = windows_to_wsl(os.path.expandvars(value))
        lower = value.casefold()
        if lower in self.path_aliases:
            return self.path_aliases[lower]
        first, separator, rest = value.partition('/')
        if separator and first.casefold() in self.path_aliases:
            value = str(self.path_aliases[first.casefold()] / rest)
        try:
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = self.home / candidate
            return Path(os.path.abspath(candidate))
        except (OSError, ValueError, RuntimeError):
            return None
