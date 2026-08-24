from __future__ import annotations

import os

import sentry_sdk


def initialize_sentry() -> None:
    """Configure Sentry once for this Flask worker, when a DSN is supplied."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return
    environment = os.getenv("SENTRY_ENVIRONMENT", "development").strip() or "development"
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=os.getenv("SENTRY_RELEASE", "local").strip() or "local",
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "1.0")),
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", "flask")
