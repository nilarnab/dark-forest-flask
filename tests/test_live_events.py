import unittest

from simulation.live_events import LiveEventBus


class LiveEventBusTests(unittest.TestCase):
    def test_publishes_to_universe_subscribers_only(self):
        bus = LiveEventBus()
        first = bus.subscribe("u1")
        other = bus.subscribe("u2")

        bus.publish("u1", {"type": "PROJECTILE_FIRED", "projectile_id": "p1"})

        self.assertEqual(first.get_nowait()["projectile_id"], "p1")
        self.assertTrue(other.empty())
