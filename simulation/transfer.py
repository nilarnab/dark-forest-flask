from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from simulation.collision import collision_radius
from simulation.movement import active_curve, curve_items, location_of, position_for_object_at_time
from simulation.orbit import basis_ellipse_position, ellipse_position, half_ellipse_arc_length, phase_from_position, semi_minor_axis


class TransferError(ValueError):
    pass


class ManeuverBlockedError(TransferError):
    pass


@dataclass(frozen=True)
class TransferPlan:
    object_id: str
    source_curve_key: str
    transfer_curve_key: str
    destination_curve_key: str
    start_time: float
    arrival_time: float
    transfer_curve: dict[str, Any]
    destination_curve: dict[str, Any]


def _next_curve_keys(curves: Any) -> tuple[str, str]:
    transfer_key = _next_curve_key(curves)
    return transfer_key, str(int(transfer_key) + 1)


def _hohmann_plan(
    universe: dict[str, Any], object_id: str, target_id: str, target_radius: float,
    source_key: str, source_curve: dict[str, Any], departure: dict[str, Any], focus_location: dict[str, Any], velocity: float, now: float,
) -> TransferPlan:
    """Direct, same-primary transfer between two circular orbits."""
    r1 = _number(source_curve.get("major_axis"))
    if r1 <= 0 or math.isclose(r1, target_radius, rel_tol=0, abs_tol=1e-7):
        raise TransferError("radnew must be a positive radius different from the current orbit radius.")
    direction = 1.0 if _number(source_curve.get("direction", 1)) > 0 else -1.0
    departure_angle = math.atan2(_number(departure.get("y")) - _number(focus_location.get("y")), _number(departure.get("x")) - _number(focus_location.get("x")))
    a = (r1 + target_radius) / 2
    eccentricity = abs(target_radius - r1) / (r1 + target_radius)
    b = semi_minor_axis(a, eccentricity)
    outward = target_radius > r1
    # A Hohmann ellipse begins at periapsis when expanding and apoapsis when
    # contracting. Rotate it so that its first point is the ship's location.
    phase_start = 0.0 if outward else math.pi
    rotation = math.degrees(departure_angle if outward else departure_angle - math.pi)
    arrival_angle = (departure_angle + math.pi) % math.tau
    arrival = {
        "x": _number(focus_location.get("x")) + target_radius * math.cos(arrival_angle),
        "y": _number(focus_location.get("y")) + target_radius * math.sin(arrival_angle),
    }
    arrival_time = now + half_ellipse_arc_length(a, b) / velocity
    transfer_key, destination_key = _next_curve_keys(universe["objects"][object_id].get("curves"))
    transfer_curve = {
        "active": True,
        "type": "ELLIPSE",
        "motion_type": "HOHMANN_TRANSFER",
        "focus1": target_id,
        "major_axis": a,
        "eccentricity": eccentricity,
        "rotation": rotation,
        "velocity": velocity,
        "direction": direction,
        "phase": phase_start,
        "phase_start": phase_start,
        "phase_end": phase_start + direction * math.pi,
        "phase_updated_at": now,
        "valid_from": now,
        "valid_till": arrival_time,
        "arrival_location": arrival,
        "arc_length": half_ellipse_arc_length(a, b),
    }
    destination_curve = {
        "active": True,
        "motion_type": "ORBIT",
        "focus1": target_id,
        "major_axis": target_radius,
        "eccentricity": 0,
        "rotation": 0,
        "velocity": velocity,
        # A real Hohmann transfer preserves tangential travel direction.
        "direction": direction,
        "phase": arrival_angle,
        "phase_updated_at": arrival_time,
        "valid_from": arrival_time,
        "valid_till": -1,
        "dotted": True,
    }
    plan = TransferPlan(object_id, source_key, transfer_key, destination_key, now, arrival_time, transfer_curve, destination_curve)
    _validate_transfer_clearance(universe, plan)
    return plan


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise TransferError("A required movement value is not a number.") from exc


def _next_curve_key(curves: Any) -> str:
    keys = [int(key) for key, _ in curve_items(curves) if key.isdigit()]
    return str(max(keys, default=-1) + 1)


def _arc_length(basis_u: dict[str, float], basis_v: dict[str, float], samples: int = 120) -> float:
    """Length of the tangent-preserving quarter-ellipse, phase 0 → pi/2."""
    step = (math.pi / 2) / samples
    total = 0.0
    for index in range(samples + 1):
        phase = index * step
        speed = math.hypot(
            -basis_u["x"] * math.sin(phase) + basis_v["x"] * math.cos(phase),
            -basis_u["y"] * math.sin(phase) + basis_v["y"] * math.cos(phase),
        )
        total += speed * (1 if index in {0, samples} else 4 if index % 2 else 2)
    return total * step / 3


def _ellipse_display_axes(basis_u: dict[str, float], basis_v: dict[str, float]) -> tuple[float, float, float]:
    """Convert arbitrary ellipse basis vectors into major/minor axes + rotation."""
    xx = basis_u["x"] ** 2 + basis_v["x"] ** 2
    xy = basis_u["x"] * basis_u["y"] + basis_v["x"] * basis_v["y"]
    yy = basis_u["y"] ** 2 + basis_v["y"] ** 2
    trace = xx + yy
    spread = math.hypot(xx - yy, 2 * xy)
    largest = max(0.0, (trace + spread) / 2)
    smallest = max(0.0, (trace - spread) / 2)
    rotation = 0.5 * math.atan2(2 * xy, xx - yy)
    return math.sqrt(largest), math.sqrt(smallest), math.degrees(rotation)


def _stays_outside_orbits(
    centre: dict[str, float], basis_u: dict[str, float], basis_v: dict[str, float],
    source: dict[str, Any], source_radius: float, target: dict[str, Any], target_radius: float,
) -> bool:
    """The transit arc must not cut through either circular orbit."""
    source_x, source_y = _number(source.get("x")), _number(source.get("y"))
    target_x, target_y = _number(target.get("x")), _number(target.get("y"))
    for index in range(1, 48):
        phase = (index / 48) * (math.pi / 2)
        x = centre["x"] + basis_u["x"] * math.cos(phase) + basis_v["x"] * math.sin(phase)
        y = centre["y"] + basis_u["y"] * math.cos(phase) + basis_v["y"] * math.sin(phase)
        if math.hypot(x - source_x, y - source_y) < source_radius - 1e-5:
            return False
        if math.hypot(x - target_x, y - target_y) < target_radius - 1e-5:
            return False
    return True


def _tangent_ellipse(
    departure: dict[str, Any], arrival: dict[str, Any], source_tangent: tuple[float, float], destination_tangent: tuple[float, float],
) -> tuple[dict[str, float], dict[str, float], dict[str, float]] | None:
    """Construct a quarter ellipse with exact tangents at both endpoints."""
    px, py = _number(departure.get("x")), _number(departure.get("y"))
    dx, dy = _number(arrival.get("x")) - px, _number(arrival.get("y")) - py
    tangent_x, tangent_y = destination_tangent
    determinant = source_tangent[0] * tangent_y - source_tangent[1] * tangent_x
    if abs(determinant) < 1e-7:
        return None
    source_scale = (dx * tangent_y - dy * tangent_x) / determinant
    destination_scale = (source_tangent[0] * dy - source_tangent[1] * dx) / determinant
    if source_scale <= 1e-5 or destination_scale <= 1e-5:
        return None
    basis_u = {"x": -destination_scale * destination_tangent[0], "y": -destination_scale * destination_tangent[1]}
    basis_v = {"x": source_scale * source_tangent[0], "y": source_scale * source_tangent[1]}
    centre = {"x": px - basis_u["x"], "y": py - basis_u["y"]}
    return centre, basis_u, basis_v


def _validate_transfer_clearance(universe: dict[str, Any], plan: TransferPlan) -> None:
    """Reject a committed transfer whose transit arc enters another star's radius."""
    objects = universe.get("objects")
    ship = objects.get(plan.object_id) if isinstance(objects, dict) else None
    if not isinstance(objects, dict) or not isinstance(ship, dict):
        raise TransferError("Could not validate transfer clearance.")
    source_id = plan.transfer_curve.get("source_object_id") or plan.transfer_curve.get("focus1")
    target_id = plan.transfer_curve.get("target_object_id") or plan.transfer_curve.get("focus1")
    target = objects.get(target_id)
    if isinstance(target, dict):
        final_clearance = collision_radius(ship, target)
        final_radius = _number(plan.destination_curve.get("major_axis"))
        if final_clearance is not None and final_radius <= final_clearance:
            raise TransferError(f"Destination orbit radius must exceed collision clearance ({final_clearance:g}).")

    obstacles = [
        (object_id, object_data)
        for object_id, object_data in objects.items()
        if object_id not in {plan.object_id, source_id, target_id}
        and isinstance(object_data, dict)
        and object_data.get("type") == "NATURAL"
        and location_of(object_data) is not None
        and collision_radius(ship, object_data) is not None
    ]
    if not obstacles:
        return
    smallest_clearance = min(collision_radius(ship, obstacle) or 1 for _, obstacle in obstacles)
    arc_length = max(1.0, _number(plan.transfer_curve.get("arc_length", 1.0)))
    samples = min(4000, max(96, math.ceil(arc_length / max(0.5, smallest_clearance / 2))))
    for index in range(samples + 1):
        position = _transfer_position(plan.transfer_curve, index / samples, objects)
        if position is None:
            continue
        for obstacle_id, obstacle in obstacles:
            obstacle_location = location_of(obstacle)
            clearance = collision_radius(ship, obstacle)
            if obstacle_location is None or clearance is None:
                continue
            if math.hypot(position["x"] - _number(obstacle_location.get("x")), position["y"] - _number(obstacle_location.get("y"))) <= clearance:
                raise TransferError(f"Unsafe transfer path: it enters collision clearance of star {obstacle_id}.")


def _transfer_position(curve: dict[str, Any], fraction: float, objects: dict[str, Any]) -> dict[str, float] | None:
    start, end = _number(curve.get("phase_start")), _number(curve.get("phase_end"))
    phase = start + (end - start) * fraction
    if isinstance(curve.get("basis_u"), dict) and isinstance(curve.get("basis_v"), dict):
        return basis_ellipse_position(curve, phase)
    focus = objects.get(curve.get("focus1"))
    focus_location = location_of(focus) if isinstance(focus, dict) else None
    return ellipse_position(focus_location, curve, phase) if focus_location else None


def build_transfer_plan(
    universe: dict[str, Any], object_id: str, target_id: str, target_radius: Any, now: float | None = None,
) -> TransferPlan:
    """Create a scheduled, normal-speed elliptical transfer between two objects."""
    objects = universe.get("objects")
    if not isinstance(objects, dict):
        raise TransferError("Universe has no objects.")
    ship = objects.get(object_id)
    target = objects.get(target_id)
    if not isinstance(ship, dict) or not isinstance(target, dict):
        raise TransferError("objectid1 and objectid2 must both exist in this universe.")
    if object_id == target_id:
        raise TransferError("The ship and transfer target must be different objects.")
    current_time = _number(universe.get("time", 0)) if now is None else float(now)
    # `location` is a spawn/checkpoint value. Curves determine the exact pose
    # at the time an action is accepted.
    departure = position_for_object_at_time(ship, objects, current_time) or location_of(ship)
    target_location = location_of(target)
    if departure is None or target_location is None:
        raise TransferError("Both the ship and target object need locations.")
    radius = _number(target_radius)
    if radius <= 0:
        raise TransferError("radnew must be greater than zero.")
    now = current_time
    blocked_till = universe.get("objects", {}).get(object_id, {}).get("maneuver_blocked_till")
    if blocked_till is not None:
        try:
            blocked_till = float(blocked_till)
        except (TypeError, ValueError):
            blocked_till = None
        if blocked_till is not None and blocked_till > now:
            raise ManeuverBlockedError(f"This object is blocked from new maneuvers until t={blocked_till:.2f}.")
    source = active_curve(ship.get("curves"), now)
    if source is None:
        raise TransferError("The ship has no active curve at the current universe time.")
    source_key, source_curve = source
    velocity = _number(source_curve.get("velocity", 0))
    if velocity <= 0:
        raise TransferError("The current active curve must have a positive velocity.")
    if abs(_number(source_curve.get("eccentricity"))) > 1e-7:
        raise TransferError("Transfers currently require a circular source orbit (eccentricity: 0).")
    direction = source_curve.get("direction", 1)
    source_focus = objects.get(source_curve.get("focus1"))
    source_focus_location = location_of(source_focus) if isinstance(source_focus, dict) else None
    if source_focus_location is None:
        raise TransferError("The current orbit's focus object needs a location.")
    if source_curve.get("focus1") == target_id:
        return _hohmann_plan(universe, object_id, target_id, radius, source_key, source_curve, departure, source_focus_location, velocity, now)
    source_radius = _number(source_curve.get("major_axis"))
    if source_radius <= 0:
        raise TransferError("The source orbit needs a positive major_axis.")
    source_phase = phase_from_position(departure, source_focus_location, source_curve)
    source_direction = 1.0 if float(direction) > 0 else -1.0
    destination_direction = -source_direction

    # Policy B: minimize the total distance before arrival. That includes the
    # source-orbit distance travelled while waiting plus the transfer-arc
    # length. The grid is deliberately small because this runs inside a
    # Firebase transaction; it is accurate enough for gameplay routing.
    best = None
    focus_x, focus_y = _number(source_focus_location.get("x")), _number(source_focus_location.get("y"))
    target_x, target_y = _number(target_location.get("x")), _number(target_location.get("y"))
    for step in range(1, 181):
        travelled_angle = (step / 180) * math.tau
        departure_phase = (source_phase + source_direction * travelled_angle) % math.tau
        candidate_departure = {
            "x": focus_x + source_radius * math.cos(departure_phase),
            "y": focus_y + source_radius * math.sin(departure_phase),
        }
        if math.hypot(candidate_departure["x"] - target_x, candidate_departure["y"] - target_y) <= radius:
            continue
        source_tangent = (source_direction * -math.sin(departure_phase), source_direction * math.cos(departure_phase))
        wait_distance = source_radius * travelled_angle
        for target_step in range(180):
            arrival_angle = (target_step / 180) * math.tau
            arrival = {"x": target_x + radius * math.cos(arrival_angle), "y": target_y + radius * math.sin(arrival_angle)}
            destination_tangent = (destination_direction * -math.sin(arrival_angle), destination_direction * math.cos(arrival_angle))
            tangent_ellipse = _tangent_ellipse(candidate_departure, arrival, source_tangent, destination_tangent)
            if tangent_ellipse is None:
                continue
            centre, basis_u, basis_v = tangent_ellipse
            a, b, rotation = _ellipse_display_axes(basis_u, basis_v)
            # Prevent degenerate, needle-like transfer arcs.
            if b <= 1e-6 or b / a < 0.15:
                continue
            if not _stays_outside_orbits(centre, basis_u, basis_v, source_focus_location, source_radius, target_location, radius):
                continue
            arc_length = _arc_length(basis_u, basis_v)
            total_distance = wait_distance + arc_length
            candidate = (total_distance, travelled_angle, candidate_departure, arrival, centre, basis_u, basis_v, a, b, rotation)
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:
        raise TransferError("Could not find a future tangent departure point for this transfer.")
    _, travelled_angle, departure, arrival, centre, basis_u, basis_v, a, b, rotation = best
    # Recompute the chosen arc at high precision after the fast grid search.
    arc_length = _arc_length(basis_u, basis_v, samples=720)
    wait_seconds = source_radius * travelled_angle / velocity
    eccentricity = math.sqrt(max(0.0, 1 - (b / a) ** 2))
    start_time = now + wait_seconds
    arrival_time = start_time + arc_length / velocity

    transfer_key, destination_key = _next_curve_keys(ship.get("curves"))
    destination_curve = {
        # It is time-gated by valid_from, but remains active so the UI can
        # show its dotted planned orbit before arrival.
        "active": True,
        "motion_type": "ORBIT",
        "focus1": target_id,
        "major_axis": radius,
        "eccentricity": 0,
        "rotation": 0,
        "velocity": velocity,
        "direction": destination_direction,
        "phase": math.atan2(arrival["y"] - _number(target_location.get("y")), arrival["x"] - _number(target_location.get("x"))) % math.tau,
        "phase_updated_at": arrival_time,
        "valid_from": arrival_time,
        "valid_till": -1,
        "dotted": True,
    }
    transfer_curve = {
        "active": True,
        "type": "ELLIPSE",
        "motion_type": "INTERSTELLAR_ELLIPSE",
        "source_object_id": source_curve.get("focus1"),
        "target_object_id": target_id,
        "major_axis": a,
        "minor_axis": b,
        "eccentricity": eccentricity,
        "rotation": rotation,
        "centre": centre,
        "basis_u": basis_u,
        "basis_v": basis_v,
        "velocity": velocity,
        "direction": 1,
        "phase": 0,
        "phase_start": 0,
        "phase_end": math.pi / 2,
        "phase_updated_at": start_time,
        "valid_from": start_time,
        "valid_till": arrival_time,
        "departure_location": departure,
        "arrival_location": arrival,
        "arc_length": arc_length,
    }
    plan = TransferPlan(object_id, source_key, transfer_key, destination_key, start_time, arrival_time, transfer_curve, destination_curve)
    _validate_transfer_clearance(universe, plan)
    return plan


def apply_transfer_plan(universe: dict[str, Any], plan: TransferPlan) -> dict[str, Any]:
    objects = universe["objects"]
    objects[plan.object_id]["maneuver_blocked_till"] = plan.arrival_time
    curves = objects[plan.object_id].setdefault("curves", {})
    if isinstance(curves, list):
        while len(curves) <= int(plan.destination_curve_key):
            curves.append(None)
        curves[int(plan.transfer_curve_key)] = plan.transfer_curve
        curves[int(plan.destination_curve_key)] = plan.destination_curve
        curves[int(plan.source_curve_key)]["valid_till"] = plan.start_time
    else:
        curves[plan.source_curve_key]["valid_till"] = plan.start_time
        curves[plan.transfer_curve_key] = plan.transfer_curve
        curves[plan.destination_curve_key] = plan.destination_curve
    return universe
