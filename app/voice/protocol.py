"""Small JSON protocol shared by the Live backend and browser adapter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranscriptEvent:
    text: str
    final: bool
    utterance_id: str | None = None

    def as_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "type": "final" if self.final else "interim",
            "text": self.text,
        }
        if self.utterance_id:
            payload["utterance_id"] = self.utterance_id
        return payload


def status_event(state: str, message: str = "") -> dict[str, str]:
    return {"type": "status", "state": state, "message": message}


def error_event(message: str, *, recoverable: bool = True) -> dict[str, object]:
    return {"type": "error", "message": message, "recoverable": recoverable}
