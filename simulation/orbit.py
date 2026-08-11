from __future__ import annotations

import math
from typing import Any


TAU = math.tau


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def semi_minor_axis(semi_major_axis: float, eccentricity: float) -> float:
    return semi_major_axis * math.sqrt(max(0.0, 1.0 - eccentricity**2))


def speed_per_radian(phase: float, semi_major_axis: float, semi_minor: float) -> float:
    """Arc-length derivative for x=a cos(t), y=b sin(t)."""
    return math.hypot(semi_major_axis * math.sin(phase), semi_minor * math.cos(phase))


def direction_sign(direction: Any) -> float:
    """Accept 1/-1; 0 is also accepted as the backwards direction for old data."""
    return -1.0 if _number(direction, 1.0) <= 0.0 else 1.0


def advance_phase(
    phase: float,
    velocity: float,
    seconds: float,
    semi_major_axis: float,
    semi_minor: float,
    direction: Any,
) -> float:
    """Advance by normal linear distance, not angular velocity.

    A short midpoint integration keeps the speed visually consistent around an
    ellipse. Small substeps also make it stable for higher velocities.
    """
    distance = max(0.0, velocity) * abs(seconds)
    if distance == 0 or semi_major_axis <= 0 or semi_minor <= 0:
        return phase % TAU

    steps = max(1, math.ceil(distance / max(1.0, min(semi_major_axis, semi_minor) * 0.03)))
    step_distance = distance / steps
    sign = direction_sign(direction) * (-1.0 if seconds < 0 else 1.0)
    result = phase
    for _ in range(steps):
        derivative = max(speed_per_radian(result, semi_major_axis, semi_minor), 1e-9)
        estimate = sign * step_distance / derivative
        midpoint_derivative = max(speed_per_radian(result + estimate / 2, semi_major_axis, semi_minor), 1e-9)
        result += sign * step_distance / midpoint_derivative
    return result % TAU


def ellipse_position(
    focus: dict[str, Any], curve: dict[str, Any], phase: float) -> dict[str, float] | None:
    """Return the position for a curve whose focus1 is the supplied object."""
    a = _number(curve.get("major_axis"))
    eccentricity = _number(curve.get("eccentricity"))
    if a <= 0 or not 0 <= eccentricity < 1:
        return None
    b = semi_minor_axis(a, eccentricity)
    rotation = math.radians(_number(curve.get("rotation")))
    focus_x, focus_y = _number(focus.get("x")), _number(focus.get("y"))

    # Focus 1 is at centre + c along the ellipse's rotated major axis.
    c = a * eccentricity
    centre_x = focus_x - c * math.cos(rotation)
    centre_y = focus_y - c * math.sin(rotation)
    local_x = a * math.cos(phase)
    local_y = b * math.sin(phase)
    return {
        "x": centre_x + local_x * math.cos(rotation) - local_y * math.sin(rotation),
        "y": centre_y + local_x * math.sin(rotation) + local_y * math.cos(rotation),
    }


def ellipse_position_from_axes(curve: dict[str, Any], phase: float) -> dict[str, float] | None:
    """Position on a free-standing ellipse, used for interstellar transfers."""
    centre = curve.get("centre")
    if not isinstance(centre, dict):
        return None
    a = _number(curve.get("major_axis"))
    b = _number(curve.get("minor_axis"))
    if a <= 0 or b <= 0:
        return None
    rotation = math.radians(_number(curve.get("rotation")))
    local_x = a * math.cos(phase)
    local_y = b * math.sin(phase)
    return {
        "x": _number(centre.get("x")) + local_x * math.cos(rotation) - local_y * math.sin(rotation),
        "y": _number(centre.get("y")) + local_x * math.sin(rotation) + local_y * math.cos(rotation),
    }


def axes_for_curve(curve: dict[str, Any]) -> tuple[float, float]:
    a = _number(curve.get("major_axis"))
    if curve.get("motion_type") == "INTERSTELLAR_ELLIPSE":
        return a, _number(curve.get("minor_axis"))
    return a, semi_minor_axis(a, _number(curve.get("eccentricity")))


def half_ellipse_arc_length(semi_major_axis: float, semi_minor: float, samples: int = 720) -> float:
    """Numerically integrate the length of either half of an ellipse."""
    if semi_major_axis <= 0 or semi_minor <= 0:
        return 0.0
    # Simpson's rule needs an even number of intervals.
    samples += samples % 2
    step = math.pi / samples
    total = speed_per_radian(0, semi_major_axis, semi_minor) + speed_per_radian(math.pi, semi_major_axis, semi_minor)
    for index in range(1, samples):
        weight = 4 if index % 2 else 2
        total += weight * speed_per_radian(index * step, semi_major_axis, semi_minor)
    return total * step / 3


def basis_speed(phase: float, basis_u: dict[str, Any], basis_v: dict[str, Any]) -> float:
    """Arc-length derivative for centre + u*cos(phase) + v*sin(phase)."""
    dx = -_number(basis_u.get("x")) * math.sin(phase) + _number(basis_v.get("x")) * math.cos(phase)
    dy = -_number(basis_u.get("y")) * math.sin(phase) + _number(basis_v.get("y")) * math.cos(phase)
    return math.hypot(dx, dy)


def advance_basis_phase(phase: float, velocity: float, seconds: float, basis_u: dict[str, Any], basis_v: dict[str, Any]) -> float:
    distance = max(0.0, velocity) * abs(seconds)
    if distance == 0:
        return phase
    minimum_axis = max(1.0, min(math.hypot(_number(basis_u.get("x")), _number(basis_u.get("y"))), math.hypot(_number(basis_v.get("x")), _number(basis_v.get("y")))))
    steps = max(1, math.ceil(distance / (minimum_axis * 0.03)))
    step_distance = distance / steps
    result = phase
    for _ in range(steps):
        derivative = max(basis_speed(result, basis_u, basis_v), 1e-9)
        estimate = (-1.0 if seconds < 0 else 1.0) * step_distance / derivative
        midpoint = max(basis_speed(result + estimate / 2, basis_u, basis_v), 1e-9)
        result += (-1.0 if seconds < 0 else 1.0) * step_distance / midpoint
    return result


def basis_ellipse_position(curve: dict[str, Any], phase: float) -> dict[str, float] | None:
    centre, basis_u, basis_v = curve.get("centre"), curve.get("basis_u"), curve.get("basis_v")
    if not isinstance(centre, dict) or not isinstance(basis_u, dict) or not isinstance(basis_v, dict):
        return None
    return {
        "x": _number(centre.get("x")) + _number(basis_u.get("x")) * math.cos(phase) + _number(basis_v.get("x")) * math.sin(phase),
        "y": _number(centre.get("y")) + _number(basis_u.get("y")) * math.cos(phase) + _number(basis_v.get("y")) * math.sin(phase),
    }


def phase_from_position(position: dict[str, Any], focus: dict[str, Any], curve: dict[str, Any]) -> float:
    """Derive an initial phase from an existing location when phase is absent."""
    a = _number(curve.get("major_axis"))
    eccentricity = _number(curve.get("eccentricity"))
    b = semi_minor_axis(a, eccentricity)
    if a <= 0 or b <= 0:
        return 0.0
    rotation = math.radians(_number(curve.get("rotation")))
    c = a * eccentricity
    centre_x = _number(focus.get("x")) - c * math.cos(rotation)
    centre_y = _number(focus.get("y")) - c * math.sin(rotation)
    dx, dy = _number(position.get("x")) - centre_x, _number(position.get("y")) - centre_y
    local_x = dx * math.cos(rotation) + dy * math.sin(rotation)
    local_y = -dx * math.sin(rotation) + dy * math.cos(rotation)
    return math.atan2(local_y / b, local_x / a) % TAU
