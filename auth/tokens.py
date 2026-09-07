from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def issue_login_token(username: str, secret: str) -> str:
    return URLSafeTimedSerializer(secret, salt="dark-forest-login").dumps({"username": username})


def authenticated_username(authorization: str | None, secret: str, max_age_seconds: int = 60 * 60 * 24 * 7) -> str | None:
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return None
    try:
        value = URLSafeTimedSerializer(secret, salt="dark-forest-login").loads(authorization[7:], max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    username = value.get("username") if isinstance(value, dict) else None
    return username if isinstance(username, str) else None
