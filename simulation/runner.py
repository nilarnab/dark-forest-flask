from __future__ import annotations

import logging
import math
import time
import uuid

from firebase.repository import UniverseRepository
from simulation.activity import UniverseActivityTracker, is_universe_active
from simulation.clock import simulation_time
from simulation.universe import apply_projectile_cleanup, apply_projectile_processing, updates_for_universe
from simulation.movement import position_for_object_at_time
from simulation.projectile import build_projectile


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
        self.projectile_range = 1000.0
        self.projectile_blast_impact = 50.0
        self.projectile_retention_seconds = 10.0
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
            # Level 1's agent is intentionally simple: once the combat lesson
            # is armed it fires at the player's home star every five seconds.
            self._maybe_fire_level_one_agent(universe_id, universe, current_time, now_ms)
            if not apply_projectile_cleanup(universe, current_time, self.hit_event_retention_seconds):
                continue

            def clean(current):
                if isinstance(current, dict):
                    apply_projectile_cleanup(current, current_time, self.hit_event_retention_seconds)
                return current

            self.repository.transaction_universe(universe_id, clean)
            deleted += 1
        return deleted

    def run_level_one_agent_tick(self, universe_id: str) -> bool:
        """Advance the Level 1 agent from a client heartbeat.

        Render can run HTTP requests and background threads in different
        processes.  The activity tracker is deliberately in-memory, so a
        background worker cannot reliably see the universe touched by the
        request-handling process.  Heartbeats, however, are received in the
        exact process serving the player.  Use them as a small, idempotent
        scheduler for the tutorial agent.
        """
        universe = self.repository.get_universe(universe_id)
        if not is_universe_active(universe):
            return False
        now_ms = time.time() * 1000
        return self._maybe_fire_level_one_agent(
            universe_id,
            universe,
            simulation_time(universe, now_ms),
            now_ms,
        )

    def _maybe_fire_level_one_agent(self, universe_id: str, universe: dict, current_time: float, now_ms: float) -> bool:
        agent_state = universe.get("agent_state")
        objects = universe.get("objects")
        if not isinstance(agent_state, dict) or not isinstance(objects, dict): return False
        agent = agent_state.get("agent_level_1_enemy")
        if not isinstance(agent, dict) or agent.get("active") is not True: return False
        last = float(agent.get("last_fire_at", float("-inf")))
        if current_time - last < 5: return False
        ship_id = agent.get("ship_id")
        ship = objects.get(ship_id)
        target = next(((oid, obj) for oid, obj in objects.items() if isinstance(obj, dict) and obj.get("type") == "NATURAL" and obj.get("owner") not in {None, "agent_level_1"}), None)
        if not isinstance(ship, dict) or target is None: return False
        gun = next((item for item in (ship.get("objects") or {}).values() if isinstance(item, dict) and item.get("type") == "GUN"), None)
        source = position_for_object_at_time(ship, objects, current_time)
        target_location = target[1].get("location")
        if not isinstance(gun, dict) or not source or not isinstance(target_location, dict): return False
        velocity, hit_radius = gun.get("velocity"), gun.get("hit_radius")
        if not isinstance(velocity, (int, float)) or not isinstance(hit_radius, (int, float)): return False
        # build_projectile deliberately accepts degrees, matching the player
        # shot endpoint. Passing raw atan2 radians made agent shots appear to
        # travel in random directions.
        rotation = math.degrees(math.atan2(float(target_location["y"]) - source["y"], float(target_location["x"]) - source["x"]))
        projectile_id = f"projectile_{uuid.uuid4().hex}"
        firing_ship = dict(ship); firing_ship["location"] = source
        projectile = build_projectile(firing_ship, current_time, rotation, float(velocity), self.projectile_range, source_objectid=ship_id, hit_radius=float(hit_radius), blast_impact=self.projectile_blast_impact, retention_seconds=self.projectile_retention_seconds)
        def commit(current):
            if not isinstance(current, dict): return current
            current_objects = current.get("objects")
            current_agent = (current.get("agent_state") or {}).get("agent_level_1_enemy")
            if not isinstance(current_objects, dict) or not isinstance(current_agent, dict) or current_agent.get("active") is not True: return current
            # A heartbeat from another tab/process may have scheduled the
            # same shot while this transaction was waiting.  Recheck the
            # persisted cooldown before committing a second projectile.
            if current_time - float(current_agent.get("last_fire_at", float("-inf"))) < 5:
                return current
            current_objects[projectile_id] = projectile
            current.setdefault("events", {})[f"fire_{projectile_id}"] = {"type": "PROJECTILE_FIRED", "projectile_id": projectile_id, "source_id": ship_id, "occurred_at": current_time, "start_location": projectile["location"], "rotation": rotation, "velocity": velocity, "hit_radius": hit_radius, "range": self.projectile_range}
            current_agent["last_fire_at"] = current_time
            current["time"] = current_time; current["time_updated_at_ms"] = now_ms
            return current
        self.repository.transaction_universe(universe_id, commit)
        logger.info("Level 1 agent fired in universe %s at simulation time %.3f.", universe_id, current_time)
        return True

    def run_projectile_cleanup_forever(self) -> None:
        next_tick = time.monotonic()
        while True:
            try:
                self.run_projectile_cleanup_tick()
            except Exception:
                logger.exception("Projectile cleanup tick failed; will retry shortly.")
            next_tick += self.projectile_cleanup_seconds
            time.sleep(max(0.0, next_tick - time.monotonic()))
