from __future__ import annotations

import time

from schema.models import Position, SpawnConfig, UniverseMembership, UniverseObject, UniverseRecord, UserRecord


def new_human_user(username: str, password_hash: str) -> UserRecord:
    return {
        "username": username,
        "password": password_hash,
        "type": "HUMAN",
        "registration_state": "COMPLETE",
        "career_universe": None,
        "universe_memberships": {},
    }


def new_pending_human_user() -> UserRecord:
    return {"username": None, "password": None, "type": "HUMAN", "registration_state": "PENDING", "career_universe": None, "universe_memberships": {}}


def new_agent_user(agent_name: str) -> UserRecord:
    return {"username": agent_name, "type": "AGENT", "registration_state": "COMPLETE", "career_universe": None, "universe_memberships": {}}


def new_empty_universe(spawn_config: SpawnConfig) -> UniverseRecord:
    return {
        "active": True,
        "time": 0,
        "time_updated_at_ms": time.time() * 1000,
        "objects": {},
        "spawn_config": spawn_config,
    }


def new_star(location: Position, life: float, border_radius: float) -> UniverseObject:
    return {
        "type": "NATURAL",
        "owner": None,
        "sub_type": "STAR",
        "life": float(life),
        "max_life": float(life),
        "border_radius": float(border_radius),
        "location": {"x": float(location["x"]), "y": float(location["y"])},
    }


def new_ship(location: Position, focus1: str, orbit_radius: float, phase: float, velocity: float, direction: int, owner: str, life: float, border_radius: float) -> UniverseObject:
    return {
        "type": "ARTIFICIAL",
        "owner": owner,
        "sub_type": "cruise_level_1",
        "life": float(life),
        "max_life": float(life),
        "border_radius": float(border_radius),
        "location": {"x": float(location["x"]), "y": float(location["y"])},
        "curves": {
            "0": {
                "type": "ELLIPSE",
                "motion_type": "ORBIT",
                "active": True,
                "dotted": False,
                "direction": direction,
                "eccentricity": 0,
                "focus1": focus1,
                "major_axis": orbit_radius,
                "rotation": 0,
                "phase": phase,
                "phase_updated_at": 0,
                "velocity": velocity,
                "valid_from": 0,
                "valid_till": -1,
            }
        },
        "objects": {},
    }


def new_gun(velocity: float, hit_radius: float) -> dict:
    return {"type": "GUN", "velocity": velocity, "hit_radius": hit_radius}


def new_radar(radius: float) -> dict:
    return {"type": "RADAR", "radius": radius}


def new_membership(star_id: str, ship_ids: list[str], onboarded_at: float, universe_type: str = "ARCADE") -> UniverseMembership:
    return {"onboarded": True, "star_id": star_id, "ship_ids": {str(index): ship_id for index, ship_id in enumerate(ship_ids)}, "onboarded_at": onboarded_at, "universe_type": "CAREER" if universe_type == "CAREER" else "ARCADE"}
