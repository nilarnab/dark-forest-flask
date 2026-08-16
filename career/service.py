from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from career.config import CareerGenerationConfig
from career.levels.level_1 import AGENT_USER_ID, create_level_one_universe, ensure_level_one_ship_radars, ensure_level_one_star_count
from firebase.client import root_reference
from schema.factories import new_agent_user, new_pending_human_user
from universe_factory.config import UniverseGenerationConfig


GUEST_USER_PATTERN = re.compile(r"^guest_user_[0-9a-f]{32}$")


class CareerInviteError(ValueError):
    pass


@dataclass(frozen=True)
class CareerInviteResult:
    user_id: str
    universe_id: str
    created: bool


def create_or_resume_level_one_invite(
    guest_user_id: Any,
    universe_config: UniverseGenerationConfig,
    career_config: CareerGenerationConfig,
    reset_existing: bool = False,
) -> CareerInviteResult:
    user_id = guest_user_id if isinstance(guest_user_id, str) and GUEST_USER_PATTERN.fullmatch(guest_user_id) else f"guest_user_{uuid.uuid4().hex}"
    users_reference = root_reference().child("users")
    universes_reference = root_reference().child("universes")
    existing = users_reference.child(user_id).get()
    if not reset_existing and isinstance(existing, dict) and isinstance(existing.get("career_universe"), str):
        existing_universe_id = existing["career_universe"]
        existing_universe = universes_reference.child(existing_universe_id).get()
        if isinstance(existing_universe, dict):
            # Restrict the top-up transaction to this one universe. A root
            # transaction repeatedly conflicts with unrelated game writes.
            def upgrade(value: Any):
                if isinstance(value, dict):
                    ensure_level_one_star_count(value, universe_config, career_config)
                    ensure_level_one_ship_radars(value, career_config)
                return value
            universes_reference.child(existing_universe_id).transaction(upgrade)
            return CareerInviteResult(user_id=user_id, universe_id=existing_universe_id, created=False)

    previous_universe_id = existing.get("career_universe") if reset_existing and isinstance(existing, dict) else None
    for _ in range(20):
        universe_id, universe, membership = create_level_one_universe(user_id, universe_config, career_config)
        def claim(current: Any):
            return universe if current is None else current
        claimed = universes_reference.child(universe_id).transaction(claim)
        if not isinstance(claimed, dict) or claimed.get("career_owner") != user_id:
            continue

        chosen = {"universe_id": universe_id, "created": True}
        def attach(current: Any):
            user = current if isinstance(current, dict) else new_pending_human_user()
            current_universe_id = user.get("career_universe")
            if not reset_existing and isinstance(current_universe_id, str):
                chosen.update(universe_id=current_universe_id, created=False)
                return user
            memberships = user.setdefault("universe_memberships", {})
            if not isinstance(memberships, dict):
                memberships = {}
                user["universe_memberships"] = memberships
            if isinstance(current_universe_id, str):
                memberships.pop(current_universe_id, None)
            user["career_universe"] = universe_id
            memberships[universe_id] = membership
            return user
        users_reference.child(user_id).transaction(attach)
        users_reference.child(AGENT_USER_ID).transaction(lambda current: current if isinstance(current, dict) else new_agent_user(AGENT_USER_ID))
        if chosen["universe_id"] != universe_id:
            universes_reference.child(universe_id).delete()
            existing_universe = universes_reference.child(str(chosen["universe_id"])).get()
            if isinstance(existing_universe, dict):
                ensure_level_one_star_count(existing_universe, universe_config, career_config)
                ensure_level_one_ship_radars(existing_universe, career_config)
                universes_reference.child(str(chosen["universe_id"])).set(existing_universe)
            return CareerInviteResult(user_id=user_id, universe_id=str(chosen["universe_id"]), created=False)
        if isinstance(previous_universe_id, str) and previous_universe_id != universe_id:
            # The new career pointer is already committed. Removing the old
            # personal universe afterward cannot strand this guest.
            universes_reference.child(previous_universe_id).delete()
        return CareerInviteResult(user_id=user_id, universe_id=universe_id, created=True)
    raise CareerInviteError("Could not allocate a Level 1 universe. Please retry.")
