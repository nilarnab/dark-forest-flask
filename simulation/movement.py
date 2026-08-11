from __future__ import annotations

from typing import Any

from simulation.orbit import advance_basis_phase, advance_phase, axes_for_curve, basis_ellipse_position, ellipse_position, ellipse_position_from_axes, phase_from_position


def as_mapping(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def location_of(obj: dict[str, Any]) -> dict[str, Any] | None:
    return as_mapping(obj.get("location"))


def curve_items(curves: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(curves, list):
        return [(str(index), curve) for index, curve in enumerate(curves) if isinstance(curve, dict)]
    if isinstance(curves, dict):
        return [(str(key), curve) for key, curve in curves.items() if isinstance(curve, dict)]
    return []


def is_active(curve: dict[str, Any], universe_time: float) -> bool:
    valid_from = float(curve.get("valid_from", float("-inf")))
    valid_till = curve.get("valid_till", -1)
    if not valid_from <= universe_time or (valid_till != -1 and universe_time >= float(valid_till)):
        return False
    # A curve with valid_from is scheduled to become active later. This lets
    # it remain visibly inactive/dotted until the tick reaches that time.
    return bool(curve.get("active", False)) or "valid_from" in curve


def active_curve(curves: Any, universe_time: float) -> tuple[str, dict[str, Any]] | None:
    for curve_key, curve in curve_items(curves):
        if is_active(curve, universe_time):
            return curve_key, curve
    return None


def next_position_for_object(
    obj: dict[str, Any],
    objects: dict[str, Any],
    universe_time: float,
    tick_seconds: float,
) -> tuple[dict[str, float], list[tuple[str, float, float]]] | None:
    """Advance through one or more scheduled curves without skipping boundaries."""
    position = location_of(obj)
    cursor, remaining = universe_time, tick_seconds
    curve_updates: list[tuple[str, float, float]] = []
    while remaining > 1e-9:
        selected = active_curve(obj.get("curves"), cursor)
        if selected is None:
            break
        curve_key, curve = selected
        valid_till = curve.get("valid_till", -1)
        segment = remaining if valid_till == -1 else min(remaining, max(0.0, float(valid_till) - cursor))
        if segment <= 1e-9:
            cursor += 1e-9
            continue
        if curve.get("type") == "STRAIGHT_LINE":
            start = curve.get("start_location")
            vector = curve.get("direction_vector")
            if not isinstance(start, dict) or not isinstance(vector, dict):
                break
            try:
                vector_x, vector_y = float(vector["x"]), float(vector["y"])
                length = (vector_x ** 2 + vector_y ** 2) ** 0.5
                if length == 0:
                    break
                reference_time = float(curve.get("valid_from", cursor))
                elapsed = max(0.0, cursor + segment - reference_time)
                distance = float(curve.get("velocity", 0)) * elapsed
                position = {"x": float(start["x"]) + vector_x / length * distance, "y": float(start["y"]) + vector_y / length * distance}
            except (KeyError, TypeError, ValueError):
                break
            cursor += segment
            remaining -= segment
            curve_updates.append((curve_key, distance, cursor))
            continue
        a, b = axes_for_curve(curve)
        if a <= 0 or b <= 0:
            break
        phase = curve.get("phase")
        if phase is None:
            focus_object = as_mapping(objects.get(curve.get("focus1")))
            focus_location = location_of(focus_object or {})
            phase = phase_from_position(position or {}, focus_location, curve) if position and focus_location else 0.0
        if isinstance(curve.get("basis_u"), dict) and isinstance(curve.get("basis_v"), dict):
            new_phase = advance_basis_phase(float(phase), float(curve.get("velocity", 0)), segment, curve["basis_u"], curve["basis_v"])
        else:
            new_phase = advance_phase(float(phase), float(curve.get("velocity", 0)), segment, a, b, curve.get("direction", 1))
        if isinstance(curve.get("basis_u"), dict) and isinstance(curve.get("basis_v"), dict):
            position = basis_ellipse_position(curve, new_phase) if "basis_u" in curve else ellipse_position_from_axes(curve, new_phase)
        else:
            focus_object = as_mapping(objects.get(curve.get("focus1")))
            focus_location = location_of(focus_object or {})
            position = ellipse_position(focus_location, curve, new_phase) if focus_location else None
        # The endpoint selected duration from the exact arc length. Snap the
        # scheduled transfer endpoint to avoid numeric drift before entering
        # its next circular orbit.
        if valid_till != -1 and abs((cursor + segment) - float(valid_till)) < 1e-7:
            arrival = curve.get("arrival_location")
            if isinstance(arrival, dict):
                position = {"x": float(arrival["x"]), "y": float(arrival["y"])}
        if position is None:
            break
        cursor += segment
        remaining -= segment
        curve_updates.append((curve_key, new_phase, cursor))
    return (position, curve_updates) if position is not None and curve_updates else None


def position_for_object_at_time(
    obj: dict[str, Any], objects: dict[str, Any], universe_time: float,
) -> dict[str, float] | None:
    """Reconstruct an object's analytic position at an arbitrary simulation time.

    Unlike ``next_position_for_object``, this can move backward from a curve's
    phase timestamp. It is used for read-only verification, not normal ticks.
    """
    selected = active_curve(obj.get("curves"), universe_time)
    if selected is None:
        position = location_of(obj)
        return {"x": float(position["x"]), "y": float(position["y"])} if position else None
    _, curve = selected
    if curve.get("type") == "STRAIGHT_LINE":
        start, vector = curve.get("start_location"), curve.get("direction_vector")
        if not isinstance(start, dict) or not isinstance(vector, dict):
            return None
        try:
            dx, dy = float(vector["x"]), float(vector["y"])
            length = (dx * dx + dy * dy) ** 0.5
            if length == 0:
                return None
            elapsed = universe_time - float(curve.get("valid_from", universe_time))
            distance = float(curve.get("velocity", 0)) * max(0.0, elapsed)
            return {"x": float(start["x"]) + dx / length * distance, "y": float(start["y"]) + dy / length * distance}
        except (KeyError, TypeError, ValueError):
            return None
    a, b = axes_for_curve(curve)
    if a <= 0 or b <= 0:
        return None
    phase = curve.get("phase")
    reference_time = curve.get("phase_updated_at", universe_time)
    if not isinstance(phase, (int, float)):
        position = location_of(obj)
        focus_object = as_mapping(objects.get(curve.get("focus1")))
        focus_location = location_of(focus_object or {})
        phase = phase_from_position(position or {}, focus_location, curve) if position and focus_location else 0.0
        reference_time = universe_time
    try:
        elapsed = universe_time - float(reference_time)
    except (TypeError, ValueError):
        elapsed = 0.0
    if isinstance(curve.get("basis_u"), dict) and isinstance(curve.get("basis_v"), dict):
        new_phase = advance_basis_phase(float(phase), float(curve.get("velocity", 0)), elapsed, curve["basis_u"], curve["basis_v"])
        return basis_ellipse_position(curve, new_phase)
    new_phase = advance_phase(float(phase), float(curve.get("velocity", 0)), elapsed, a, b, curve.get("direction", 1))
    focus_object = as_mapping(objects.get(curve.get("focus1")))
    focus_location = location_of(focus_object or {})
    return ellipse_position(focus_location, curve, new_phase) if focus_location else None
