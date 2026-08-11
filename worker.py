from __future__ import annotations

import logging

from config import Settings
from firebase.client import initialize_firebase
from firebase.repository import UniverseRepository
from simulation.runner import SimulationRunner


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_environment()
    if not settings.simulation_enabled:
        raise SystemExit("SIMULATION_ENABLED is false; worker will not start.")
    initialize_firebase(settings)
    SimulationRunner(UniverseRepository(), settings.tick_seconds).run_forever()
