import math
import unittest

from simulation.orbit import advance_phase, ellipse_position


class OrbitTests(unittest.TestCase):
    def test_circle_advances_by_linear_distance(self):
        phase = advance_phase(0, velocity=10, seconds=1, semi_major_axis=100, semi_minor=100, direction=1)
        self.assertTrue(math.isclose(phase, 0.1, rel_tol=1e-6))


    def test_ellipse_position_at_phase_zero_is_major_axis_from_centre(self):
        curve = {"major_axis": 100, "eccentricity": 0.5, "rotation": 0}
        position = ellipse_position({"x": 50, "y": 0}, curve, 0)
        self.assertEqual(position, {"x": 100.0, "y": 0.0})
