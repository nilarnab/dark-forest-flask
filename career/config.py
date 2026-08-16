from __future__ import annotations

import os
from dataclasses import dataclass

from universe_factory.config import UniverseGenerationConfig


@dataclass(frozen=True)
class CareerGenerationConfig:
    level_one_star_count: int
    level_one_radar_radius: float
    level_one_enemy_orbit_radius: float
    level_one_near_miss_distance: float
    level_one_player_orbit_radius: float
    level_one_enemy_orbit_velocity: float
    level_one_enemy_star_distance_multiplier: float = 1.3
    level_one_enemy_approach_delay_seconds: float = 8.0

    @classmethod
    def from_environment(cls, universe: UniverseGenerationConfig) -> "CareerGenerationConfig":
        config = cls(
            level_one_star_count=int(os.getenv("CAREER_LEVEL_1_STAR_COUNT", "5")),
            level_one_radar_radius=float(os.getenv("CAREER_LEVEL_1_RADAR_RADIUS", str(universe.star_distance_target))),
            level_one_enemy_orbit_radius=float(os.getenv("CAREER_LEVEL_1_ENEMY_ORBIT_RADIUS", "120")),
            level_one_enemy_star_distance_multiplier=float(os.getenv("CAREER_LEVEL_1_ENEMY_STAR_DISTANCE_MULTIPLIER", "1.3")),
            level_one_near_miss_distance=float(os.getenv("CAREER_LEVEL_1_NEAR_MISS_DISTANCE", "50")),
            level_one_player_orbit_radius=float(os.getenv("CAREER_LEVEL_1_PLAYER_ORBIT_RADIUS", str(universe.ship_orbit_radius))),
            level_one_enemy_orbit_velocity=float(os.getenv("CAREER_LEVEL_1_ENEMY_ORBIT_VELOCITY", str(universe.ship_orbit_velocity))),
            level_one_enemy_approach_delay_seconds=float(os.getenv("CAREER_LEVEL_1_ENEMY_APPROACH_DELAY_SECONDS", "8")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.level_one_star_count < 2:
            raise ValueError("CAREER_LEVEL_1_STAR_COUNT must be at least 2.")
        if self.level_one_radar_radius <= 0 or self.level_one_near_miss_distance <= 0:
            raise ValueError("Career Level 1 radar and near-miss distances must be positive.")
        if self.level_one_near_miss_distance >= self.level_one_radar_radius:
            raise ValueError("CAREER_LEVEL_1_NEAR_MISS_DISTANCE must be smaller than the radar radius.")
        if self.level_one_player_orbit_radius <= 0 or self.level_one_enemy_orbit_radius <= 0 or self.level_one_enemy_orbit_velocity <= 0 or self.level_one_enemy_star_distance_multiplier <= 0 or self.level_one_enemy_approach_delay_seconds < 0:
            raise ValueError("Career Level 1 orbit settings must be positive.")
