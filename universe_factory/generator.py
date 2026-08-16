from __future__ import annotations

import math
import random
import uuid

from schema.factories import new_empty_universe, new_gun, new_radar, new_ship, new_star
from schema.models import Position, UniverseRecord
from universe_factory.config import UniverseGenerationConfig


class UniverseGenerationError(ValueError):
    pass


def create_universe(config: UniverseGenerationConfig, seed: int | None = None) -> tuple[str, UniverseRecord]:
    """Create a random-ID universe populated with procedurally placed stars."""
    rng = random.Random(seed)
    universe = new_empty_universe(spawn_config(config))
    [create_star(universe, location, config.star_life, config.star_border_radius) for location in generate_star_locations(config, rng)]
    # A short numeric code is easy to share and use in the universe picker.
    # Creation still verifies that the code is unused in its Firebase
    # transaction before committing it.
    return str(rng.randrange(1000, 10_000)), universe


def create_star(universe: UniverseRecord, location: Position, life: float, border_radius: float, object_id: str | None = None) -> str:
    """Add one schema-valid natural star to an existing generated universe."""
    objects = universe.setdefault("objects", {})
    star_id = object_id or f"star_{uuid.uuid4().hex}"
    if star_id in objects:
        raise UniverseGenerationError(f"Object ID already exists: {star_id}")
    objects[star_id] = new_star(location, life, border_radius)
    return star_id


def create_ship(
    universe: UniverseRecord,
    star_id: str,
    config: UniverseGenerationConfig,
    rng: random.Random,
    owner: str,
    orbit_radius: float | None = None,
    object_id: str | None = None,
    phase: float | None = None,
    velocity: float | None = None,
) -> str:
    objects = universe.setdefault("objects", {})
    star = objects.get(star_id)
    if not isinstance(star, dict) or not isinstance(star.get("location"), dict):
        raise UniverseGenerationError(f"Cannot orbit unknown star: {star_id}")
    radius = config.ship_orbit_radius if orbit_radius is None else orbit_radius
    if radius <= 0:
        raise UniverseGenerationError("Ship orbit radius must be positive.")
    orbit_phase = rng.uniform(0, math.tau) if phase is None else phase
    orbit_velocity = config.ship_orbit_velocity if velocity is None else velocity
    star_location = star["location"]
    location = {
        "x": float(star_location["x"]) + math.cos(orbit_phase) * radius,
        "y": float(star_location["y"]) + math.sin(orbit_phase) * radius,
    }
    ship_id = object_id or f"ship_{uuid.uuid4().hex}"
    if ship_id in objects:
        raise UniverseGenerationError(f"Object ID already exists: {ship_id}")
    objects[ship_id] = new_ship(location, star_id, radius, orbit_phase, orbit_velocity, rng.choice([-1, 1]), owner, config.ship_life, config.ship_border_radius)
    return ship_id


def mount_gun(universe: UniverseRecord, ship_id: str, velocity: float, hit_radius: float, gun_id: str | None = None) -> str:
    ship = universe.setdefault("objects", {}).get(ship_id)
    if not isinstance(ship, dict) or ship.get("type") != "ARTIFICIAL":
        raise UniverseGenerationError(f"Cannot mount gun on unknown ship: {ship_id}")
    attachments = ship.setdefault("objects", {})
    attached_id = gun_id or f"gun_{uuid.uuid4().hex}"
    if attached_id in attachments:
        raise UniverseGenerationError(f"Attached object ID already exists: {attached_id}")
    attachments[attached_id] = new_gun(velocity, hit_radius)
    return attached_id


def mount_radar(universe: UniverseRecord, ship_id: str, radius: float, radar_id: str | None = None) -> str:
    ship = universe.setdefault("objects", {}).get(ship_id)
    if not isinstance(ship, dict) or ship.get("type") != "ARTIFICIAL":
        raise UniverseGenerationError(f"Cannot mount radar on unknown ship: {ship_id}")
    if radius <= 0:
        raise UniverseGenerationError("Radar radius must be positive.")
    attachments = ship.setdefault("objects", {})
    attached_id = radar_id or f"radar_{uuid.uuid4().hex}"
    if attached_id in attachments:
        raise UniverseGenerationError(f"Attached object ID already exists: {attached_id}")
    attachments[attached_id] = new_radar(radius)
    return attached_id


def generate_star_locations(config: UniverseGenerationConfig, rng: random.Random) -> list[Position]:
    """Generate a connected star cluster with bounded local spacing.

    `star_distance_max` limits the distance from a new star to its selected
    parent star. It does not limit every pair in a 20-star cluster.
    """
    locations: list[Position] = [{"x": 0.0, "y": 0.0}]
    while len(locations) < config.star_count:
        candidate: Position | None = None
        for _ in range(config.star_placement_attempts):
            parent = rng.choice(locations)
            distance = sample_star_distance(config, rng)
            angle = rng.uniform(0, math.tau)
            proposal = {
                "x": parent["x"] + math.cos(angle) * distance,
                "y": parent["y"] + math.sin(angle) * distance,
            }
            if all(math.hypot(proposal["x"] - star["x"], proposal["y"] - star["y"]) >= config.star_distance_min for star in locations):
                candidate = proposal
                break
        if candidate is None:
            raise UniverseGenerationError(
                f"Could not place star {len(locations) + 1} after {config.star_placement_attempts} attempts."
            )
        locations.append(candidate)
    return locations


def sample_star_distance(config: UniverseGenerationConfig, rng: random.Random) -> float:
    """Sample a varied distance with mean close to the configured target."""
    spread = max(1e-9, config.star_distance_target - config.star_distance_min)
    return min(config.star_distance_max, config.star_distance_min + rng.expovariate(1 / spread))


def spawn_config(config: UniverseGenerationConfig) -> dict:
    return {
        "starter_ship_count": config.ship_count,
        "ship_orbit_radius": config.ship_orbit_radius,
        "ship_orbit_velocity": config.ship_orbit_velocity,
        "gun_velocity": config.gun_velocity,
        "gun_hit_radius": config.gun_hit_radius,
        "star_life": config.star_life,
        "ship_life": config.ship_life,
        "star_border_radius": config.star_border_radius,
        "ship_border_radius": config.ship_border_radius,
    }
