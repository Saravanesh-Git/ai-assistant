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
        self.path_aliases = {
            name.casefold(): self.home / name
            for name in ("Documents", "Downloads", "Desktop", "Pictures", "Projects")
        }
        for configured in allowed_paths or ():
            root = Path(configured).expanduser().resolve(strict=False)
            self.path_aliases[root.name.casefold()] = root

    def route(self, message: str) -> Route:
        normalized = " ".join(message.strip().split())
        lower = normalized.casefold()
        if not normalized:
            return Route("empty", None, confidence=1.0)

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
            raw_name = match.group(1).strip().strip('"\'')
            path = self._safe_user_path(raw_name, default_root="Projects")
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

    def _safe_user_path(self, value: str, default_root: str | None = None) -> Path | None:
        if not value or "\x00" in value:
            return None
        lower = value.casefold()
        if lower in self.path_aliases:
            return self.path_aliases[lower]
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            if default_root:
                base = self.path_aliases.get(default_root.casefold(), self.home / default_root)
                candidate = base / candidate
            else:
                candidate = self.home / candidate
        try:
            return candidate.resolve(strict=False)
        except OSError:
            return None
