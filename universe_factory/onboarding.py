from __future__ import annotations

import math
import random

from schema.factories import new_membership
from schema.models import UniverseRecord
from universe_factory.config import UniverseGenerationConfig
from universe_factory.generator import create_ship, mount_gun


class OnboardingError(ValueError):
    pass


def onboard_user(universe: UniverseRecord, username: str, config: UniverseGenerationConfig, now: float) -> dict:
    star_id = choose_star(universe, random.Random())
    objects = universe["objects"]
    objects[star_id]["owner"] = username
    spawn = universe.get("spawn_config") if isinstance(universe.get("spawn_config"), dict) else {}
    assigned_config = UniverseGenerationConfig(**{
        **config.__dict__,
        "ship_count": int(spawn.get("starter_ship_count", config.ship_count)),
        "ship_orbit_radius": float(spawn.get("ship_orbit_radius", config.ship_orbit_radius)),
        "ship_orbit_velocity": float(spawn.get("ship_orbit_velocity", config.ship_orbit_velocity)),
        "gun_velocity": float(spawn.get("gun_velocity", config.gun_velocity)),
        "gun_hit_radius": float(spawn.get("gun_hit_radius", config.gun_hit_radius)),
        "star_life": float(spawn.get("star_life", config.star_life)),
        "ship_life": float(spawn.get("ship_life", config.ship_life)),
        "star_border_radius": float(spawn.get("star_border_radius", config.star_border_radius)),
        "ship_border_radius": float(spawn.get("ship_border_radius", config.ship_border_radius)),
    })
    assigned_config.validate()
    ship_ids = []
    rng = random.Random()
    for index in range(assigned_config.ship_count):
        orbit_radius = assigned_config.ship_orbit_radius * (index + 1) / assigned_config.ship_count
        ship_id = create_ship(universe, star_id, assigned_config, rng, username, orbit_radius=orbit_radius)
        mount_gun(universe, ship_id, assigned_config.gun_velocity, assigned_config.gun_hit_radius)
        ship_ids.append(ship_id)
    return new_membership(star_id, ship_ids, now)


def choose_star(universe: UniverseRecord, rng: random.Random) -> str:
    objects = universe.get("objects", {})
    # Older manually-created universes do not have sub_type: STAR. Any
    # top-level natural object with a location is therefore eligible as a star
    # for first-entry ownership assignment.
    stars = [(object_id, obj) for object_id, obj in objects.items() if isinstance(obj, dict) and obj.get("type") == "NATURAL" and obj.get("owner") is None and isinstance(obj.get("location"), dict)]
    if not stars:
        raise OnboardingError("No unowned generated stars are available.")
    owned_locations = [obj["location"] for obj in objects.values() if isinstance(obj, dict) and obj.get("type") == "NATURAL" and isinstance(obj.get("owner"), str) and isinstance(obj.get("location"), dict)]
    if not owned_locations:
        return rng.choice(convex_hull(stars))[0]
    ranked = sorted(stars, key=lambda item: min(math.hypot(float(item[1]["location"]["x"]) - float(owned["x"]), float(item[1]["location"]["y"]) - float(owned["y"])) for owned in owned_locations), reverse=True)
    return rng.choice(ranked[:5])[0]


def convex_hull(stars: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    if len(stars) <= 2:
        return stars
    points = sorted(stars, key=lambda item: (float(item[1]["location"]["x"]), float(item[1]["location"]["y"])))
    def cross(origin, first, second):
        return ((float(first[1]["location"]["x"]) - float(origin[1]["location"]["x"])) * (float(second[1]["location"]["y"]) - float(origin[1]["location"]["y"])) - (float(first[1]["location"]["y"]) - float(origin[1]["location"]["y"])) * (float(second[1]["location"]["x"]) - float(origin[1]["location"]["x"])))
    lower = []
    for point in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0: lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0: upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]
