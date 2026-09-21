"""Small JSON protocol shared by the Live backend and browser adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    text: str
    final: bool

    def as_json(self) -> dict[str, object]:
        return {"type": "final" if self.final else "interim", "text": self.text}


def status_event(state: str, message: str = "") -> dict[str, str]:
    return {"type": "status", "state": state, "message": message}


def error_event(message: str, *, recoverable: bool = True) -> dict[str, object]:
    return {"type": "error", "message": message, "recoverable": recoverable}
