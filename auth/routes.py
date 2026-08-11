from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from auth.service import AuthenticationError, authenticate_human, create_universe_for_user, enter_universe_for_user


auth_blueprint = Blueprint("auth", __name__, url_prefix="/auth")


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
    return jsonify({"ok": True, "universe_id": universe_id})
