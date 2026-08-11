from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class UniverseGenerationConfig:
    star_count: int = 20
    star_distance_target: float = 500
    star_distance_min: float = 100
    star_distance_max: float = 2000
    star_placement_attempts: int = 100
    ship_count: int = 3
    ship_count_max: int = 3
    ship_orbit_radius: float = 150
    ship_orbit_velocity: float = 20
    gun_velocity: float = 300
    gun_hit_radius: float = 20
    star_life: float = 1000
    ship_life: float = 200
    star_border_radius: float = 2
    ship_border_radius: float = 2

    @classmethod
    def from_environment(cls) -> "UniverseGenerationConfig":
        config = cls(
            star_count=int(os.getenv("UNIVERSE_STAR_COUNT", "20")),
            star_distance_target=float(os.getenv("UNIVERSE_STAR_DISTANCE_TARGET", "500")),
            star_distance_min=float(os.getenv("UNIVERSE_STAR_DISTANCE_MIN", "100")),
            star_distance_max=float(os.getenv("UNIVERSE_STAR_DISTANCE_MAX", "2000")),
            star_placement_attempts=int(os.getenv("UNIVERSE_STAR_PLACEMENT_ATTEMPTS", "100")),
            ship_count=int(os.getenv("UNIVERSE_SHIP_COUNT", "3")),
            ship_count_max=int(os.getenv("UNIVERSE_SHIP_COUNT_MAX", "3")),
            ship_orbit_radius=float(os.getenv("UNIVERSE_SHIP_ORBIT_RADIUS", "150")),
            ship_orbit_velocity=float(os.getenv("UNIVERSE_SHIP_ORBIT_VELOCITY", "20")),
            gun_velocity=float(os.getenv("UNIVERSE_GUN_VELOCITY", "300")),
            gun_hit_radius=float(os.getenv("UNIVERSE_GUN_HIT_RADIUS", "20")),
            star_life=float(os.getenv("UNIVERSE_STAR_LIFE", "1000")),
            ship_life=float(os.getenv("UNIVERSE_SHIP_LIFE", "200")),
            star_border_radius=float(os.getenv("UNIVERSE_STAR_BORDER_RADIUS", "2")),
            ship_border_radius=float(os.getenv("UNIVERSE_SHIP_BORDER_RADIUS", "2")),
        )
        config.validate()
        return config

    def with_options(self, options: object) -> "UniverseGenerationConfig":
        if options is None:
            return self
        if not isinstance(options, dict):
            raise ValueError("Generation options must be an object.")
        star_count = options.get("star_count", self.star_count)
        ship_count = options.get("ship_count", self.ship_count)
        if isinstance(star_count, bool) or not isinstance(star_count, int):
            raise ValueError("star_count must be a whole number.")
        if isinstance(ship_count, bool) or not isinstance(ship_count, int):
            raise ValueError("ship_count must be a whole number.")
        config = UniverseGenerationConfig(**{**self.__dict__, "star_count": star_count, "ship_count": ship_count})
        config.validate()
        return config

    def validate(self) -> None:
        if self.star_count < 1:
            raise ValueError("UNIVERSE_STAR_COUNT must be at least 1.")
        if not 0 < self.star_distance_min <= self.star_distance_target <= self.star_distance_max:
            raise ValueError("Star distances must satisfy 0 < min <= target <= max.")
        if self.star_placement_attempts < 1:
            raise ValueError("UNIVERSE_STAR_PLACEMENT_ATTEMPTS must be at least 1.")
        if not 0 <= self.ship_count <= self.ship_count_max:
            raise ValueError(f"ship_count must be between 0 and {self.ship_count_max}.")
        if self.ship_orbit_radius <= 0 or self.ship_orbit_velocity <= 0 or self.gun_velocity <= 0 or self.gun_hit_radius <= 0:
            raise ValueError("Starter ship and gun settings must be positive.")
        if self.star_life < 0 or self.ship_life < 0:
            raise ValueError("Starter object life values cannot be negative.")
        if self.star_border_radius < 0 or self.ship_border_radius < 0:
            raise ValueError("Starter object border radii cannot be negative.")
