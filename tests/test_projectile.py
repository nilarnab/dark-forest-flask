import unittest

from simulation.projectile import build_projectile
from simulation.movement import position_for_object_at_time
from simulation.universe import apply_projectile_cleanup, apply_projectile_processing, updates_for_universe


class ProjectileTests(unittest.TestCase):
    def test_projectile_uses_a_straight_line_curve(self):
        projectile = build_projectile({"location": {"x": 10, "y": 20}}, 5, 0, 100, 500, blast_impact=50)
        curve = projectile["curves"]["0"]
        self.assertEqual(projectile["type"], "ARTIFICIAL")
        self.assertEqual(projectile["sub_type"], "PROJECTILE")
        self.assertEqual(projectile["life"], 0)
        self.assertEqual(projectile["max_life"], 0)
        self.assertEqual(projectile["blast_impact"], 50)
        self.assertEqual(curve["type"], "STRAIGHT_LINE")
        self.assertEqual(curve["valid_till"], 10)

    def test_cleanup_deletes_projectile_after_retention_window(self):
        projectile = build_projectile({"location": {"x": 10, "y": 20}}, 5, 0, 100, 100, blast_impact=50)
        universe = {"time": 5.5, "objects": {"shot": projectile}}
        self.assertFalse(apply_projectile_processing(universe, 5.5, 6.5))
        self.assertIn("shot", universe["objects"])
        self.assertTrue(apply_projectile_cleanup(universe, projectile["delete_at"]))
        self.assertNotIn("shot", universe["objects"])

    def test_cleanup_prunes_old_projectile_hit_events(self):
        universe = {
            "objects": {},
            "events": {
                "old": {"type": "PROJECTILE_HIT", "hit_time": 10},
                "recent": {"type": "PROJECTILE_HIT", "hit_time": 19},
            },
        }
        self.assertTrue(apply_projectile_cleanup(universe, 20, hit_event_retention_seconds=10))
        self.assertNotIn("old", universe["events"])
        self.assertIn("recent", universe["events"])

    def test_worker_does_not_rewrite_live_projectile_location(self):
        projectile = build_projectile({"location": {"x": 10, "y": 20}}, 5, 0, 100, 500, blast_impact=50)
        updates = updates_for_universe("u1", {"time": 5, "objects": {"shot": projectile}}, 1)
        self.assertNotIn("universes/u1/objects/shot/location", updates)

    def test_worker_records_first_projectile_hit_and_deletes_shot(self):
        projectile = build_projectile({"location": {"x": 0, "y": 0}}, 0, 0, 100, 500, "ship", blast_impact=50)
        universe = {
            "time": 0,
            "objects": {
                "ship": {"location": {"x": 0, "y": 0}},
                "target": {"location": {"x": 50, "y": 0}, "life": 40},
                "shot": projectile,
            },
        }
        self.assertTrue(apply_projectile_processing(universe, 0, 1))
        self.assertNotIn("shot", universe["objects"])
        event = next(value for key, value in universe["events"].items() if key.startswith("hit_shot_"))
        self.assertEqual(event["target_id"], "target")
        self.assertEqual(event["blast_impact"], 50)
        self.assertEqual(event["life_before"], 40)
        self.assertEqual(event["life_after"], 0)
        self.assertNotIn("target", universe["objects"])

    def test_destroyed_star_becomes_dead_star_instead_of_being_removed(self):
        projectile = build_projectile({"location": {"x": 0, "y": 0}}, 0, 0, 100, 500, "ship", blast_impact=50)
        universe = {
            "time": 0,
            "objects": {
                "ship": {"location": {"x": 0, "y": 0}},
                "star": {"type": "NATURAL", "sub_type": "STAR", "location": {"x": 50, "y": 0}, "life": 40},
                "shot": projectile,
            },
        }

        self.assertTrue(apply_projectile_processing(universe, 0, 1))
        self.assertIn("star", universe["objects"])
        self.assertEqual(universe["objects"]["star"]["sub_type"], "DEAD_STAR")
        self.assertEqual(universe["objects"]["star"]["life"], 0)

    def test_position_reconstruction_can_move_backwards_from_phase_timestamp(self):
        object_data = {
            "location": {"x": 0, "y": 10},
            "curves": {"0": {
                "type": "ELLIPSE", "active": True, "focus1": "star", "major_axis": 10,
                "eccentricity": 0, "rotation": 0, "phase": 1.5707963267948966,
                "phase_updated_at": 10, "velocity": 10, "direction": 1, "valid_till": -1,
            }},
        }
        position = position_for_object_at_time(object_data, {"star": {"location": {"x": 0, "y": 0}}}, 9)
        self.assertIsNotNone(position)
        self.assertGreater(position["x"], 0)
