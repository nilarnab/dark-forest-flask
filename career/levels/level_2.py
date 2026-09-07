from __future__ import annotations

import math
import random
import uuid

from career.config import CareerGenerationConfig
from career.levels.level_1 import AGENT_USER_ID
from schema.factories import new_empty_universe, new_gun, new_membership, new_star
from schema.models import UniverseRecord
from universe_factory.config import UniverseGenerationConfig
from universe_factory.generator import create_ship, mount_gun, mount_radar, spawn_config


LEVEL_NUMBER = 2
AGENT_INSTANCE_ID = "agent_level_2_avoidant"


def create_level_two_universe(user_id: str, config: UniverseGenerationConfig, career: CareerGenerationConfig, seed: int | None = None) -> tuple[str, UniverseRecord, dict]:
    """Build the deterministic Level 2 blast-chain star chart."""
    rng = random.Random(seed)
    universe_id = str(rng.randrange(1000, 10_000))
    universe = new_empty_universe(spawn_config(config), active=False)
    universe.update({
        "name": f"CAREER_2_{universe_id}", "career": True, "career_owner": user_id,
        "darkforest": True, "career_level": LEVEL_NUMBER,
        "career_state": {
            "current_step": "level_2",
            "status": "BRIEFING",
            "opening_briefing": {
                "step": 0,
                "completed": False,
                "messages": [
                    "INTEL: THE ENEMY HAS 1 SHIP, AND IT IS NOT IN ORBIT OF ITS HOME STAR.",
                    "WHEN YOU HOVER OVER A STAR, THE RED CIRCLE SHOWS THE BLAST RADIUS OF ITS SUPERNOVA IF IT IS DESTROYED.",
                ],
            },
        },
        "participants": {user_id: {"type": "HUMAN"}, AGENT_USER_ID: {"type": "AGENT"}},
        "agent_state": {AGENT_INSTANCE_ID: {"agent_name": "avoidant", "active": True, "mode": "ORBITING", "ship_id": ""}},
    })
    objects = universe["objects"]
    # The chart is deliberately broad and irregular. The enemy staging orbit
    # remains outside the restored, normal player-star radar at mission start.
    player_star_id = f"star_player_{uuid.uuid4().hex}"
    enemy_staging_star_id = f"star_enemy_staging_{uuid.uuid4().hex}"
    enemy_home_star_id = f"star_enemy_home_{uuid.uuid4().hex}"
    objects[player_star_id] = new_star({"x": -190.0, "y": -125.0}, config.star_life, config.star_border_radius)
    objects[player_star_id]["owner"] = user_id
    objects[player_star_id]["objects"] = {f"radar_{uuid.uuid4().hex}": {"type": "RADAR", "radius": config.radar_radius}}
    objects[enemy_staging_star_id] = new_star({"x": -700.0, "y": 150.0}, config.star_life, config.star_border_radius)
    objects[enemy_home_star_id] = new_star({"x": 1780.0, "y": -200.0}, config.star_life * career.level_two_enemy_star_life_multiplier, config.star_border_radius)
    objects[enemy_home_star_id]["owner"] = AGENT_USER_ID
    objects[enemy_home_star_id]["max_life"] = objects[enemy_home_star_id]["life"]

    # This deterministic scatter avoids an artificial row/grid appearance.
    # Each star is still within one blast hop of the graph, so a detonation at
    # any connected node eventually destroys the complete cluster.
    cluster_positions = [
        (160.0, 190.0), (390.0, 285.0), (610.0, 120.0), (850.0, 300.0),
        (1080.0, 95.0), (1320.0, 255.0), (1510.0, 40.0), (370.0, -25.0),
        (650.0, -130.0), (920.0, -80.0), (1190.0, -115.0), (1480.0, -20.0),
    ]
    cluster_ids: list[str] = []
    for index, (x, y) in enumerate(cluster_positions):
        star_id = f"star_cluster_{index}_{uuid.uuid4().hex}"
        objects[star_id] = new_star({"x": x, "y": y}, career.level_two_cluster_star_life, config.star_border_radius)
        objects[star_id]["death_blast_radius"] = career.level_two_cluster_blast_radius
        objects[star_id]["death_blast_damage"] = career.level_two_enemy_star_life_multiplier * config.star_life
        cluster_ids.append(star_id)
    chain_star_id = cluster_ids[0]
    objects[chain_star_id]["death_blast_radius"] = career.level_two_chain_blast_radius

    player_ship_id = create_ship(universe, player_star_id, config, rng, user_id,
        orbit_radius=career.level_two_player_orbit_radius, velocity=career.level_two_player_orbit_velocity,
        phase=math.pi / 3, object_id=f"ship_player_{uuid.uuid4().hex}")
    mount_gun(universe, player_ship_id, config.gun_velocity, config.gun_hit_radius, config.gun_range)
    mount_radar(universe, player_ship_id, config.radar_radius / 2)
    enemy_ship_id = create_ship(universe, enemy_staging_star_id, config, rng, AGENT_USER_ID,
        orbit_radius=career.level_two_enemy_orbit_radius, velocity=career.level_two_player_orbit_velocity * .75,
        phase=math.pi, object_id=f"ship_enemy_{uuid.uuid4().hex}")
    mount_gun(universe, enemy_ship_id, config.gun_velocity, config.gun_hit_radius, config.gun_range)
    # Half the player firing rate means twice the cooldown.
    enemy_gun = next(iter(objects[enemy_ship_id]["objects"].values()))
    enemy_gun["cooldown_seconds"] = 2.0
    mount_radar(universe, enemy_ship_id, career.level_two_enemy_ship_radar_radius)
    objects[enemy_home_star_id]["objects"] = {
        f"gun_{uuid.uuid4().hex}": new_gun(config.gun_velocity, config.gun_hit_radius, config.gun_range, career.level_two_enemy_star_fire_interval),
    }
    objects[enemy_home_star_id]["objects"][next(iter(objects[enemy_home_star_id]["objects"]))]["blast_impact"] = career.level_two_enemy_star_gun_damage
    universe["agent_state"][AGENT_INSTANCE_ID]["ship_id"] = enemy_ship_id
    universe["career_state"].update({
        "level_two_player_star_id": player_star_id, "level_two_player_ship_id": player_ship_id,
        "level_two_enemy_ship_id": enemy_ship_id, "level_two_enemy_staging_star_id": enemy_staging_star_id,
        "level_two_enemy_home_star_id": enemy_home_star_id, "level_two_cluster_target_id": cluster_ids[-1],
        "level_two_intel_sent": False,
    })
    return universe_id, universe, new_membership(player_star_id, [player_ship_id], 0, universe_type="CAREER")
