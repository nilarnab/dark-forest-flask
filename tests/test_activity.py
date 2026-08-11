import unittest
from unittest.mock import patch

from simulation.activity import UniverseActivityTracker, is_universe_active


class UniverseActivityTrackerTests(unittest.TestCase):
    @patch("simulation.activity.time.monotonic", return_value=100.0)
    def test_touched_universe_is_active(self, _monotonic):
        tracker = UniverseActivityTracker(timeout_seconds=45)
        tracker.touch("u1")
        self.assertEqual(tracker.active_universe_ids(), ["u1"])

    @patch("simulation.activity.time.monotonic", side_effect=[100.0, 146.0])
    def test_stale_universe_is_removed(self, monotonic):
        tracker = UniverseActivityTracker(timeout_seconds=45)
        tracker.touch("u1")
        self.assertEqual(tracker.active_universe_ids(), [])

    def test_universe_requires_explicit_active_true(self):
        self.assertTrue(is_universe_active({"active": True}))
        self.assertFalse(is_universe_active({"active": False}))
        self.assertFalse(is_universe_active({}))
