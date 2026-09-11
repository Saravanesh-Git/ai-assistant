"""Fast deterministic routing for common assistant requests."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Iterable
from typing import Any

from security.command_policy import ALLOWED_APPLICATIONS


@dataclass(frozen=True, slots=True)
class Route:
    intent: str
    tool: str | None
    arguments: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


class IntentRouter:
    _search = re.compile(
        r"^(?:please\s+)?(?:search(?:\s+the\s+web)?(?:\s+for)?|look\s+up|find(?:\s+(?:recent|latest))?\s+(?:news\s+)?(?:about|on))\s+(.+)$",
        re.IGNORECASE,
    )
    _open = re.compile(r"^(?:please\s+)?(?:open|launch|start)\s+([a-z0-9_-]+)\s*[.!?]?$", re.IGNORECASE)
    _create = re.compile(
        r"^(?:please\s+)?(?:create|make)\s+(?:a\s+)?(?:folder|directory)(?:\s+called|\s+named)?\s+(.+?)\s*[.!?]?$",
        re.IGNORECASE,
    )
    _list = re.compile(
        r"^(?:please\s+)?(?:list|show)(?:\s+me)?(?:\s+the)?\s+(?:files|contents)(?:\s+in|\s+of)?\s+(.+?)\s*[.!?]?$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        home: Path | None = None,
        allowed_paths: Iterable[Path | str] | None = None,
    ) -> None:
        self.home = (home or Path.home()).resolve(strict=False)
        roots = tuple(Path(root).expanduser().resolve(strict=False) for root in (allowed_paths or ()))
        # Relative paths use the first configured root, never an invented Projects folder.
        self.default_directory = roots[0] if roots else self.home
        self.path_aliases = {}
        standard_names = ("Documents", "Downloads", "Desktop", "Pictures", "Projects")
        for root in roots or (self.home,):
            for name in standard_names:
                child = root / name
                if child.is_dir():
                    self.path_aliases.setdefault(name.casefold(), child)
        for root in roots:
            self.path_aliases[root.name.casefold()] = root

    def route(self, message: str) -> Route:
        normalized = " ".join(message.strip().split())
        lower = normalized.casefold()
        if not normalized:
            return Route("empty", None, confidence=1.0)

        # Parse structured file commands before broad informational keywords.
        match = re.fullmatch(r'(?:please\s+)?(?:create|make)\s+(?:a\s+)?file(?:\s+called|\s+named)?\s+(.+?)(?:\s+with content\s+(.*))?', message.strip(), re.I | re.S)
        if match:
            path = self._creation_path(match[1])
            return Route("create_text_file", "create_text_file", {"path": str(path), "content": match[2] or ""}) if path else Route("unsafe_path", None)
        match = re.fullmatch(r'(?:please\s+)?move\s+(.+?)\s+to\s+(.+)', message.strip(), re.I)
        if match:
            paths = [self._safe_user_path(value.strip().strip('"\'')) for value in match.groups()]
            return Route("move_path", "move_path", dict(zip(("source", "destination"), map(str, paths)))) if all(paths) else Route("unsafe_path", None)
        normalized = re.sub(
            r"^((?:please\s+)?(?:open|launch|start)\s+)windows\s+(calculator|notepad|files|terminal)([.!?]?)$",
            r"\1windows_\2\3", normalized, flags=re.I,
        )

        if any(term in lower for term in ("system information", "system info", "computer information")):
            return Route("get_system_info", "get_system_info")
        if re.search(r"\b(cpu|processor)\b", lower) and any(
            term in lower for term in ("usage", "load", "show", "check", "what")
        ):
            return Route("get_cpu_usage", "get_cpu_usage")
        if re.search(r"\b(ram|memory)\b", lower):
            return Route("get_memory_usage", "get_memory_usage")
        if re.search(r"\b(disk|storage|drive)\b", lower) and any(
            term in lower for term in ("space", "usage", "free", "available", "how much")
        ):
            return Route("get_disk_usage", "get_disk_usage", {"path": "/"})
        if "battery" in lower:
            return Route("get_battery_status", "get_battery_status")
        if any(term in lower for term in ("current directory", "working directory", "where am i")):
            return Route(
                "get_current_directory",
                "run_safe_command",
                {"command_id": "get_current_directory"},
            )

        match = self._open.match(normalized)
        if match:
            application = match.group(1).casefold()
            if application in ALLOWED_APPLICATIONS:
                return Route("open_application", "open_application", {"application": application})
            return Route("unsupported_application", None, {"application": application}, confidence=0.95)

        match = self._create.match(normalized)
        if match:
            path = self._creation_path(match.group(1))
            if path is not None:
                return Route("create_directory", "create_directory", {"path": str(path)})
            return Route("unsafe_path", None, confidence=1.0)

        match = self._list.match(normalized)
        if match:
            raw_path = match.group(1).strip().strip('"\'')
            path = self._safe_user_path(raw_path)
            if path is not None:
                return Route("list_directory", "list_directory", {"path": str(path)})
            return Route("unsafe_path", None, confidence=1.0)

        match = self._search.match(normalized)
        if match:
            query = match.group(1).strip().rstrip("?.!")
            if query:
                return Route("web_search", "search_web", {"query": query, "max_results": 5})

        return Route("unknown", None, confidence=0.0)

    def _creation_path(self, value: str) -> Path | None:
        # Quoted names can contain literal " in "; unquoted "in" introduces a folder.
        match = re.fullmatch(
            r"(\"[^\"]+\"|'[^']+'|.+?)(?:\s+in\s+(.+))?", value.strip(), re.I
        )
        if not match:
            return None
        name = match[1].strip().strip("\"'")
        if match[2] is None:
            return self._safe_user_path(name)
        destination = match[2].strip()
        if not destination.startswith(("\"", "'")):
            destination = re.sub(r"\s+(?:folder|directory)$", "", destination, flags=re.I)
        parent = self._safe_user_path(destination.strip("\"'"))
        # An explicit destination takes a filename, not a second absolute path.
        if parent is None or Path(name).name != name or name in (".", ".."):
            return None
        return self._safe_user_path(str(parent / name))

    def _safe_user_path(self, value: str) -> Path | None:
        if not value or "\x00" in value:
            return None
        try:
            lower = value.casefold()
            if lower in self.path_aliases:
                return self.path_aliases[lower]
            first, separator, rest = value.partition("/")
            if separator and first.casefold() in self.path_aliases:
                return (self.path_aliases[first.casefold()] / rest).resolve(strict=False)
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = self.default_directory / candidate
            return candidate.resolve(strict=False)
        except (OSError, ValueError):
            return None
