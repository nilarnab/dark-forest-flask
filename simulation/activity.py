from __future__ import annotations

import time
from threading import Lock


class UniverseActivityTracker:
    """In-process presence timestamps for universes with active game clients."""

    def __init__(self, timeout_seconds: float = 45) -> None:
        self.timeout_seconds = max(1.0, timeout_seconds)
        self._last_seen: dict[str, float] = {}
        self._lock = Lock()

    def touch(self, universe_id: str) -> None:
        with self._lock:
            self._last_seen[universe_id] = time.monotonic()

    def active_universe_ids(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            expired = [universe_id for universe_id, last_seen in self._last_seen.items() if now - last_seen >= self.timeout_seconds]
            for universe_id in expired:
                self._last_seen.pop(universe_id, None)
            return list(self._last_seen)


def is_universe_active(universe: object) -> bool:
    return isinstance(universe, dict) and universe.get("active") is True
