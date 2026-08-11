from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from firebase.client import root_reference
from schema.factories import new_human_user
from universe_factory.config import UniverseGenerationConfig
from universe_factory.generator import create_universe
from universe_factory.onboarding import OnboardingError, onboard_user
from werkzeug.security import check_password_hash, generate_password_hash


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthenticationResult:
    username: str
    account_type: str
    action: str


@dataclass(frozen=True)
class UniverseCreationResult:
    universe_id: str


@dataclass(frozen=True)
class UniverseEntryResult:
    universe_id: str
    onboarded: bool
    star_id: str
    ship_ids: dict[str, str]


def authenticate_human(username: Any, password: Any) -> AuthenticationResult:
    """Log an existing human in, or atomically create a new human account."""
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise AuthenticationError("Username must be 3–32 characters using letters, numbers, _ or -.")
    if not isinstance(password, str) or len(password) < 6:
        raise AuthenticationError("Password must contain at least 6 characters.")

    result: dict[str, str] = {}

    def authenticate(existing: Any):
        if existing is None:
            result.update(username=username, account_type="HUMAN", action="signup")
            return new_human_user(username, generate_password_hash(password))
        if not isinstance(existing, dict):
            raise AuthenticationError("This username is unavailable.")
        stored_password = existing.get("password")
        if not isinstance(stored_password, str) or not check_password_hash(stored_password, password):
            raise AuthenticationError("Incorrect password.")
        result.update(
            username=str(existing.get("username") or username),
            account_type=str(existing.get("type") or "HUMAN"),
            action="login",
        )
        return existing

    root_reference().child("users").child(username).transaction(authenticate)
    return AuthenticationResult(**result)


def create_universe_for_user(username: Any, config: UniverseGenerationConfig) -> UniverseCreationResult:
    """Atomically create a generated universe; membership is created on entry."""
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise AuthenticationError("Invalid logged-in username.")
    # A four-digit code has only 9,000 usable values, so retry a collision
    # rather than making the player choose another code themselves.
    for _ in range(20):
        universe_id, generated_universe = create_universe(config)
        created = {"value": False}

        def create(root: Any):
            if not isinstance(root, dict):
                root = {}
            users = root.setdefault("users", {})
            universes = root.setdefault("universes", {})
            user = users.get(username) if isinstance(users, dict) else None
            if not isinstance(user, dict):
                raise AuthenticationError("Logged-in user no longer exists.")
            if universe_id in universes:
                created["value"] = False
                return root
            universes[universe_id] = generated_universe
            created["value"] = True
            return root

        root_reference().transaction(create)
        if created["value"]:
            return UniverseCreationResult(universe_id=universe_id)
    raise AuthenticationError("Could not allocate an unused four-digit universe ID. Please retry.")


def enter_universe_for_user(username: Any, universe_id: Any, config: UniverseGenerationConfig) -> UniverseEntryResult:
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise AuthenticationError("Invalid logged-in username.")
    if not isinstance(universe_id, str) or not universe_id:
        raise AuthenticationError("A universe ID is required.")
    result: dict[str, Any] = {}

    def enter(root: Any):
        if not isinstance(root, dict):
            raise AuthenticationError("Database is unavailable.")
        users, universes = root.get("users"), root.get("universes")
        user = users.get(username) if isinstance(users, dict) else None
        universe = universes.get(universe_id) if isinstance(universes, dict) else None
        if not isinstance(user, dict):
            raise AuthenticationError("Logged-in user no longer exists.")
        if not isinstance(universe, dict):
            raise AuthenticationError("Universe does not exist.")
        memberships = user.setdefault("universe_memberships", {})
        if not isinstance(memberships, dict):
            memberships = {}
            user["universe_memberships"] = memberships
        existing = memberships.get(universe_id)
        if isinstance(existing, dict) and existing.get("onboarded") is True:
            result.update(onboarded=False, membership=existing)
            return root
        try:
            membership = onboard_user(universe, username, config, float(universe.get("time", 0)))
        except OnboardingError as error:
            raise AuthenticationError(str(error)) from error
        memberships[universe_id] = membership
        result.update(onboarded=True, membership=membership)
        return root

    root_reference().transaction(enter)
    membership = result["membership"]
    return UniverseEntryResult(universe_id, bool(result["onboarded"]), membership["star_id"], membership["ship_ids"])
