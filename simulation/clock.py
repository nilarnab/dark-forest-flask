from __future__ import annotations

from typing import Any


def simulation_time(universe: dict[str, Any], wall_clock_ms: float) -> float:
    """Return continuous simulation time from a persisted clock anchor."""
    base_time = float(universe.get("time", 0))
    # `active: false` freezes the shared clock.  Without this guard, merely
    # resuming a paused tutorial would add the entire real-world pause to the
    # simulation time and make every analytic orbit jump forward.
    if universe.get("active") is not True:
        return base_time
    anchor = universe.get("time_updated_at_ms")
    if not isinstance(anchor, (int, float)):
        return base_time
    return base_time + max(0.0, (wall_clock_ms - float(anchor)) / 1000.0)
