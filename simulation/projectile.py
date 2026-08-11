from __future__ import annotations

import math
from typing import Any


class ProjectileError(ValueError):
    pass


def build_projectile(
    ship: dict[str, Any],
    universe_time: float,
    rotation: Any,
    speed: float,
    maximum_range: float,
    source_objectid: str | None = None,
    hit_radius: float = 10,
    blast_impact: float = 0,
    retention_seconds: float = 10,
) -> dict[str, Any]:
    location = ship.get("location")
    if not isinstance(location, dict) or not isinstance(location.get("x"), (int, float)) or not isinstance(location.get("y"), (int, float)):
        raise ProjectileError("The firing object needs a valid location.")
    try:
        angle = float(rotation)
    except (TypeError, ValueError) as error:
        raise ProjectileError("rotation must be a number in degrees.") from error
    if speed <= 0 or maximum_range <= 0 or hit_radius <= 0 or blast_impact < 0:
        raise ProjectileError("Projectile speed, range, and hit radius must be positive; blast impact cannot be negative.")
    direction = {"x": math.cos(math.radians(angle)), "y": math.sin(math.radians(angle))}
    start = {"x": float(location["x"]), "y": float(location["y"])}
    valid_till = universe_time + maximum_range / speed
    projectile = {
        "type": "ARTIFICIAL",
        "owner": ship.get("owner"),
        "sub_type": "PROJECTILE",
        "life": 0,
        "max_life": 0,
        "blast_impact": float(blast_impact),
        "hit_radius": hit_radius,
        "delete_at": valid_till + max(0, retention_seconds),
        "location": start,
        "curves": {
            "0": {
                "type": "STRAIGHT_LINE",
                "active": True,
                "rotation": angle,
                "direction_vector": direction,
                "start_location": start,
                "velocity": speed,
                "valid_from": universe_time,
                "valid_till": valid_till,
            }
        },
    }
    if source_objectid:
        projectile["source_objectid"] = source_objectid
    return projectile
