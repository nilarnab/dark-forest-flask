from __future__ import annotations

import math
from typing import Any

from simulation.clock import simulation_time
from simulation.collision import preserve_dead_star
from simulation.movement import curve_items, next_position_for_object, position_for_object_at_time


def updates_for_universe(universe_id: str, universe: dict[str, Any], tick_seconds: float, now_ms: float | None = None) -> dict[str, Any]:
    """Compute every change from one immutable Firebase universe snapshot."""
    objects = universe.get("objects")
    if not isinstance(objects, dict):
        objects = {}
    current_time = float(universe.get("time", 0))
    continuous_time = simulation_time(universe, now_ms) if now_ms is not None else current_time
    end_time = max(current_time + tick_seconds, continuous_time)
    elapsed = end_time - current_time
    updates: dict[str, Any] = {f"universes/{universe_id}/time": end_time}
    if now_ms is not None:
        updates[f"universes/{universe_id}/time_updated_at_ms"] = now_ms

    for object_id, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        base = f"universes/{universe_id}/objects/{object_id}"
        if obj.get("sub_type") == "PROJECTILE":
            # Projectile lifecycle belongs to the fast processing worker.
            continue
        result = next_position_for_object(obj, objects, current_time, elapsed)
        if result is None:
            continue
        position, curve_updates = result
        updates[f"{base}/location"] = position
        current_curve_key = curve_updates[-1][0]
        expired_curve_keys = {
            curve_key
            for curve_key, curve in curve_items(obj.get("curves"))
            if curve_key != current_curve_key
            and curve.get("valid_till", -1) != -1
            and float(curve["valid_till"]) <= end_time
        }
        for curve_key, phase, phase_time in curve_updates:
            if curve_key in expired_curve_keys:
                continue
            updates[f"{base}/curves/{curve_key}/phase"] = phase
            updates[f"{base}/curves/{curve_key}/phase_updated_at"] = phase_time
        for curve_key in expired_curve_keys:
            # In a Firebase array this leaves a null slot; in a map it removes
            # the key. Both are intentionally ignored by the reader/UI.
            updates[f"{base}/curves/{curve_key}"] = None
        blocked_till = obj.get("maneuver_blocked_till")
        if isinstance(blocked_till, (int, float)) and blocked_till <= end_time:
            updates[f"{base}/maneuver_blocked_till"] = None

        # Keep scheduled future curves active so the client can render their
        # dotted planned orbit. valid_from still prevents early movement.
        for curve_key, curve in curve_items(obj.get("curves")):
            if curve_key in expired_curve_keys:
                continue
            active = bool(curve.get("active", False))
            if curve_key == current_curve_key:
                active = True
            valid_till = curve.get("valid_till", -1)
            if bool(curve.get("active", False)) != active:
                updates[f"{base}/curves/{curve_key}/active"] = active
            if curve_key == current_curve_key and curve.get("dotted"):
                updates[f"{base}/curves/{curve_key}/dotted"] = False
    return updates


def apply_projectile_processing(universe: dict[str, Any], start_time: float, end_time: float, hit_distance_tolerance: float = 0.01) -> bool:
    """Apply authoritative projectile collisions/expiry within one transaction."""
    objects = universe.get("objects")
    if not isinstance(objects, dict) or end_time <= start_time:
        return False
    events = universe.setdefault("events", {})
    if not isinstance(events, dict):
        events = {}
        universe["events"] = events
    outcomes = universe.setdefault("recent_projectile_outcomes", {})
    if not isinstance(outcomes, dict):
        outcomes = {}
        universe["recent_projectile_outcomes"] = outcomes
    changed = False
    for projectile_id, projectile in list(objects.items()):
        if not isinstance(projectile, dict) or projectile.get("sub_type") != "PROJECTILE":
            continue
        hit = projectile_hit(projectile, projectile_id, objects, start_time, end_time, hit_distance_tolerance)
        if hit:
            target_id, hit_time, position = hit
            target = objects.get(target_id)
            impact = projectile.get("blast_impact")
            life_before = target.get("life") if isinstance(target, dict) else None
            life_after = None
            if isinstance(target, dict) and isinstance(life_before, (int, float)) and isinstance(impact, (int, float)):
                life_after = max(0.0, float(life_before) - max(0.0, float(impact)))
                target["life"] = life_after
            objects.pop(projectile_id, None)
            if life_after is not None and life_after <= 0:
                preserve_dead_star(objects, target_id)
            event = {
                "type": "PROJECTILE_HIT",
                "projectile_id": projectile_id,
                "target_id": target_id,
                "hit_time": hit_time,
                "location": position,
            }
            if isinstance(impact, (int, float)):
                event["blast_impact"] = float(impact)
            if isinstance(life_before, (int, float)):
                event["life_before"] = float(life_before)
            if life_after is not None:
                event["life_after"] = life_after
            events[f"hit_{projectile_id}_{round(hit_time * 1000)}"] = event
            outcomes[projectile_id] = {
                "status": "HIT",
                "target_id": target_id,
                "hit_time": hit_time,
                "recorded_at": end_time,
            }
            changed = True
    trim_projectile_outcomes(outcomes)
    return changed


def apply_projectile_cleanup(universe: dict[str, Any], current_time: float, hit_event_retention_seconds: float = 10) -> bool:
    """Prune retained projectiles and old transient hit events."""
    objects = universe.get("objects")
    if not isinstance(objects, dict):
        return False
    outcomes = universe.setdefault("recent_projectile_outcomes", {})
    if not isinstance(outcomes, dict):
        outcomes = {}
        universe["recent_projectile_outcomes"] = outcomes
    changed = False
    for projectile_id, projectile in list(objects.items()):
        if not isinstance(projectile, dict) or projectile.get("sub_type") != "PROJECTILE":
            continue
        delete_at = projectile.get("delete_at")
        if not isinstance(delete_at, (int, float)) or delete_at > current_time:
            continue
        objects.pop(projectile_id, None)
        outcomes[projectile_id] = {"status": "EXPIRED", "recorded_at": current_time}
        changed = True
    events = universe.get("events")
    if isinstance(events, dict):
        for event_id, event in list(events.items()):
            if not isinstance(event, dict) or event.get("type") not in {
                "PROJECTILE_HIT", "OBJECT_COLLISION", "PROJECTILE_FIRED", "TRANSFER_SCHEDULED",
            }:
                continue
            event_time = event.get("hit_time", event.get("occurred_at"))
            if isinstance(event_time, (int, float)) and current_time >= event_time + max(0, hit_event_retention_seconds):
                events.pop(event_id, None)
                changed = True
    trim_projectile_outcomes(outcomes)
    return changed


def trim_projectile_outcomes(outcomes: dict[str, Any], limit: int = 10) -> None:
    ordered = sorted(
        ((key, value) for key, value in outcomes.items() if isinstance(value, dict)),
        key=lambda item: float(item[1].get("recorded_at", 0)),
        reverse=True,
    )
    for key, _ in ordered[limit:]:
        outcomes.pop(key, None)


def projectile_expires_this_tick(obj: dict[str, Any], end_time: float) -> bool:
    if obj.get("type") != "ARTIFICIAL":
        return False
    for _, curve in curve_items(obj.get("curves")):
        if curve.get("type") == "STRAIGHT_LINE" and curve.get("valid_till", -1) != -1:
            return float(curve["valid_till"]) <= end_time
    return False


def projectile_hit(
    projectile: dict[str, Any],
    projectile_id: str,
    objects: dict[str, Any],
    start_time: float,
    end_time: float,
    hit_distance_tolerance: float = 0.01,
) -> tuple[str, float, dict[str, float]] | None:
    """Find the first target hit by a projectile during this tick interval."""
    curve = next((curve for _, curve in curve_items(projectile.get("curves")) if curve.get("type") == "STRAIGHT_LINE"), None)
    if not curve:
        return None
    valid_from = float(curve.get("valid_from", start_time))
    valid_till = float(curve.get("valid_till", -1))
    interval_start = max(start_time, valid_from)
    interval_end = end_time if valid_till == -1 else min(end_time, valid_till)
    if interval_end <= interval_start:
        return None
    projectile_start = straight_line_position(curve, interval_start)
    projectile_end = straight_line_position(curve, interval_end)
    if not projectile_start or not projectile_end:
        return None

    earliest: tuple[str, float, dict[str, float]] | None = None
    source_id = projectile.get("source_objectid")
    hit_radius = projectile.get("hit_radius")
    if not isinstance(hit_radius, (int, float)) or hit_radius <= 0:
        return None
    for target_id, target in objects.items():
        if target_id in {projectile_id, source_id} or not isinstance(target, dict) or target.get("sub_type") == "PROJECTILE":
            continue
        # In event-driven mode locations are spawn/checkpoint values. Rebuild
        # both ends of the collision interval from the analytic curve instead
        # of advancing from a stale checkpoint phase.
        start_location = position_for_object_at_time(target, objects, interval_start) or location(target)
        if not start_location:
            continue
        target_end = position_for_object_at_time(target, objects, interval_end) or start_location
        intersection = swept_circle_intersection(
            projectile_start, projectile_end, start_location, target_end,
            float(hit_radius) + max(0.0, hit_distance_tolerance),
        )
        if intersection is None:
            continue
        fraction = intersection
        hit_time = interval_start + (interval_end - interval_start) * fraction
        hit_position = {
            "x": projectile_start["x"] + (projectile_end["x"] - projectile_start["x"]) * fraction,
            "y": projectile_start["y"] + (projectile_end["y"] - projectile_start["y"]) * fraction,
        }
        if earliest is None or hit_time < earliest[1]:
            earliest = (target_id, hit_time, hit_position)
    return earliest


def straight_line_position(curve: dict[str, Any], time_value: float) -> dict[str, float] | None:
    start = curve.get("start_location")
    vector = curve.get("direction_vector")
    if not isinstance(start, dict) or not isinstance(vector, dict):
        return None
    try:
        start_x, start_y = float(start["x"]), float(start["y"])
        vector_x, vector_y = float(vector["x"]), float(vector["y"])
        length = math.hypot(vector_x, vector_y)
        if length == 0:
            return None
        distance = float(curve.get("velocity", 0)) * max(0, time_value - float(curve.get("valid_from", time_value)))
    except (KeyError, TypeError, ValueError):
        return None
    return {"x": start_x + vector_x / length * distance, "y": start_y + vector_y / length * distance}


def swept_circle_intersection(
    projectile_start: dict[str, float],
    projectile_end: dict[str, float],
    target_start: dict[str, float],
    target_end: dict[str, float],
    radius: float,
) -> float | None:
    """Earliest t in [0, 1] where a moving point reaches a moving circle."""
    relative_start_x = projectile_start["x"] - target_start["x"]
    relative_start_y = projectile_start["y"] - target_start["y"]
    relative_velocity_x = (projectile_end["x"] - projectile_start["x"]) - (target_end["x"] - target_start["x"])
    relative_velocity_y = (projectile_end["y"] - projectile_start["y"]) - (target_end["y"] - target_start["y"])
    quadratic_a = relative_velocity_x ** 2 + relative_velocity_y ** 2
    quadratic_b = 2 * (relative_start_x * relative_velocity_x + relative_start_y * relative_velocity_y)
    quadratic_c = relative_start_x ** 2 + relative_start_y ** 2 - radius ** 2
    if quadratic_c <= 0:
        return 0.0
    if quadratic_a <= 1e-12:
        return None
    discriminant = quadratic_b ** 2 - 4 * quadratic_a * quadratic_c
    if discriminant < 0:
        return None
    hit = (-quadratic_b - math.sqrt(discriminant)) / (2 * quadratic_a)
    return hit if 0 <= hit <= 1 else None


def location(obj: dict[str, Any]) -> dict[str, float] | None:
    value = obj.get("location")
    if not isinstance(value, dict):
        return None
    try:
        return {"x": float(value["x"]), "y": float(value["y"])}
    except (KeyError, TypeError, ValueError):
        return None
