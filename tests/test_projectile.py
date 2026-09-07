import unittest

from simulation.projectile import build_projectile
from simulation.movement import position_for_object_at_time
from simulation.universe import apply_projectile_cleanup, apply_projectile_processing, resolve_star_death_blast, updates_for_universe


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

    def test_star_blast_that_kills_another_star_records_cluster_blast_event(self):
        universe = {
            "objects": {
                "source": {
                    "type": "NATURAL", "sub_type": "STAR", "life": 0,
                    "location": {"x": 0, "y": 0}, "death_blast_at": 1,
                    "death_blast_radius": 20, "death_blast_damage": 100,
                },
                "target": {
                    "type": "NATURAL", "sub_type": "STAR", "life": 100,
                    "location": {"x": 10, "y": 0},
                },
            },
        }

        self.assertEqual(resolve_star_death_blast(universe, "source", 1)["status"], "confirmed")
        cluster_events = [event for event in universe["events"].values() if event.get("type") == "CLUSTER_BLAST"]
        self.assertEqual(len(cluster_events), 1)
        self.assertEqual(cluster_events[0]["source_id"], "source")
        self.assertEqual(cluster_events[0]["triggered_star_ids"], ["target"])
        self.assertEqual(universe["objects"]["target"]["death_blast_at"], 2)

    def test_cleanup_does_not_drive_pending_star_blasts(self):
        universe = {
            "objects": {
                "source": {
                    "type": "NATURAL", "life": 0, "location": {"x": 0, "y": 0},
                    "death_blast_at": 1, "death_blast_radius": 20, "death_blast_damage": 100,
                },
                "target": {"type": "NATURAL", "life": 100, "location": {"x": 10, "y": 0}},
            },
        }

        self.assertFalse(apply_projectile_cleanup(universe, 2))
        self.assertEqual(universe["objects"]["target"]["life"], 100)

    def test_client_scheduled_star_blast_is_idempotent_and_announces_chain(self):
        universe = {
            "objects": {
                "source": {
                    "type": "NATURAL", "sub_type": "STAR", "life": 0,
                    "location": {"x": 0, "y": 0}, "death_blast_at": 11,
                    "death_blast_radius": 20, "death_blast_damage": 100,
                },
                "target": {
                    "type": "NATURAL", "sub_type": "STAR", "life": 100,
                    "location": {"x": 10, "y": 0},
                },
            },
            "events": {
                "death": {"type": "STAR_DIED", "star_id": "source", "blast_at": 11, "resolved": False},
            },
        }

        self.assertEqual(resolve_star_death_blast(universe, "source", 10.5)["status"], "not_due")
        result = resolve_star_death_blast(universe, "source", 11)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["triggered_star_ids"], ["target"])
        self.assertTrue(universe["events"]["death"]["resolved"])
        self.assertEqual(universe["objects"]["target"]["death_blast_at"], 12)
        chained_deaths = [event for event in universe["events"].values() if event.get("type") == "STAR_DIED" and event.get("star_id") == "target"]
        self.assertEqual(len(chained_deaths), 1)
        self.assertEqual(resolve_star_death_blast(universe, "source", 12)["status"], "already_resolved")

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
        self.assertEqual(event["source_objectid"], "ship")
        self.assertEqual(event["blast_impact"], 50)
        self.assertEqual(event["life_before"], 40)
        self.assertEqual(event["life_after"], 0)
        self.assertNotIn("target", universe["objects"])

    def test_destroyed_star_stays_visible_and_arms_a_delayed_blast(self):
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
        self.assertEqual(universe["objects"]["star"]["sub_type"], "STAR")
        self.assertEqual(universe["objects"]["star"]["life"], 0)
        hit_time = next(event["hit_time"] for event in universe["events"].values() if event.get("target_id") == "star")
        self.assertAlmostEqual(universe["objects"]["star"]["death_blast_at"], hit_time + 1.0)
        death_event = next(event for event in universe["events"].values() if event.get("type") == "STAR_DIED")
        self.assertEqual(death_event["star_id"], "star")
        self.assertAlmostEqual(death_event["blast_at"], hit_time + 1.0)

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
