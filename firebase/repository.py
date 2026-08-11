from __future__ import annotations

from contextlib import contextmanager
from threading import Lock, RLock
from typing import Any, Iterator

from firebase_admin import db
from firebase.client import root_reference


class TransactionConflictError(RuntimeError):
    pass


class UniverseRepository:
    def __init__(self) -> None:
        self._locks: dict[str, RLock] = {}
        self._locks_guard = Lock()

    @contextmanager
    def universe_lock(self, universe_id: str) -> Iterator[None]:
        """Serialize read/write work for one universe inside this process."""
        with self._locks_guard:
            lock = self._locks.setdefault(universe_id, RLock())
        with lock:
            yield

    def list_universe_ids(self) -> list[str]:
        universes = root_reference().child("universes").get() or {}
        return list(universes.keys()) if isinstance(universes, dict) else []

    def get_universe(self, universe_id: str) -> dict[str, Any] | None:
        data = root_reference().child("universes").child(universe_id).get()
        return data if isinstance(data, dict) else None

    def atomic_update(self, updates: dict[str, Any]) -> None:
        if updates:
            root_reference().update(updates)

    def transaction_universe(self, universe_id: str, update_function):
        with self.universe_lock(universe_id):
            try:
                return root_reference().child("universes").child(universe_id).transaction(update_function)
            except db.TransactionAbortedError as error:
                raise TransactionConflictError("Universe is busy updating. Please retry the maneuver.") from error
