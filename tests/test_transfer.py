import math
import unittest

from simulation.transfer import ManeuverBlockedError, TransferError, apply_transfer_plan, build_transfer_plan
from simulation.universe import updates_for_universe


def universe_fixture():
    return {
        "time": 10,
        "objects": {
            "starA": {"location": {"x": 0, "y": 0}},
            "starB": {"location": {"x": 1000, "y": 0}},
            "ship": {
                "location": {"x": 100, "y": 0},
                "curves": [{
                    "active": True,
                    "focus1": "starA",
                    "major_axis": 100,
                    "eccentricity": 0,
                    "rotation": 0,
                    "velocity": 100,
                    "direction": 1,
                    "phase": 0,
                    "valid_till": -1,
                }],
            },
        },
    }


class TransferTests(unittest.TestCase):
    def test_pending_maneuver_blocks_another_transfer(self):
        universe = universe_fixture()
        universe["objects"]["ship"]["maneuver_blocked_till"] = 20
        with self.assertRaises(ManeuverBlockedError):
            build_transfer_plan(universe, "ship", "starB", 200)

    def test_same_focus_uses_direct_hohmann_transfer(self):
        universe = universe_fixture()
        plan = build_transfer_plan(universe, "ship", "starA", 200)
        curve = plan.transfer_curve
        self.assertEqual(curve["motion_type"], "HOHMANN_TRANSFER")
        self.assertEqual(curve["focus1"], "starA")
        self.assertEqual(curve["major_axis"], 150)
        self.assertAlmostEqual(curve["eccentricity"], 1 / 3)
        self.assertGreater(plan.arrival_time, plan.start_time)

    def test_plan_creates_transfer_and_destination_circle(self):
        universe = universe_fixture()
        plan = build_transfer_plan(universe, "ship", "starB", 200)
        self.assertEqual(plan.transfer_curve["motion_type"], "INTERSTELLAR_ELLIPSE")
        self.assertIn("basis_u", plan.transfer_curve)
        self.assertIn("basis_v", plan.transfer_curve)
        self.assertEqual(plan.destination_curve["focus1"], "starB")
        self.assertEqual(plan.destination_curve["major_axis"], 200)
        self.assertEqual(plan.destination_curve["direction"], -1)
        self.assertGreater(plan.arrival_time, plan.start_time)

        updated = apply_transfer_plan(universe, plan)
        curves = updated["objects"]["ship"]["curves"]
        self.assertGreater(curves[0]["valid_till"], 10.0)
        self.assertTrue(curves[0]["active"])
        self.assertEqual(curves[1]["valid_from"], plan.start_time)
        self.assertEqual(curves[2]["valid_from"], plan.arrival_time)

    def test_tick_uses_destination_curve_after_transfer_arrival(self):
        universe = universe_fixture()
        plan = build_transfer_plan(universe, "ship", "starB", 200)
        apply_transfer_plan(universe, plan)
        universe["time"] = math.ceil(plan.arrival_time)
        updates = updates_for_universe("u1", universe, 1)
        destination_key = plan.destination_curve_key
        self.assertIn(f"universes/u1/objects/ship/curves/{destination_key}/phase", updates)

    def test_rejects_transfer_arc_that_enters_another_star(self):
        universe = universe_fixture()
        universe["objects"]["ship"]["border_radius"] = 2
        universe["objects"]["starBlock"] = {
            "type": "NATURAL",
            "border_radius": 2,
            # Midpoint of the outward Hohmann half-ellipse for r=100 → 200.
            "location": {"x": -50, "y": 141.4213562373095},
        }
        with self.assertRaisesRegex(TransferError, "star starBlock"):
            build_transfer_plan(universe, "ship", "starA", 200)
