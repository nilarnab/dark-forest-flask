from __future__ import annotations

import math
import random
import uuid

from career.config import CareerGenerationConfig
from schema.factories import new_empty_universe, new_membership, new_star
from schema.models import UniverseRecord
from simulation.transfer import apply_transfer_plan, build_transfer_plan
from simulation.movement import position_for_object_at_time
from universe_factory.config import UniverseGenerationConfig
from universe_factory.generator import create_ship, mount_gun, mount_radar, spawn_config


LEVEL_NUMBER = 1
AGENT_USER_ID = "agent_level_1"
AGENT_INSTANCE_ID = "agent_level_1_enemy"

# Level 1 is deliberately authored, not procedurally generated.  Multipliers
# are relative to AVG_DIST (`star_distance_target`) so the scene scales as a
# whole if that single universe setting changes.
LEVEL_ONE_NEUTRAL_STAR_OFFSETS = (
    (0.0, 2.0),
    (-1.5, 1.5),
    (-1.5, -1.5),
)


def create_level_one_universe(user_id: str, config: UniverseGenerationConfig, career: CareerGenerationConfig, seed: int | None = None) -> tuple[str, UniverseRecord, dict]:
    """Create the first personal Dark Forest encounter."""
    rng = random.Random(seed)
    universe_id = str(rng.randrange(1000, 10_000))
    universe = new_empty_universe(spawn_config(config))
    universe.update({
        "name": f"GUEST_{universe_id}",
        "career": True,
        "career_owner": user_id,
        "darkforest": True,
        "career_level": LEVEL_NUMBER,
        "career_state": {"current_step": "tutorial_1", "status": "ACTIVE", "tutorial_step": 0},
        "participants": {user_id: {"type": "HUMAN"}, AGENT_USER_ID: {"type": "AGENT"}},
        "agent_state": {AGENT_INSTANCE_ID: {"agent_name": AGENT_USER_ID, "active": False, "mode": "DORMANT", "ship_id": ""}},
    })
    # The opening tutorial controls when this personal universe begins.
    universe["active"] = False
    objects = universe["objects"]
    player_star_id = f"star_player_{uuid.uuid4().hex}"
    objects[player_star_id] = new_star({"x": 0.0, "y": 0.0}, config.star_life, config.star_border_radius)
    objects[player_star_id]["owner"] = user_id
    objects[player_star_id]["objects"] = {f"radar_{uuid.uuid4().hex}": {"type": "RADAR", "radius": career.level_one_radar_radius}}
    player_ship_id = create_ship(universe, player_star_id, config, rng, user_id, orbit_radius=career.level_one_player_orbit_radius, object_id=f"ship_player_{uuid.uuid4().hex}")
    mount_gun(universe, player_ship_id, config.gun_velocity, config.gun_hit_radius)
    mount_radar(universe, player_ship_id, career.level_one_radar_radius / 2)

    # Keep the enemy home star just outside the initial radar field. At the
    # opening cruise speed this places first radar contact ~3 seconds after
    # the observation lesson begins, while retaining a visible home system.
    enemy_distance = config.star_distance_target * career.level_one_enemy_star_distance_multiplier
    if enemy_distance <= career.level_one_near_miss_distance:
        raise ValueError("Level 1 enemy star must be farther away than the near-miss distance.")
    enemy_star_id = f"star_enemy_{uuid.uuid4().hex}"
    objects[enemy_star_id] = new_star({"x": enemy_distance, "y": 0.0}, config.star_life, config.star_border_radius)
    objects[enemy_star_id]["owner"] = AGENT_USER_ID
    # The enemy ship stays on the distant home star until its scheduled
    # transfer, rather than beginning inside the player's local orbit.
    enemy_ship_id = create_ship(
        universe, enemy_star_id, config, rng, AGENT_USER_ID,
        orbit_radius=min(career.level_one_enemy_orbit_radius, enemy_distance - career.level_one_near_miss_distance),
        object_id=f"ship_enemy_{uuid.uuid4().hex}", phase=math.pi,
        velocity=career.level_one_enemy_orbit_velocity,
    )
    mount_gun(universe, enemy_ship_id, config.gun_velocity, config.gun_hit_radius)
    mount_radar(universe, enemy_ship_id, career.level_one_radar_radius / 2)
    universe["agent_state"][AGENT_INSTANCE_ID]["ship_id"] = enemy_ship_id
    ensure_level_one_star_count(universe, config, career)
    ensure_level_one_ship_radars(universe, career)

    # Level 1's first contact is an incoming maneuver: the enemy begins on
    # its nearby star, waits for the tangent departure point, then transfers
    # into a compact orbit around the player's assigned star.
    # The first-contact ship settles into a deliberately wider orbit around
    # the player's star, making the hostile arrival legible at a glance.
    destination_orbit_radius = career.level_one_player_orbit_radius * 1.5
    transfer_plan = build_transfer_plan(
        universe,
        enemy_ship_id,
        player_star_id,
        destination_orbit_radius,
        now=float(universe.get("time", 0.0)),
    )
    apply_transfer_plan(universe, transfer_plan)
    _delay_enemy_maneuver(universe["objects"][enemy_ship_id], career.level_one_enemy_approach_delay_seconds)
    universe["career_state"]["enemy_contact_progress_starts_at"] = career.level_one_enemy_approach_delay_seconds
    universe["career_state"]["enemy_contact_expected_at"] = _first_radar_entry_time(
        universe, enemy_ship_id, player_star_id, career.level_one_radar_radius,
        transfer_plan.arrival_time + career.level_one_enemy_approach_delay_seconds,
    )
    return universe_id, universe, new_membership(player_star_id, [player_ship_id], 0, universe_type="CAREER")


def _first_radar_entry_time(universe: UniverseRecord, ship_id: str, target_star_id: str, radar_radius: float, horizon: float) -> float:
    """Return the first analytic time the incoming ship crosses the radar edge."""
    objects = universe["objects"]
    ship = objects[ship_id]
    target_location = objects[target_star_id]["location"]

    def distance_at(simulation_time: float) -> float:
        position = position_for_object_at_time(ship, objects, simulation_time)
        if position is None:
            return float("inf")
        return math.hypot(position["x"] - target_location["x"], position["y"] - target_location["y"])

    previous_time = 0.0
    previous_distance = distance_at(previous_time)
    samples = max(1, math.ceil(max(horizon, 1.0) * 20))
    for index in range(1, samples + 1):
        candidate_time = horizon * index / samples
        candidate_distance = distance_at(candidate_time)
        if candidate_distance <= radar_radius < previous_distance:
            low, high = previous_time, candidate_time
            for _ in range(24):
                middle = (low + high) / 2
                if distance_at(middle) <= radar_radius:
                    high = middle
                else:
                    low = middle
            return high
        previous_time, previous_distance = candidate_time, candidate_distance
    return horizon


def _delay_enemy_maneuver(ship: dict, delay_seconds: float) -> None:
    """Hold the authored enemy motion until the opening tutorial has run."""
    for curve in ship.get("curves", {}).values():
        if not isinstance(curve, dict):
            continue
        for field in ("valid_from", "phase_updated_at"):
            if isinstance(curve.get(field), (int, float)):
                curve[field] += delay_seconds
        if isinstance(curve.get("valid_till"), (int, float)) and curve["valid_till"] != -1:
            curve["valid_till"] += delay_seconds
    if isinstance(ship.get("maneuver_blocked_till"), (int, float)):
        ship["maneuver_blocked_till"] += delay_seconds


def ensure_level_one_star_count(universe: UniverseRecord, config: UniverseGenerationConfig, career: CareerGenerationConfig) -> None:
    """Top up an existing Level 1 universe to its configured star count."""
    objects = universe.get("objects")
    if not isinstance(objects, dict):
        return
    natural_count = sum(1 for object_data in objects.values() if isinstance(object_data, dict) and object_data.get("type") == "NATURAL")
    missing = max(0, career.level_one_star_count - natural_count)
    # Neutral stars are intentionally ownerless. Their authored offsets make
    # the whole Level 1 star field deterministic rather than procedural.
    player_star = next(
        (object_data for object_data in objects.values()
         if isinstance(object_data, dict) and object_data.get("type") == "NATURAL" and object_data.get("owner") not in {None, AGENT_USER_ID}),
        None,
    )
    player_location = player_star.get("location") if isinstance(player_star, dict) else None
    origin_x = float(player_location.get("x", 0.0)) if isinstance(player_location, dict) else 0.0
    origin_y = float(player_location.get("y", 0.0)) if isinstance(player_location, dict) else 0.0
    for index in range(missing):
        offset_x, offset_y = LEVEL_ONE_NEUTRAL_STAR_OFFSETS[(natural_count - 2 + index) % len(LEVEL_ONE_NEUTRAL_STAR_OFFSETS)]
        objects[f"star_neutral_{uuid.uuid4().hex}"] = new_star(
            {"x": origin_x + offset_x * config.star_distance_target, "y": origin_y + offset_y * config.star_distance_target},
            config.star_life,
            config.star_border_radius,
        )


def ensure_level_one_ship_radars(universe: UniverseRecord, career: CareerGenerationConfig) -> None:
    """Add the half-range radar to legacy Level 1 ships once, if missing."""
    objects = universe.get("objects")
    if not isinstance(objects, dict):
        return
    for ship_id, object_data in objects.items():
        if not isinstance(object_data, dict) or object_data.get("type") != "ARTIFICIAL" or object_data.get("sub_type") == "PROJECTILE":
            continue
        attachments = object_data.get("objects")
        if isinstance(attachments, dict) and any(isinstance(attachment, dict) and attachment.get("type") == "RADAR" for attachment in attachments.values()):
            continue
        mount_radar(universe, ship_id, career.level_one_radar_radius / 2)
