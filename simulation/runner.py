from __future__ import annotations

import logging
import math
import time

from firebase.repository import UniverseRepository
from simulation.activity import UniverseActivityTracker, is_universe_active
from simulation.clock import simulation_time
from simulation.universe import apply_projectile_cleanup, apply_projectile_processing, updates_for_universe
from simulation.movement import position_for_object_at_time
from simulation.projectile import ProjectileError
from simulation.shots import prepare_shot
from simulation.transfer import TransferError, apply_transfer_plan, build_transfer_plan


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
        self.star_death_blast_radius = 200.0
        self.star_death_blast_damage = 100.0
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
            if not apply_projectile_cleanup(universe, current_time, self.hit_event_retention_seconds, self.star_death_blast_radius, self.star_death_blast_damage):
                continue

            def clean(current):
                if isinstance(current, dict):
                    apply_projectile_cleanup(current, current_time, self.hit_event_retention_seconds, self.star_death_blast_radius, self.star_death_blast_damage)
                return current

            self.repository.transaction_universe(universe_id, clean)
            deleted += 1
        return deleted

    def run_career_agent_tick_from_client(self, universe_id: str, requesting_user: str | None = None) -> bool:
        """Advance a career agent from an explicit authenticated client tick."""
        # Multiple tabs may tick together. Serialize the read/cooldown/write
        # sequence so only one request can claim a firing interval in the
        # configured single Gunicorn process.
        with self.repository.universe_lock(universe_id):
            universe = self.repository.get_universe(universe_id)
            if not is_universe_active(universe):
                return False
            participants = universe.get("participants")
            if requesting_user is not None and (
                not isinstance(participants, dict) or requesting_user not in participants
            ):
                raise PermissionError("The authenticated user is not a participant in this universe.")
            now_ms = time.time() * 1000
            return self.run_career_agent_tick(
                universe_id,
                universe,
                simulation_time(universe, now_ms),
                now_ms,
            )

    def run_career_agent_tick(self, universe_id: str, universe: dict | None = None, current_time: float | None = None, now_ms: float | None = None) -> bool:
        """Run the small deterministic AI scheduler for the active career level."""
        if universe is None:
            universe = self.repository.get_universe(universe_id)
        if not is_universe_active(universe):
            return False
        resolved_now_ms = time.time() * 1000 if now_ms is None else now_ms
        resolved_time = simulation_time(universe, resolved_now_ms) if current_time is None else current_time
        if universe.get("career_level") == 2:
            return self._maybe_run_level_two_agent(universe_id, universe, resolved_time, resolved_now_ms)
        return self._maybe_fire_level_one_agent(universe_id, universe, resolved_time, resolved_now_ms)

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
        gun_entry = next(((gun_id, item) for gun_id, item in (ship.get("objects") or {}).items() if isinstance(gun_id, str) and isinstance(item, dict) and item.get("type") == "GUN"), None)
        source = position_for_object_at_time(ship, objects, current_time)
        target_location = target[1].get("location")
        if gun_entry is None or not source or not isinstance(target_location, dict): return False
        gun_id, _gun = gun_entry
        # Player input supplies degrees. The agent derives the exact same
        # input from its live position, then uses the player shot operation.
        rotation = math.degrees(math.atan2(float(target_location["y"]) - source["y"], float(target_location["x"]) - source["x"]))
        try:
            shot = prepare_shot(
                universe_id, universe, ship_id, gun_id, rotation,
                projectile_range=self.projectile_range,
                projectile_blast_impact=self.projectile_blast_impact,
                projectile_retention_seconds=self.projectile_retention_seconds,
                client_fired_at=current_time,
                now_ms=now_ms,
            )
        except ProjectileError:
            logger.exception("Level 1 agent could not prepare a shot in universe %s.", universe_id)
            return False
        updates = dict(shot.updates)
        updates[f"universes/{universe_id}/agent_state/agent_level_1_enemy/last_fire_at"] = shot.fired_at
        self.repository.atomic_update(updates)
        logger.info("Level 1 agent fired in universe %s at simulation time %.3f.", universe_id, shot.fired_at)
        return True

    def _maybe_run_level_two_agent(self, universe_id: str, universe: dict, current_time: float, now_ms: float) -> bool:
        """Avoidant ship plus enemy-home bombardment for the authored Level 2 chart."""
        objects = universe.get("objects")
        career = universe.get("career_state")
        agent_state = universe.get("agent_state")
        if not isinstance(objects, dict) or not isinstance(career, dict) or not isinstance(agent_state, dict):
            return False
        player_star_id = career.get("level_two_player_star_id")
        player_ship_id = career.get("level_two_player_ship_id")
        enemy_ship_id = career.get("level_two_enemy_ship_id")
        enemy_home_id = career.get("level_two_enemy_home_star_id")
        cluster_target_id = career.get("level_two_cluster_target_id")
        player_star, player_ship = objects.get(player_star_id), objects.get(player_ship_id)
        enemy_ship, enemy_home, cluster_target = objects.get(enemy_ship_id), objects.get(enemy_home_id), objects.get(cluster_target_id)
        changed = False
        player_detected = False

        # The avoidant ship only leaves its staging star when its own radar
        # detects the player home/ship. It then uses the same transfer planner
        # as a human command.
        if isinstance(enemy_ship, dict) and isinstance(player_star, dict) and isinstance(enemy_ship_id, str) and isinstance(player_star_id, str):
            source_position = position_for_object_at_time(enemy_ship, objects, current_time)
            player_position = position_for_object_at_time(player_ship, objects, current_time) if isinstance(player_ship, dict) else None
            home_position = player_star.get("location")
            radar_radius = next((float(item.get("radius")) for item in (enemy_ship.get("objects") or {}).values() if isinstance(item, dict) and item.get("type") == "RADAR" and isinstance(item.get("radius"), (int, float))), 0.0)
            player_detected = source_position is not None and any(
                isinstance(position, dict) and math.hypot(float(position["x"]) - source_position["x"], float(position["y"]) - source_position["y"]) <= radar_radius
                for position in (home_position, player_position)
            )
            agent = agent_state.get("agent_level_2_avoidant")
            if player_detected and isinstance(agent, dict) and agent.get("mode") == "ORBITING":
                def transfer(current):
                    if not isinstance(current, dict): return current
                    try:
                        plan = build_transfer_plan(current, enemy_ship_id, player_star_id, 150.0, now=current_time)
                        apply_transfer_plan(current, plan)
                        current.setdefault("agent_state", {}).setdefault("agent_level_2_avoidant", {})["mode"] = "AVOIDING"
                    except TransferError:
                        pass
                    return current
                self.repository.transaction_universe(universe_id, transfer)
                return True

        # Star bombardment: 75 damage every 3 seconds yields about forty
        # seconds to destroy a 1,000-life cluster target.
        if isinstance(enemy_home, dict) and isinstance(cluster_target, dict) and isinstance(enemy_home_id, str) and isinstance(cluster_target_id, str):
            armed_at = career.get("level_two_enemy_home_armed_at")
            if isinstance(armed_at, (int, float)) and current_time >= float(armed_at):
                changed = self._maybe_agent_fire(universe_id, universe, enemy_home_id, cluster_target_id, "level_two_enemy_home_last_fire_at", current_time, now_ms) or changed

        # Once close enough, the avoidant ship shoots whichever player object
        # is nearer and inside its gun range.
        if player_detected and isinstance(enemy_ship, dict) and isinstance(enemy_ship_id, str):
            candidates = [(player_star_id, player_star), (player_ship_id, player_ship)]
            source = position_for_object_at_time(enemy_ship, objects, current_time)
            if source:
                visible = []
                for target_id, target in candidates:
                    position = position_for_object_at_time(target, objects, current_time) if isinstance(target, dict) else None
                    if isinstance(target_id, str) and position:
                        visible.append((math.hypot(position["x"] - source["x"], position["y"] - source["y"]), target_id))
                if visible:
                    _, target_id = min(visible)
                    changed = self._maybe_agent_fire(universe_id, universe, enemy_ship_id, target_id, "level_two_enemy_ship_last_fire_at", current_time, now_ms) or changed
        return changed

    def _maybe_agent_fire(self, universe_id: str, universe: dict, source_id: str, target_id: str, state_key: str, current_time: float, now_ms: float) -> bool:
        objects, career = universe.get("objects"), universe.get("career_state")
        source = objects.get(source_id) if isinstance(objects, dict) else None
        target = objects.get(target_id) if isinstance(objects, dict) else None
        if not isinstance(source, dict) or not isinstance(target, dict) or not isinstance(career, dict): return False
        gun_entry = next(((gid, item) for gid, item in (source.get("objects") or {}).items() if isinstance(gid, str) and isinstance(item, dict) and item.get("type") == "GUN"), None)
        source_position = position_for_object_at_time(source, objects, current_time)
        target_position = position_for_object_at_time(target, objects, current_time)
        if gun_entry is None or source_position is None or target_position is None: return False
        gun_id, gun = gun_entry
        cooldown = float(gun.get("cooldown_seconds", 1))
        if current_time - float(career.get(state_key, float("-inf"))) < cooldown: return False
        if math.hypot(target_position["x"] - source_position["x"], target_position["y"] - source_position["y"]) > float(gun.get("range", self.projectile_range)): return False
        rotation = math.degrees(math.atan2(target_position["y"] - source_position["y"], target_position["x"] - source_position["x"]))
        try:
            shot = prepare_shot(universe_id, universe, source_id, gun_id, rotation, projectile_range=self.projectile_range, projectile_blast_impact=self.projectile_blast_impact, projectile_retention_seconds=self.projectile_retention_seconds, client_fired_at=current_time, now_ms=now_ms)
        except ProjectileError:
            return False
        updates = dict(shot.updates)
        updates[f"universes/{universe_id}/career_state/{state_key}"] = shot.fired_at
        self.repository.atomic_update(updates)
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
