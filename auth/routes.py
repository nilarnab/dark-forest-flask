from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from auth.service import AuthenticationError, authenticate_human, create_universe_for_user, enter_universe_for_user
from career.service import CareerInviteError, create_or_resume_level_one_invite


auth_blueprint = Blueprint("auth", __name__, url_prefix="/auth")


@auth_blueprint.post("/career/invite/level1")
def enter_level_one_invite():
    payload = request.get_json(silent=True) or {}
    try:
        result = create_or_resume_level_one_invite(
            payload.get("guest_user_id"),
            current_app.config["universe_generation"],
            current_app.config["career_generation"],
            reset_existing=payload.get("reset") is True,
        )
    except (CareerInviteError, ValueError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    return jsonify({"ok": True, "user_id": result.user_id, "universe_id": result.universe_id, "created": result.created}), 201 if result.created else 200


@auth_blueprint.post("/login")
def login_or_signup():
    payload = request.get_json(silent=True) or {}
    try:
        result = authenticate_human(payload.get("username"), payload.get("password"))
    except AuthenticationError as error:
        return jsonify({"ok": False, "error": str(error)}), 401
    return jsonify({
        "ok": True,
        "action": result.action,
        "username": result.username,
        "type": result.account_type,
    }), 201 if result.action == "signup" else 200


@auth_blueprint.post("/universe/new")
def create_universe():
    payload = request.get_json(silent=True) or {}
    try:
        config = current_app.config["universe_generation"].with_options(payload.get("options"))
        result = create_universe_for_user(payload.get("username"), config)
    except (AuthenticationError, ValueError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    return jsonify({"ok": True, "universe_id": result.universe_id}), 201


@auth_blueprint.post("/universe/enter")
def enter_universe():
    payload = request.get_json(silent=True) or {}
    try:
        result = enter_universe_for_user(payload.get("username"), payload.get("universe_id"), current_app.config["universe_generation"])
    except AuthenticationError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    return jsonify({"ok": True, "universe_id": result.universe_id, "onboarded": result.onboarded, "star_id": result.star_id, "ship_ids": result.ship_ids})


@auth_blueprint.post("/universe/heartbeat")
def universe_heartbeat():
    payload = request.get_json(silent=True) or {}
    username, universe_id = payload.get("username"), payload.get("universe_id")
    if not isinstance(username, str) or not isinstance(universe_id, str):
        return jsonify({"ok": False, "error": "username and universe_id are required."}), 400
    # This is intentionally in-memory. It prevents idle universes from
    # consuming Firebase simulation reads/writes without adding presence writes.
    current_app.config["universe_activity"].touch(universe_id)
    # Schedule the simple Level 1 tutorial agent here too.  This avoids a
    # production-only failure mode where Render serves the heartbeat in a
    # different process from the background worker holding in-memory presence.
    try:
        agent_fired = current_app.config["simulation_runner"].run_level_one_agent_tick(universe_id)
    except Exception:
        # Presence must remain reliable even if Firebase temporarily rejects
        # the optional Level 1 agent scheduling read/transaction.
        current_app.logger.exception("Level 1 agent heartbeat scheduling failed for universe %s.", universe_id)
        agent_fired = False
    return jsonify({"ok": True, "universe_id": universe_id, "agent_fired": agent_fired})
