from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from simulation.clock import simulation_time
from simulation.movement import position_for_object_at_time
from simulation.projectile import ProjectileError, build_projectile


@dataclass(frozen=True)
class PreparedShot:
    projectile_id: str
    fired_at: float
    updates: dict[str, Any]


def prepare_shot(
    universe_id: str,
    universe: dict[str, Any] | None,
    object_id: str,
    gun_id: str,
    rotation: float,
    *,
    projectile_range: float,
    projectile_blast_impact: float,
    projectile_retention_seconds: float,
    client_fired_at: float | None = None,
    client_fire_time_tolerance_seconds: float = 0,
    now_ms: float | None = None,
) -> PreparedShot:
    """Validate and build the exact Firebase update used for every shot."""
    if not isinstance(universe, dict) or not isinstance(universe.get("objects"), dict):
        raise ProjectileError("Universe does not exist.")
    ship = universe["objects"].get(object_id)
    if not isinstance(ship, dict) or ship.get("type") != "ARTIFICIAL":
        raise ProjectileError("objectid must identify an ARTIFICIAL firing object.")
    attachments = ship.get("objects")
    gun = attachments.get(gun_id) if isinstance(attachments, dict) else None
    if not isinstance(gun, dict) or gun.get("type") != "GUN":
        raise ProjectileError("gun_id must identify an attached GUN.")
    velocity, hit_radius = gun.get("velocity"), gun.get("hit_radius")
    if not isinstance(velocity, (int, float)) or velocity <= 0:
        raise ProjectileError("The selected GUN needs a positive numeric velocity.")
    if not isinstance(hit_radius, (int, float)) or hit_radius <= 0:
        raise ProjectileError("The selected GUN needs a positive numeric hit_radius.")

    resolved_now_ms = time.time() * 1000 if now_ms is None else now_ms
    if not isinstance(universe.get("time_updated_at_ms"), (int, float)):
        universe["time_updated_at_ms"] = resolved_now_ms
    server_time = simulation_time(universe, resolved_now_ms)
    fired_at = server_time if client_fired_at is None else float(client_fired_at)
    tolerance = max(0.0, client_fire_time_tolerance_seconds)
    if abs(fired_at - server_time) > tolerance:
        raise ProjectileError(
            f"CLIENT TIME REJECTED: supplied time differs from Flask by more than {tolerance:g}s."
        )
    if fired_at < float(universe.get("time", 0)):
        raise ProjectileError("CLIENT TIME REJECTED: supplied time predates the authoritative universe state.")

    firing_ship = dict(ship)
    firing_position = position_for_object_at_time(ship, universe["objects"], fired_at)
    if firing_position is not None:
        firing_ship["location"] = firing_position
    projectile_id = f"projectile_{uuid.uuid4().hex}"
    projectile = build_projectile(
        firing_ship, fired_at, rotation, float(velocity), projectile_range,
        source_objectid=object_id, hit_radius=float(hit_radius),
        blast_impact=projectile_blast_impact,
        retention_seconds=projectile_retention_seconds,
    )
    fire_event = {
        "type": "PROJECTILE_FIRED",
        "projectile_id": projectile_id,
        "source_id": object_id,
        "occurred_at": fired_at,
        "start_location": projectile["location"],
        "rotation": float(rotation),
        "velocity": float(velocity),
        "hit_radius": float(hit_radius),
        "range": projectile_range,
    }
    return PreparedShot(
        projectile_id=projectile_id,
        fired_at=fired_at,
        updates={
            f"universes/{universe_id}/objects/{projectile_id}": projectile,
            f"universes/{universe_id}/events/fire_{projectile_id}": fire_event,
            f"universes/{universe_id}/time": server_time,
            f"universes/{universe_id}/time_updated_at_ms": resolved_now_ms,
        },
    )
