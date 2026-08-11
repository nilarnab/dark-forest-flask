import math
import random
import unittest

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
