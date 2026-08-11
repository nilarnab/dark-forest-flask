from __future__ import annotations

from typing import Any


def simulation_time(universe: dict[str, Any], wall_clock_ms: float) -> float:
    """Return continuous simulation time from a persisted clock anchor."""
    base_time = float(universe.get("time", 0))
    anchor = universe.get("time_updated_at_ms")
    if not isinstance(anchor, (int, float)):
        return base_time
    return base_time + max(0.0, (wall_clock_ms - float(anchor)) / 1000.0)
