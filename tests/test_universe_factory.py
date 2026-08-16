import math
import random
import unittest

from career.config import CareerGenerationConfig
from career.levels.level_1 import AGENT_USER_ID, create_level_one_universe
from universe_factory.config import UniverseGenerationConfig
from universe_factory.generator import create_universe, generate_star_locations
from universe_factory.onboarding import onboard_user


class UniverseFactoryTests(unittest.TestCase):
    def setUp(self):
        self.config = UniverseGenerationConfig(star_count=20, star_distance_min=100, star_distance_target=500, star_distance_max=2000)

    def test_generated_universe_has_twenty_natural_stars(self):
        universe_id, universe = create_universe(self.config, seed=123)
        self.assertRegex(universe_id, r"^[0-9]{4}$")
        stars = [object_data for object_data in universe["objects"].values() if object_data.get("sub_type") == "STAR"]
        ships = [object_data for object_data in universe["objects"].values() if object_data.get("sub_type") == "cruise_level_1"]
        self.assertEqual(len(stars), 20)
        self.assertEqual(len(ships), 0)
        self.assertTrue(all(object_data["type"] == "NATURAL" for object_data in stars))
        self.assertTrue(all(star["owner"] is None for star in stars))
        self.assertTrue(all(star["life"] == 1000 for star in stars))
        self.assertTrue(all(star["max_life"] == 1000 for star in stars))
        self.assertEqual(universe["spawn_config"]["starter_ship_count"], 3)

    def test_generated_stars_respect_minimum_spacing(self):
        locations = generate_star_locations(self.config, random.Random(123))
        for index, first in enumerate(locations):
            for second in locations[index + 1:]:
                self.assertGreaterEqual(math.hypot(first["x"] - second["x"], first["y"] - second["y"]), 100)

    def test_first_entry_claims_a_star_and_creates_owned_ships(self):
        config = UniverseGenerationConfig(
            star_count=5,
            star_distance_min=100,
            star_distance_target=500,
            star_distance_max=2000,
            ship_count=2,
        )
        _, universe = create_universe(config, seed=123)

        membership = onboard_user(universe, "pilot_01", config, now=42)

        self.assertTrue(membership["onboarded"])
        self.assertEqual(universe["objects"][membership["star_id"]]["owner"], "pilot_01")
        self.assertEqual(len(membership["ship_ids"]), 2)
        orbit_radii = []
        for ship_id in membership["ship_ids"].values():
            ship = universe["objects"][ship_id]
            self.assertEqual(ship["owner"], "pilot_01")
            self.assertEqual(ship["life"], 200)
            self.assertEqual(ship["max_life"], 200)
            self.assertTrue(any(gun.get("type") == "GUN" for gun in ship["objects"].values()))
            orbit_radii.append(ship["curves"]["0"]["major_axis"])
        self.assertEqual(sorted(orbit_radii), [75, 150])

    def test_level_one_career_universe_has_personal_radar_and_near_miss_enemy_orbit(self):
        career = CareerGenerationConfig(
            level_one_star_count=5,
            level_one_radar_radius=500,
            level_one_enemy_orbit_radius=120,
            level_one_near_miss_distance=50,
            level_one_player_orbit_radius=150,
            level_one_enemy_orbit_velocity=20,
        )
        universe_id, universe, membership = create_level_one_universe("guest_user_" + "a" * 32, self.config, career, seed=123)
        self.assertRegex(universe_id, r"^[0-9]{4}$")
        self.assertTrue(universe["career"])
        self.assertTrue(universe["darkforest"])
        self.assertEqual(universe["career_level"], 1)
        self.assertEqual(universe["name"], f"GUEST_{universe_id}")
        self.assertEqual(universe["participants"][AGENT_USER_ID]["type"], "AGENT")
        self.assertEqual(sum(1 for object_data in universe["objects"].values() if object_data.get("type") == "NATURAL"), 5)
        player_star = universe["objects"][membership["star_id"]]
        self.assertEqual(player_star["owner"], "guest_user_" + "a" * 32)
        self.assertEqual(next(iter(player_star["objects"].values()))["radius"], 500)
        enemy_star = next(object_data for object_data in universe["objects"].values() if object_data.get("type") == "NATURAL" and object_data.get("owner") == AGENT_USER_ID)
        self.assertEqual(enemy_star["location"]["x"], career.level_one_enemy_star_distance_multiplier * self.config.star_distance_target)
        enemy_ship = next(object_data for object_data in universe["objects"].values() if object_data.get("type") == "ARTIFICIAL" and object_data.get("owner") == AGENT_USER_ID)
        self.assertEqual(enemy_ship["curves"]["0"]["major_axis"], 120)
        self.assertGreater(universe["career_state"]["enemy_contact_expected_at"], 0)
        for object_data in universe["objects"].values():
            if object_data.get("type") != "ARTIFICIAL":
                continue
            self.assertTrue(any(attached.get("type") == "RADAR" and attached.get("radius") == 250 for attached in object_data["objects"].values()))
