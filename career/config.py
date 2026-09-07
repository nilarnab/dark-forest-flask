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
    level_one_player_orbit_velocity: float = 40.0
    # Keep first contact brisk even with the straight-line transfer model.
    # The earlier ellipse transit had a shorter visible leg; the authored
    # defaults below preserve the same tutorial pacing without hard-coding it
    # into the Level 1 generator.
    level_one_enemy_star_distance_multiplier: float = 1.2
    level_one_enemy_approach_delay_seconds: float = 0.0
    level_two_player_orbit_radius: float = 120.0
    level_two_player_orbit_velocity: float = 20.0
    level_two_enemy_orbit_radius: float = 45.0
    level_two_enemy_star_life_multiplier: float = 100.0
    level_two_cluster_star_life: float = 1_000.0
    level_two_cluster_blast_radius: float = 315.0
    level_two_chain_blast_radius: float = 520.0
    level_two_enemy_ship_radar_radius: float = 110.0
    level_two_enemy_star_fire_interval: float = 5.0
    level_two_enemy_star_gun_damage: float = 75.0

    @classmethod
    def from_environment(cls, universe: UniverseGenerationConfig) -> "CareerGenerationConfig":
        config = cls(
            level_one_star_count=int(os.getenv("CAREER_LEVEL_1_STAR_COUNT", "5")),
            level_one_radar_radius=float(os.getenv("CAREER_LEVEL_1_RADAR_RADIUS", str(universe.star_distance_target))),
            level_one_enemy_orbit_radius=float(os.getenv("CAREER_LEVEL_1_ENEMY_ORBIT_RADIUS", "120")),
            level_one_enemy_star_distance_multiplier=float(os.getenv("CAREER_LEVEL_1_ENEMY_STAR_DISTANCE_MULTIPLIER", "1.2")),
            level_one_near_miss_distance=float(os.getenv("CAREER_LEVEL_1_NEAR_MISS_DISTANCE", "50")),
            level_one_player_orbit_radius=float(os.getenv("CAREER_LEVEL_1_PLAYER_ORBIT_RADIUS", str(universe.ship_orbit_radius * 1.5))),
            level_one_player_orbit_velocity=float(os.getenv("CAREER_LEVEL_1_PLAYER_ORBIT_VELOCITY", str(universe.ship_orbit_velocity * 2))),
            level_one_enemy_orbit_velocity=float(os.getenv("CAREER_LEVEL_1_ENEMY_ORBIT_VELOCITY", "50")),
            level_one_enemy_approach_delay_seconds=float(os.getenv("CAREER_LEVEL_1_ENEMY_APPROACH_DELAY_SECONDS", "0")),
            level_two_player_orbit_radius=float(os.getenv("CAREER_LEVEL_2_PLAYER_ORBIT_RADIUS", "120")),
            level_two_player_orbit_velocity=float(os.getenv("CAREER_LEVEL_2_PLAYER_ORBIT_VELOCITY", str(universe.ship_orbit_velocity))),
            level_two_enemy_orbit_radius=float(os.getenv("CAREER_LEVEL_2_ENEMY_ORBIT_RADIUS", "45")),
            level_two_enemy_star_life_multiplier=float(os.getenv("CAREER_LEVEL_2_ENEMY_STAR_LIFE_MULTIPLIER", "100")),
            level_two_cluster_star_life=float(os.getenv("CAREER_LEVEL_2_CLUSTER_STAR_LIFE", str(universe.star_life))),
            level_two_cluster_blast_radius=float(os.getenv("CAREER_LEVEL_2_CLUSTER_BLAST_RADIUS", "315")),
            level_two_chain_blast_radius=float(os.getenv("CAREER_LEVEL_2_CHAIN_BLAST_RADIUS", "520")),
            level_two_enemy_ship_radar_radius=float(os.getenv("CAREER_LEVEL_2_ENEMY_SHIP_RADAR_RADIUS", "110")),
            level_two_enemy_star_fire_interval=float(os.getenv("CAREER_LEVEL_2_ENEMY_STAR_FIRE_INTERVAL", "5")),
            level_two_enemy_star_gun_damage=float(os.getenv("CAREER_LEVEL_2_ENEMY_STAR_GUN_DAMAGE", "75")),
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
        if self.level_one_player_orbit_radius <= 0 or self.level_one_player_orbit_velocity <= 0 or self.level_one_enemy_orbit_radius <= 0 or self.level_one_enemy_orbit_velocity <= 0 or self.level_one_enemy_star_distance_multiplier <= 0 or self.level_one_enemy_approach_delay_seconds < 0:
            raise ValueError("Career Level 1 orbit settings must be positive.")
        if min(self.level_two_player_orbit_radius, self.level_two_player_orbit_velocity, self.level_two_enemy_orbit_radius, self.level_two_enemy_star_life_multiplier, self.level_two_cluster_star_life, self.level_two_cluster_blast_radius, self.level_two_chain_blast_radius, self.level_two_enemy_ship_radar_radius, self.level_two_enemy_star_fire_interval, self.level_two_enemy_star_gun_damage) <= 0:
            raise ValueError("Career Level 2 settings must be positive.")
