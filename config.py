from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    firebase_database_url: str
    firebase_service_account_path: Path | None
    tick_seconds: float
    firebase_http_timeout_seconds: float
    projectile_speed: float
    projectile_range: float
    projectile_blast_impact: float
    projectile_processing_seconds: float
    projectile_cleanup_seconds: float
    projectile_retention_seconds: float
    hit_event_retention_seconds: float
    hit_distance_tolerance: float
    star_death_blast_radius: float
    star_death_blast_damage: float
    universe_activity_timeout_seconds: float
    client_fire_time_tolerance_seconds: float
    simulation_enabled: bool
    simulation_write_positions: bool
    projectile_processing_enabled: bool
    cors_allowed_origins: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> "Settings":
        credential_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "").strip()
        cors_allowed_origins = tuple(
            origin.strip().rstrip("/")
            for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
            if origin.strip()
        )
        return cls(
            firebase_database_url=os.getenv("FIREBASE_DATABASE_URL", "").strip(),
            firebase_service_account_path=Path(credential_path) if credential_path else None,
            tick_seconds=float(os.getenv("SIMULATION_TICK_SECONDS", "1")),
            firebase_http_timeout_seconds=float(os.getenv("FIREBASE_HTTP_TIMEOUT_SECONDS", "2")),
            projectile_speed=float(os.getenv("PROJECTILE_SPEED", "500")),
            projectile_range=float(os.getenv("PROJECTILE_RANGE", "1000")),
            projectile_blast_impact=float(os.getenv("PROJECTILE_BLAST_IMPACT", "50")),
            projectile_processing_seconds=float(os.getenv("PROJECTILE_PROCESSING_SECONDS", "0.1")),
            projectile_cleanup_seconds=float(os.getenv("PROJECTILE_CLEANUP_SECONDS", "1")),
            projectile_retention_seconds=float(os.getenv("PROJECTILE_RETENTION_SECONDS", "10")),
            hit_event_retention_seconds=float(os.getenv("HIT_EVENT_RETENTION_SECONDS", "10")),
            hit_distance_tolerance=float(os.getenv("HIT_DISTANCE_TOLERANCE", "1")),
            star_death_blast_radius=float(os.getenv("STAR_DEATH_BLAST_RADIUS", "200")),
            star_death_blast_damage=float(os.getenv("STAR_DEATH_BLAST_DAMAGE", "100")),
            universe_activity_timeout_seconds=float(os.getenv("UNIVERSE_ACTIVITY_TIMEOUT_SECONDS", "45")),
            client_fire_time_tolerance_seconds=float(os.getenv("CLIENT_FIRE_TIME_TOLERANCE_SECONDS", "1")),
            simulation_enabled=_as_bool(os.getenv("SIMULATION_ENABLED")),
            # Set true temporarily only when rolling back to the legacy
            # location-writing worker.
            simulation_write_positions=_as_bool(os.getenv("SIMULATION_WRITE_POSITIONS"), False),
            # Clients predict projectile movement and submit an exact hit time
            # to the verifier, so continuous full-universe polling is opt-in.
            projectile_processing_enabled=_as_bool(os.getenv("PROJECTILE_PROCESSING_ENABLED"), False),
            cors_allowed_origins=cors_allowed_origins,
        )
