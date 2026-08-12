from __future__ import annotations

import logging
import time

from firebase.repository import UniverseRepository
from simulation.activity import UniverseActivityTracker, is_universe_active
from simulation.clock import simulation_time
from simulation.universe import apply_projectile_cleanup, apply_projectile_processing, updates_for_universe


logger = logging.getLogger(__name__)


class SimulationRunner:
    def __init__(self, repository: UniverseRepository, tick_seconds: float = 1.0, activity: UniverseActivityTracker | None = None, write_positions: bool = False) -> None:
        self.repository = repository
        self.activity = activity or UniverseActivityTracker()
        self.tick_seconds = tick_seconds
        self.write_positions = write_positions
        self.projectile_processing_seconds = 0.1
        self.projectile_cleanup_seconds = 1.0
        self.hit_event_retention_seconds = 10.0
        self.hit_distance_tolerance = 0.01
        self._projectile_times: dict[str, float] = {}

    def run_tick(self) -> int:
        if not self.write_positions:
            # Movement is analytic from curve data and time_updated_at_ms. The
            # fast projectile workers below remain authoritative for outcomes.
            return 0
        universe_ids = self.activity.active_universe_ids()
        updated = 0
        now_ms = time.time() * 1000
        for universe_id in universe_ids:
            # Keep the snapshot and its write atomic with respect to local
            # Flask requests such as a transfer transaction.
            with self.repository.universe_lock(universe_id):
                universe = self.repository.get_universe(universe_id)
                if not is_universe_active(universe):
                    continue
                self.repository.atomic_update(updates_for_universe(universe_id, universe, self.tick_seconds, now_ms))
                updated += 1
        return updated

    def run_forever(self) -> None:
        next_tick = time.monotonic()
        while True:
            try:
                updated = self.run_tick()
                logger.info("Simulation tick completed for %s universe(s).", updated)
            except Exception:
                logger.exception("Simulation tick failed; will retry next tick.")
            next_tick += self.tick_seconds
            time.sleep(max(0.0, next_tick - time.monotonic()))

    def run_projectile_processing_tick(self) -> int:
        updated = 0
        now_ms = time.time() * 1000
        for universe_id in self.activity.active_universe_ids():
            # Do not hold the local universe lock while waiting on Firebase.
            # On a deployed service this read can take longer than the 0.1s
            # collision interval, starving /shots and other player actions.
            universe = self.repository.get_universe(universe_id)
            if not is_universe_active(universe):
                continue
            end_time = simulation_time(universe, now_ms)
            start_time = self._projectile_times.get(universe_id, float(universe.get("time", 0)))
            if end_time <= start_time:
                continue

            # Evaluate a detached Firebase snapshot first. The fast loop
            # must not commit a transaction every 100ms when no projectile
            # actually hit or expired.
            changed = apply_projectile_processing(universe, start_time, end_time, self.hit_distance_tolerance)
            self._projectile_times[universe_id] = end_time
            if not changed:
                continue

            def process(current):
                if not isinstance(current, dict):
                    return current
                apply_projectile_processing(current, start_time, end_time, self.hit_distance_tolerance)
                return current

            self.repository.transaction_universe(universe_id, process)
            updated += 1
        return updated

    def run_projectile_processing_forever(self) -> None:
        next_tick = time.monotonic()
        while True:
            try:
                self.run_projectile_processing_tick()
            except Exception:
                logger.exception("Projectile processing tick failed; will retry shortly.")
            next_tick += self.projectile_processing_seconds
            time.sleep(max(0.0, next_tick - time.monotonic()))

    def run_projectile_cleanup_tick(self) -> int:
        deleted = 0
        now_ms = time.time() * 1000
        for universe_id in self.activity.active_universe_ids():
            # As above, keep Firebase reads outside the local write lock so a
            # slow network response cannot delay player action endpoints.
            universe = self.repository.get_universe(universe_id)
            if not is_universe_active(universe):
                continue
            current_time = simulation_time(universe, now_ms)
            if not apply_projectile_cleanup(universe, current_time, self.hit_event_retention_seconds):
                continue

            def clean(current):
                if isinstance(current, dict):
                    apply_projectile_cleanup(current, current_time, self.hit_event_retention_seconds)
                return current

            self.repository.transaction_universe(universe_id, clean)
            deleted += 1
        return deleted

    def run_projectile_cleanup_forever(self) -> None:
        next_tick = time.monotonic()
        while True:
            try:
                self.run_projectile_cleanup_tick()
            except Exception:
                logger.exception("Projectile cleanup tick failed; will retry shortly.")
            next_tick += self.projectile_cleanup_seconds
            time.sleep(max(0.0, next_tick - time.monotonic()))
