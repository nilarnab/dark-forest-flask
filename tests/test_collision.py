import unittest

from simulation.collision import verify_and_apply_collision


class CollisionTests(unittest.TestCase):
    def test_verified_contact_uses_mutual_life_damage_and_removes_destroyed_object(self):
        universe = {
            "objects": {
                "ship": {"location": {"x": 0, "y": 0}, "life": 200, "border_radius": 2},
                "star": {"location": {"x": 1, "y": 0}, "life": 1000, "border_radius": 2},
            },
        }

        result = verify_and_apply_collision(universe, "ship", "star", 0)

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["damage"], 200)
        self.assertNotIn("ship", universe["objects"])
        self.assertEqual(universe["objects"]["star"]["life"], 800)

    def test_blast_impact_can_raise_the_mutual_damage(self):
        universe = {
            "objects": {
                "mine": {"location": {"x": 0, "y": 0}, "life": 20, "blast_impact": 50, "border_radius": 2},
                "ship": {"location": {"x": 1, "y": 0}, "life": 200, "border_radius": 2},
            },
        }

        result = verify_and_apply_collision(universe, "mine", "ship", 0)

        self.assertEqual(result["damage"], 50)
        self.assertNotIn("mine", universe["objects"])
        self.assertEqual(universe["objects"]["ship"]["life"], 150)
