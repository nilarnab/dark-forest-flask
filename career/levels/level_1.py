from __future__ import annotations

import math
import random
import uuid

from career.config import CareerGenerationConfig
from schema.factories import new_empty_universe, new_membership, new_star
from schema.models import UniverseRecord
from simulation.transfer import apply_transfer_plan, build_transfer_plan
from simulation.movement import active_curve, curve_items, position_for_object_at_time
from simulation.orbit import phase_from_position
from universe_factory.config import UniverseGenerationConfig
from universe_factory.generator import create_ship, mount_gun, mount_radar, spawn_config


LEVEL_NUMBER = 1
AGENT_USER_ID = "agent_level_1"
AGENT_INSTANCE_ID = "agent_level_1_enemy"
ENEMY_CONTACT_HOLD_SECONDS = 1_000_000.0

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
    player_ship_id = create_ship(
        universe, player_star_id, config, rng, user_id,
        orbit_radius=career.level_one_player_orbit_radius,
        velocity=career.level_one_player_orbit_velocity,
        object_id=f"ship_player_{uuid.uuid4().hex}",
    )
    mount_gun(universe, player_ship_id, config.gun_velocity, config.gun_hit_radius, config.gun_range)
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
    mount_gun(universe, enemy_ship_id, config.gun_velocity, config.gun_hit_radius, config.gun_range)
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
    # Both ships orbit the player's star during first contact. Keep their
    # circular paths visibly and physically distinct.
    if destination_orbit_radius <= career.level_one_player_orbit_radius + 2 * config.ship_border_radius:
        raise ValueError("Level 1 enemy destination orbit must clear the player orbit.")
    transfer_plan = _level_one_immediate_transfer_plan(
        universe, enemy_ship_id, player_star_id, destination_orbit_radius,
    )
    apply_transfer_plan(universe, transfer_plan)
    _delay_enemy_maneuver(universe["objects"][enemy_ship_id], career.level_one_enemy_approach_delay_seconds)
    expected_contact_at = _first_radar_entry_time(
        universe, enemy_ship_id, player_star_id, career.level_one_radar_radius,
        transfer_plan.arrival_time + career.level_one_enemy_approach_delay_seconds,
    )
    # Do not let the enemy start moving while the player is still reading the
    # opening tutorial. The final “wait and see” transition releases this
    # exact schedule at the current simulation time.
    _delay_enemy_maneuver(universe["objects"][enemy_ship_id], ENEMY_CONTACT_HOLD_SECONDS)
    universe["career_state"].update({
        "enemy_contact_hold_seconds": ENEMY_CONTACT_HOLD_SECONDS,
        "enemy_contact_duration_seconds": expected_contact_at - career.level_one_enemy_approach_delay_seconds,
        # These are rewritten to the actual release time at the final
        # tutorial transition. Keeping an inert initial window preserves the
        # schema for observers that inspect a newly created universe.
        "enemy_contact_progress_starts_at": ENEMY_CONTACT_HOLD_SECONDS,
        "enemy_contact_expected_at": ENEMY_CONTACT_HOLD_SECONDS + expected_contact_at - career.level_one_enemy_approach_delay_seconds,
        "enemy_contact_released": False,
    })
    return universe_id, universe, new_membership(player_star_id, [player_ship_id], 0, universe_type="CAREER")


def _level_one_immediate_transfer_plan(
    universe: UniverseRecord, ship_id: str, target_star_id: str, target_radius: float,
):
    """Build the tutorial's straight transfer without an arbitrary orbit wait.

    Normal player transfers deliberately wait until the ship reaches the
    nearest compatible tangent.  For Level 1, that wait can be almost one
    full orbit and makes the contact progress bar feel stalled.  We first
    solve the exact same global tangent problem, place the authored enemy at
    that computed departure point, then solve once more.  The second plan has
    zero wait while retaining the same tangent straight-line mechanics.
    """
    now = float(universe.get("time", 0.0))
    initial_plan = build_transfer_plan(universe, ship_id, target_star_id, target_radius, now=now)
    departure = initial_plan.transfer_curve.get("start_location")
    ship = universe["objects"][ship_id]
    source_curve = ship.get("curves", {}).get(initial_plan.source_curve_key)
    focus_id = source_curve.get("focus1") if isinstance(source_curve, dict) else None
    focus = universe["objects"].get(focus_id) if isinstance(focus_id, str) else None
    focus_location = focus.get("location") if isinstance(focus, dict) else None
    if not isinstance(departure, dict) or not isinstance(source_curve, dict) or not isinstance(focus_location, dict):
        return initial_plan
    source_curve["phase"] = phase_from_position(departure, focus_location, source_curve)
    source_curve["phase_updated_at"] = now
    ship["location"] = {"x": float(departure["x"]), "y": float(departure["y"])}
    return build_transfer_plan(universe, ship_id, target_star_id, target_radius, now=now)


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


def release_level_one_enemy_contact(universe: UniverseRecord, current_time: float) -> None:
    """Release the held first-contact transfer at an exact simulation time."""
    career_state = universe.get("career_state")
    if not isinstance(career_state, dict) or career_state.get("enemy_contact_released") is True:
        return
    hold = career_state.get("enemy_contact_hold_seconds")
    duration = career_state.get("enemy_contact_duration_seconds")
    if not isinstance(hold, (int, float)) or not isinstance(duration, (int, float)):
        return
    objects = universe.get("objects")
    ship_id = career_state.get("enemy_contact_ship_id")
    ship = objects.get(ship_id) if isinstance(objects, dict) and isinstance(ship_id, str) else None
    if not isinstance(ship, dict):
        # `enemy_contact_ship_id` is only populated once the contact tutorial
        # fires, so find the authored Level 1 enemy before that point.
        ship = next((item for item in objects.values() if isinstance(item, dict) and item.get("owner") == AGENT_USER_ID and item.get("type") == "ARTIFICIAL" and item.get("sub_type") != "PROJECTILE"), None) if isinstance(objects, dict) else None
    if not isinstance(ship, dict):
        return
    shift = current_time - float(hold)
    curves = ship.get("curves")
    values = curves.values() if isinstance(curves, dict) else curves if isinstance(curves, list) else []
    for curve in values:
        if not isinstance(curve, dict):
            continue
        for field in ("valid_from", "phase_updated_at"):
            if isinstance(curve.get(field), (int, float)):
                curve[field] += shift
        if isinstance(curve.get("valid_till"), (int, float)) and curve["valid_till"] != -1:
            curve["valid_till"] += shift
    if isinstance(ship.get("maneuver_blocked_till"), (int, float)):
        ship["maneuver_blocked_till"] += shift
    career_state["enemy_contact_progress_starts_at"] = current_time
    career_state["enemy_contact_expected_at"] = current_time + max(0.0, float(duration))
    career_state["enemy_contact_released"] = True


def speed_up_level_one_player_transfer(universe: UniverseRecord, current_time: float, multiplier: float = 3.0) -> bool:
    """Accelerate only the Level 1 player's currently scheduled transfer.

    The tutorial deliberately shortens both the remaining source-orbit wait
    and the straight transit.  The destination orbit keeps its normal cruise
    velocity once the ship arrives.
    """
    if multiplier <= 1:
        return False
    objects = universe.get("objects")
    owner = universe.get("career_owner")
    if not isinstance(objects, dict) or not isinstance(owner, str):
        return False
    ship = next((item for item in objects.values() if isinstance(item, dict)
                 and item.get("owner") == owner and item.get("type") == "ARTIFICIAL"
                 and item.get("sub_type") != "PROJECTILE"), None)
    if not isinstance(ship, dict):
        return False
    curves = ship.get("curves")
    source_item = active_curve(curves, current_time)
    values = curve_items(curves)
    transfer_item = next(((key, curve) for key, curve in values
                          if curve.get("type") == "STRAIGHT_LINE"
                          and isinstance(curve.get("valid_from"), (int, float))
                          and isinstance(curve.get("valid_till"), (int, float))
                          and float(curve["valid_from"]) >= current_time - 1e-7), None)
    if source_item is None or transfer_item is None:
        return False
    _, source_curve = source_item
    _, transfer_curve = transfer_item
    start_location = transfer_curve.get("start_location")
    focus = objects.get(source_curve.get("focus1"))
    focus_location = focus.get("location") if isinstance(focus, dict) else None
    current_position = position_for_object_at_time(ship, objects, current_time)
    if not all(isinstance(value, dict) for value in (start_location, focus_location, current_position)):
        return False
    try:
        radius = float(source_curve["major_axis"])
        source_velocity = float(source_curve["velocity"])
        transfer_velocity = float(transfer_curve["velocity"])
        line_length = float(transfer_curve["arc_length"])
        if min(radius, source_velocity, transfer_velocity, line_length) <= 0:
            return False
        current_phase = phase_from_position(current_position, focus_location, source_curve)
        departure_phase = phase_from_position(start_location, focus_location, source_curve)
        direction = 1 if float(source_curve.get("direction", 1)) >= 0 else -1
        travelled_angle = ((departure_phase - current_phase) % math.tau) if direction > 0 else ((current_phase - departure_phase) % math.tau)
    except (KeyError, TypeError, ValueError):
        return False

    boosted_source_velocity = source_velocity * multiplier
    boosted_transfer_velocity = transfer_velocity * multiplier
    departure_time = current_time + radius * travelled_angle / boosted_source_velocity
    arrival_time = departure_time + line_length / boosted_transfer_velocity
    source_curve["phase"] = current_phase
    source_curve["phase_updated_at"] = current_time
    source_curve["velocity"] = boosted_source_velocity
    source_curve["valid_till"] = departure_time
    transfer_curve["velocity"] = boosted_transfer_velocity
    transfer_curve["valid_from"] = departure_time
    transfer_curve["valid_till"] = arrival_time
    for _, curve in values:
        if curve.get("motion_type") == "ORBIT" and curve.get("focus1") == transfer_curve.get("target_object_id") and curve.get("dotted") is True:
            curve["valid_from"] = arrival_time
            curve["phase_updated_at"] = arrival_time
            break
    ship["maneuver_blocked_till"] = arrival_time
    career_state = universe.setdefault("career_state", {})
    if isinstance(career_state, dict):
        career_state["tutorial_transfer_speed_multiplier"] = multiplier
        career_state["tutorial_transfer_speeding"] = True
    return True


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
