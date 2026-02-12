from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Optional


@dataclass
class PendingSessionState:
    pending_confirm: Optional[dict] = None
    pending_action: Optional[dict] = None
    pending_selection: Optional[dict] = None


class SessionStateStore:
    def __init__(self) -> None:
        self._states: dict[str, PendingSessionState] = {}
        self._lock = Lock()

    def get(self, session_id: str) -> PendingSessionState:
        key = session_id or "default"
        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = PendingSessionState()
                self._states[key] = state
            return state

    def update_from_result(self, session_id: str, result: dict) -> PendingSessionState:
        state = self.get(session_id)
        with self._lock:
            state.pending_confirm = result.get("pending_confirm")
            state.pending_action = result.get("pending_action")
            state.pending_selection = result.get("pending_selection")
            return state
