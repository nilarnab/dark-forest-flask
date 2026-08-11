from __future__ import annotations

from collections import defaultdict
from queue import Empty, Full, Queue
from threading import Lock
from typing import Any, Iterator


class LiveEventBus:
    """Process-local fan-out for latency-sensitive, non-authoritative events."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = Lock()

    def subscribe(self, universe_id: str) -> Queue[dict[str, Any]]:
        subscriber: Queue[dict[str, Any]] = Queue(maxsize=32)
        with self._lock:
            self._subscribers[universe_id].add(subscriber)
        return subscriber

    def unsubscribe(self, universe_id: str, subscriber: Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(universe_id)
            if not subscribers:
                return
            subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(universe_id, None)

    def publish(self, universe_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            subscribers = list(self._subscribers.get(universe_id, ()))
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except Full:
                # A slow client can safely miss a cosmetic event; Firebase
                # still supplies the authoritative projectile record.
                pass

    def stream(self, universe_id: str) -> Iterator[dict[str, Any] | None]:
        subscriber = self.subscribe(universe_id)
        try:
            while True:
                try:
                    yield subscriber.get(timeout=15)
                except Empty:
                    yield None
        finally:
            self.unsubscribe(universe_id, subscriber)
