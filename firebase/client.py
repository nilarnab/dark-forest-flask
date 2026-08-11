from __future__ import annotations

import firebase_admin
from firebase_admin import credentials, db

from config import Settings


def initialize_firebase(settings: Settings) -> None:
    """Initialize Firebase once per Python process."""
    if firebase_admin._apps:
        return
    if not settings.firebase_database_url:
        raise RuntimeError("FIREBASE_DATABASE_URL must be configured.")

    options = {
        "databaseURL": settings.firebase_database_url,
        # Firebase Admin otherwise waits 120 seconds for a timed-out database
        # request, which stalls the simulation loop for two minutes.
        "httpTimeout": settings.firebase_http_timeout_seconds,
    }
    if settings.firebase_service_account_path:
        credential = credentials.Certificate(str(settings.firebase_service_account_path))
        firebase_admin.initialize_app(credential, options)
    else:
        firebase_admin.initialize_app(options=options)


def root_reference() -> db.Reference:
    return db.reference("/")
