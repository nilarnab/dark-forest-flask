from __future__ import annotations

import math
from typing import Any

from simulation.movement import position_for_object_at_time


def verify_and_apply_collision(
    universe: dict[str, Any], first_id: str, second_id: str, hit_time: float, distance_tolerance: float = 0.01,
) -> dict[str, Any]:
    """Authoritatively verify one client-reported contact and apply its result.

    This deliberately examines only the supplied pair; it is not a background
    all-object collision scan.
    """
    if first_id == second_id:
        return {"status": "rejected", "reason": "Objects must be different."}
    objects = universe.get("objects")
    if not isinstance(objects, dict):
        return {"status": "rejected", "reason": "Universe has no objects."}
    first, second = objects.get(first_id), objects.get(second_id)
    if not isinstance(first, dict) or not isinstance(second, dict):
        return {"status": "rejected", "reason": "An object no longer exists."}
    if first.get("sub_type") == "PROJECTILE" or second.get("sub_type") == "PROJECTILE":
        return {"status": "rejected", "reason": "Projectile collisions use the projectile verifier."}
    if not isinstance(first.get("life"), (int, float)) or not isinstance(second.get("life"), (int, float)):
        return {"status": "rejected", "reason": "Both objects need numeric life."}
    radius = collision_radius(first, second)
    if radius is None:
        return {"status": "rejected", "reason": "Neither object has a collision radius."}
    first_position = position_for_object_at_time(first, objects, hit_time)
    second_position = position_for_object_at_time(second, objects, hit_time)
    if not first_position or not second_position:
        return {"status": "rejected", "reason": "Could not reconstruct both positions."}
    distance = math.hypot(first_position["x"] - second_position["x"], first_position["y"] - second_position["y"])
    if distance > radius + max(0.0, distance_tolerance):
        return {"status": "rejected", "reason": "Objects were outside collision range.", "distance": distance, "radius": radius}

    first_life, second_life = float(first["life"]), float(second["life"])
    damage = min(
        max(first_life, numeric_or_zero(first.get("blast_impact"))),
        max(second_life, numeric_or_zero(second.get("blast_impact"))),
    )
    first_after, second_after = max(0.0, first_life - damage), max(0.0, second_life - damage)
    first["life"], second["life"] = first_after, second_after
    events = universe.setdefault("events", {})
    if not isinstance(events, dict):
        events = {}
        universe["events"] = events
    events[f"collision_{first_id}_{second_id}_{round(hit_time * 1000)}"] = {
        "type": "OBJECT_COLLISION",
        "object_id": first_id,
        "other_object_id": second_id,
        "hit_time": hit_time,
        "location": first_position,
        "damage": damage,
    }
    if first_after <= 0:
        preserve_dead_star(objects, first_id)
    if second_after <= 0:
        preserve_dead_star(objects, second_id)
    return {
        "status": "confirmed",
        "distance": distance,
        "radius": radius,
        "damage": damage,
        "destroyed": [object_id for object_id, life in ((first_id, first_after), (second_id, second_after)) if life <= 0],
    }


def collision_radius(first: dict[str, Any], second: dict[str, Any]) -> float | None:
    radii = [
        float(value)
        for obj in (first, second)
        for value in (obj.get("border_radius"), obj.get("hit_radius"))
        if isinstance(value, (int, float)) and value > 0
    ]
    return max(radii) if radii else None


def numeric_or_zero(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def preserve_dead_star(objects: dict[str, Any], object_id: str) -> None:
    object_data = objects.get(object_id)
    if isinstance(object_data, dict) and object_data.get("sub_type") == "STAR":
        object_data["sub_type"] = "DEAD_STAR"
        object_data["life"] = 0.0
        return
    objects.pop(object_id, None)
