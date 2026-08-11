import unittest

from schema.factories import new_empty_universe, new_human_user


class SchemaFactoryTests(unittest.TestCase):
    def test_new_human_user_matches_schema(self):
        user = new_human_user("pilot_01", "encoded-password")
        self.assertEqual(user["type"], "HUMAN")
        self.assertEqual(user["universe_memberships"], {})

    def test_new_empty_universe_matches_schema(self):
        universe = new_empty_universe({
            "starter_ship_count": 1,
            "ship_orbit_radius": 150,
            "ship_orbit_velocity": 20,
            "gun_velocity": 300,
            "gun_hit_radius": 20,
        })
        self.assertTrue(universe["active"])
        self.assertEqual(universe["time"], 0)
        self.assertEqual(universe["objects"], {})
