from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from career.config import CareerGenerationConfig
from career.levels.level_1 import AGENT_USER_ID, create_level_one_universe, ensure_level_one_ship_radars, ensure_level_one_star_count
from career.levels.level_2 import create_level_two_universe
from firebase.client import root_reference
from schema.factories import new_agent_user, new_pending_human_user
from universe_factory.config import UniverseGenerationConfig


GUEST_USER_PATTERN = re.compile(r"^guest_user_[0-9a-f]{32}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


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
    account_user_id: Any = None,
) -> CareerInviteResult:
    users_reference = root_reference().child("users")
    universes_reference = root_reference().child("universes")
    if account_user_id is not None:
        if not isinstance(account_user_id, str) or not USERNAME_PATTERN.fullmatch(account_user_id):
            raise CareerInviteError("Invalid saved username.")
        user_id = account_user_id
        existing = users_reference.child(user_id).get()
        if not isinstance(existing, dict) or existing.get("type") != "HUMAN":
            raise CareerInviteError("Saved account is unavailable.")
    else:
        user_id = guest_user_id if isinstance(guest_user_id, str) and GUEST_USER_PATTERN.fullmatch(guest_user_id) else f"guest_user_{uuid.uuid4().hex}"
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
    agent_user = users_reference.child(AGENT_USER_ID).get()
    for _ in range(20):
        universe_id, universe, membership = create_level_one_universe(user_id, universe_config, career_config)
        # Universe ids are only four digits, so keep the small collision
        # check—but avoid a full-universe transaction.  A Level 1 reset used
        # to make four sequential Firebase transactions, which can stall for
        # several seconds on Render while any transaction retries.
        if universes_reference.child(universe_id).get() is not None:
            continue

        updates: dict[str, Any] = {
            f"universes/{universe_id}": universe,
            f"users/{user_id}/career_universe": universe_id,
            f"users/{user_id}/universe_memberships/{universe_id}": membership,
        }
        if not isinstance(agent_user, dict):
            updates[f"users/{AGENT_USER_ID}"] = new_agent_user(AGENT_USER_ID)
        if isinstance(previous_universe_id, str) and previous_universe_id != universe_id:
            # Creation, pointer swap, and old-universe deletion are one
            # atomic Firebase update; no follow-up request can leave the UI
            # waiting after the new career is already ready.
            updates[f"users/{user_id}/universe_memberships/{previous_universe_id}"] = None
            updates[f"universes/{previous_universe_id}"] = None
        root_reference().update(updates)
        return CareerInviteResult(user_id=user_id, universe_id=universe_id, created=True)
    raise CareerInviteError("Could not allocate a Level 1 universe. Please retry.")


def create_or_resume_level_two_invite(
    account_user_id: str, universe_config: UniverseGenerationConfig, career_config: CareerGenerationConfig,
    reset_existing: bool = False,
) -> CareerInviteResult:
    """Create the next career mission only for an authenticated Level 1 winner."""
    users_reference = root_reference().child("users")
    universes_reference = root_reference().child("universes")
    account = users_reference.child(account_user_id).get()
    if not isinstance(account, dict) or account.get("type") != "HUMAN":
        raise CareerInviteError("Saved account is unavailable.")
    prior_id = account.get("career_universe")
    prior = universes_reference.child(prior_id).get() if isinstance(prior_id, str) else None
    previous_universe_id = prior_id if reset_existing and isinstance(prior, dict) and prior.get("career_level") == 2 else None
    if not reset_existing and isinstance(prior, dict) and prior.get("career_level") == 2:
        return CareerInviteResult(account_user_id, prior_id, False)
    # Accounts created after a guest victory can have an older/incomplete
    # career pointer while their successfully claimed Level 1 remains in the
    # membership map. Prefer the completed account-owned mission in that
    # case; it is the only valid source for opening Level 2.
    if not (isinstance(prior, dict) and prior.get("career_level") == 1 and isinstance(prior.get("career_state"), dict) and prior["career_state"].get("level_completed") is True):
        memberships = account.get("universe_memberships")
        if isinstance(memberships, dict):
            for candidate_id in memberships:
                if not isinstance(candidate_id, str):
                    continue
                candidate = universes_reference.child(candidate_id).get()
                if isinstance(candidate, dict) and candidate.get("career") is True and candidate.get("career_level") == 1 and candidate.get("career_owner") == account_user_id and isinstance(candidate.get("career_state"), dict) and candidate["career_state"].get("level_completed") is True:
                    prior_id, prior = candidate_id, candidate
                    break
    if not isinstance(prior, dict) or prior.get("career_level") != 1 or not isinstance(prior.get("career_state"), dict) or prior["career_state"].get("level_completed") is not True:
        raise CareerInviteError("Complete Level 1 before entering Level 2.")
    agent_user = users_reference.child(AGENT_USER_ID).get()
    for _ in range(20):
        universe_id, universe, membership = create_level_two_universe(account_user_id, universe_config, career_config)
        if universes_reference.child(universe_id).get() is not None:
            continue
        updates: dict[str, Any] = {
            f"universes/{universe_id}": universe,
            f"users/{account_user_id}/career_universe": universe_id,
            f"users/{account_user_id}/universe_memberships/{universe_id}": membership,
        }
        if isinstance(previous_universe_id, str) and previous_universe_id != universe_id:
            updates[f"users/{account_user_id}/universe_memberships/{previous_universe_id}"] = None
            updates[f"universes/{previous_universe_id}"] = None
        if not isinstance(agent_user, dict):
            updates[f"users/{AGENT_USER_ID}"] = new_agent_user(AGENT_USER_ID)
        root_reference().update(updates)
        return CareerInviteResult(account_user_id, universe_id, True)
    raise CareerInviteError("Could not allocate a Level 2 universe. Please retry.")
