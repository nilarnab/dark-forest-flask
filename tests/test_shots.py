import unittest

from simulation.shots import prepare_shot


class ShotTests(unittest.TestCase):
    def test_legacy_gun_uses_its_universe_configured_range(self):
        universe = {
            "time": 10,
            "time_updated_at_ms": 0,
            "spawn_config": {"gun_range": 400},
            "objects": {
                "ship": {
                    "type": "ARTIFICIAL",
                    "location": {"x": 0, "y": 0},
                    "objects": {"gun": {"type": "GUN", "velocity": 100, "hit_radius": 20}},
                },
            },
        }
        shot = prepare_shot(
            "u1", universe, "ship", "gun", 0,
            projectile_range=1000, projectile_blast_impact=50,
            projectile_retention_seconds=10, now_ms=0,
        )
        projectile = shot.updates[f"universes/u1/objects/{shot.projectile_id}"]
        self.assertEqual(projectile["curves"]["0"]["valid_till"], 14)

