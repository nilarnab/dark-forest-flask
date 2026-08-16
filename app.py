from __future__ import annotations

import logging
import math
import time
import uuid
from threading import Thread

from flask import Flask, jsonify, request

from auth.routes import auth_blueprint
from config import Settings
from firebase.client import initialize_firebase
from firebase.repository import TransactionConflictError, UniverseRepository
from simulation.runner import SimulationRunner
from simulation.activity import UniverseActivityTracker
from simulation.projectile import ProjectileError
from simulation.shots import prepare_shot
from simulation.clock import simulation_time
from simulation.movement import curve_items, position_for_object_at_time
from simulation.collision import verify_and_apply_collision
from simulation.universe import apply_client_reported_projectile_hit, apply_projectile_processing, straight_line_position
from simulation.transfer import ManeuverBlockedError, TransferError, apply_transfer_plan, build_transfer_plan
from universe_factory.config import UniverseGenerationConfig
from career.config import CareerGenerationConfig


def create_app() -> Flask:
    settings = Settings.from_environment()
    initialize_firebase(settings)
    repository = UniverseRepository()
    activity = UniverseActivityTracker(settings.universe_activity_timeout_seconds)
    universe_generation = UniverseGenerationConfig.from_environment()
    career_generation = CareerGenerationConfig.from_environment(universe_generation)
    runner = SimulationRunner(repository, settings.tick_seconds, activity, settings.simulation_write_positions)
    runner.projectile_processing_seconds = settings.projectile_processing_seconds
    runner.projectile_cleanup_seconds = settings.projectile_cleanup_seconds
    runner.hit_event_retention_seconds = settings.hit_event_retention_seconds
    runner.hit_distance_tolerance = settings.hit_distance_tolerance
    runner.projectile_range = settings.projectile_range
    runner.projectile_blast_impact = settings.projectile_blast_impact
    runner.projectile_retention_seconds = settings.projectile_retention_seconds

    app = Flask(__name__)
    # Gunicorn owns the process-wide logging configuration in Render. Set the
    # Flask logger explicitly so the per-request timing diagnostics below are
    # visible alongside Gunicorn's access logs.
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = True
    app.config["settings"] = settings
    app.config["simulation_runner"] = runner
    app.config["universe_activity"] = activity
    app.config["universe_generation"] = universe_generation
    app.config["career_generation"] = career_generation
    app.register_blueprint(auth_blueprint)

    @app.after_request
    def allow_configured_ui(response):
        origin = request.headers.get("Origin", "").rstrip("/")
        if origin in settings.cors_allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "tick_seconds": settings.tick_seconds})

    @app.post("/simulation/tick")
    def single_tick():
        """Useful for local testing. Production ticks should use worker.py."""
        updated = runner.run_tick()
        return jsonify({"ok": True, "universes_updated": updated})

    @app.post("/universes/<universe_id>/tutorial")
    def update_tutorial(universe_id: str):
        """Advance one deterministic Level 1 tutorial state transition."""
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        app.logger.info("TUTORIAL action=%r universe=%s object_id=%r", action, universe_id, payload.get("object_id"))
        if action not in {"next", "back", "auto_pause", "ensure_paused", "enemy_contact", "contact_next", "contact_back", "begin_combat", "combat_ship", "combat_orbit", "combat_star", "combat_transfer_sent", "combat_radar_locked", "combat_status_next", "combat_finish"}:
            app.logger.warning("TUTORIAL rejected unknown action=%r universe=%s", action, universe_id)
            return jsonify({"ok": False, "error": "Unknown tutorial action."}), 400
        contact_object_id = payload.get("object_id")

        def update(universe):
            if not isinstance(universe, dict) or universe.get("career") is not True:
                raise TransferError("Career universe does not exist.")
            now_ms = time.time() * 1000
            career_state = universe.setdefault("career_state", {})
            if not isinstance(career_state, dict):
                career_state = {}
                universe["career_state"] = career_state
            step = int(career_state.get("tutorial_step", 0))
            intermission = career_state.get("tutorial_intermission") is True
            contact_step = career_state.get("enemy_contact_tutorial_step")
            if not isinstance(contact_step, int):
                contact_step = None

            # Enemy contact is a separate, one-time tutorial after the base
            # Level 1 sequence. Freeze the exact analytic instant at which a
            # hostile ship first becomes visible; never rewind to a prior
            # Firebase location.
            if action == "enemy_contact":
                if step < 6 or contact_step is not None:
                    return universe
                objects = universe.get("objects")
                ship = objects.get(contact_object_id) if isinstance(objects, dict) and isinstance(contact_object_id, str) else None
                if not isinstance(ship, dict) or ship.get("type") != "ARTIFICIAL" or ship.get("sub_type") == "PROJECTILE":
                    raise TransferError("Enemy contact must identify an enemy ship.")
                home_star_id = None
                for _, curve in curve_items(ship.get("curves")):
                    focus_id = curve.get("focus1") if isinstance(curve, dict) else None
                    focus = objects.get(focus_id) if isinstance(objects, dict) and isinstance(focus_id, str) else None
                    if isinstance(focus, dict) and focus.get("type") == "NATURAL":
                        home_star_id = focus_id
                        break
                if home_star_id is None:
                    raise TransferError("Enemy ship does not have an identifiable home star.")
                current_time = simulation_time(universe, now_ms) if universe.get("active") is True else float(universe.get("time", 0))
                career_state["enemy_contact_tutorial_step"] = 0
                career_state["enemy_contact_ship_id"] = contact_object_id
                career_state["enemy_contact_star_id"] = home_star_id
                career_state["tutorial_intermission"] = False
                career_state.pop("tutorial_intermission_started_at_ms", None)
                universe["time"] = current_time
                universe["time_updated_at_ms"] = now_ms
                universe["active"] = False
                return universe

            combat_step = career_state.get("combat_tutorial_step")
            if not isinstance(combat_step, int):
                combat_step = None
            if action == "begin_combat":
                if step < 6 or contact_step != 2 or combat_step is not None:
                    return universe
                current_time = simulation_time(universe, now_ms) if universe.get("active") is True else float(universe.get("time", 0))
                career_state["combat_tutorial_step"] = 0
                universe["time"] = current_time
                universe["time_updated_at_ms"] = now_ms
                universe["active"] = False
                return universe
            if action in {"combat_ship", "combat_orbit", "combat_star", "combat_transfer_sent", "combat_radar_locked", "combat_status_next", "combat_finish"}:
                transitions = {
                    "combat_ship": (0, 1), "combat_orbit": (1, 2), "combat_star": (2, 3),
                    "combat_transfer_sent": (3, 4), "combat_radar_locked": (4, 5),
                    "combat_status_next": (5, 6), "combat_finish": (6, 7),
                }
                expected, next_step = transitions[action]
                if combat_step != expected:
                    return universe
                career_state["combat_tutorial_step"] = next_step
                career_state["tutorial_intermission"] = False
                career_state.pop("tutorial_intermission_started_at_ms", None)
                if action == "combat_status_next":
                    agent_state = universe.get("agent_state")
                    if isinstance(agent_state, dict):
                        agent = agent_state.get("agent_level_1_enemy")
                        if isinstance(agent, dict):
                            agent["active"] = True
                            agent["mode"] = "FIRING"
                active_after = action in {"combat_orbit", "combat_transfer_sent", "combat_finish"}
                # Checkpoint analytic time before every new paused tutorial.
                # Without this, a resume uses the old checkpoint and appears
                # to leap through the maneuver that happened while active.
                universe["time"] = simulation_time(universe, now_ms) if universe.get("active") is True else float(universe.get("time", 0))
                universe["time_updated_at_ms"] = now_ms
                universe["active"] = active_after
                return universe

            if action in {"contact_next", "contact_back"}:
                if contact_step is None or contact_step >= 2:
                    return universe
                contact_step = contact_step + 1 if action == "contact_next" else max(0, contact_step - 1)
                career_state["enemy_contact_tutorial_step"] = contact_step
                career_state["tutorial_intermission"] = False
                career_state.pop("tutorial_intermission_started_at_ms", None)
                universe["time_updated_at_ms"] = now_ms
                # The final contact message resumes from the frozen time with
                # a fresh anchor. The ship cannot jump forward on dismissal.
                universe["active"] = contact_step >= 2
                return universe

            if action == "next" and not intermission:
                step = min(6, step + 1)
                # Steps 2 and 4 are three-second live demonstrations. Step
                # 5 is the shorter two-second radar-observation beat; the
                # client uses its step to select the matching duration.
                intermission = step in {2, 4, 5}
            elif action == "back" and not intermission:
                step = max(0, step - 1)
            elif action == "auto_pause":
                intermission = False

            if intermission:
                # `universe.time` is the sole frozen timestamp. Resume from
                # that exact value and establish a fresh wall-clock anchor.
                current_time = float(universe.get("time", 0))
                career_state["tutorial_intermission"] = True
                career_state["tutorial_intermission_started_at_ms"] = now_ms
                active = True
            elif step < 6:
                # Freeze at the actual analytic position/time at the instant
                # this transition is committed, never at an old location.
                current_time = simulation_time(universe, now_ms) if universe.get("active") is True else float(universe.get("time", 0))
                career_state["paused_time"] = current_time
                career_state["tutorial_intermission"] = False
                career_state.pop("tutorial_intermission_started_at_ms", None)
                active = False
            else:
                # The final resume starts precisely at the frozen universe
                # value; it never derives a second, stale checkpoint.
                current_time = float(universe.get("time", 0))
                career_state["tutorial_intermission"] = False
                career_state.pop("tutorial_intermission_started_at_ms", None)
                active = True
            career_state["tutorial_step"] = step
            career_state["status"] = "COMPLETED" if step >= 6 else "ACTIVE"
            universe["time"] = current_time
            universe["time_updated_at_ms"] = now_ms
            universe["active"] = active
            return universe

        try:
            updated = repository.transaction_universe(universe_id, update)
        except TransferError as error:
            return jsonify({"ok": False, "error": str(error)}), 404
        except TransactionConflictError as error:
            return jsonify({"ok": False, "error": str(error)}), 409
        if action == "combat_finish" and updated.get("active") is True:
            # Fire the agent's opening shot at the exact moment the combat
            # tutorial is dismissed, rather than waiting for the next UI
            # heartbeat (which may be almost two seconds later).
            try:
                runner.run_level_one_agent_tick(universe_id)
            except Exception:
                app.logger.exception("Could not fire the Level 1 agent opening shot in %s.", universe_id)
        state = updated.get("career_state") if isinstance(updated.get("career_state"), dict) else {}
        return jsonify({
            "ok": True,
            "step": state.get("tutorial_step", 0),
            "enemy_contact_step": state.get("enemy_contact_tutorial_step"),
            "active": updated.get("active") is True,
            "intermission": state.get("tutorial_intermission") is True,
            "intermission_started_at_ms": state.get("tutorial_intermission_started_at_ms"),
        })

    @app.post("/universes/<universe_id>/transfers")
    def create_transfer(universe_id: str):
        payload = request.get_json(silent=True) or {}
        object_id = payload.get("objectid1")
        target_id = payload.get("objectid2")
        target_radius = payload.get("radnew")
        if not isinstance(object_id, str) or not isinstance(target_id, str) or target_radius is None:
            return jsonify({"ok": False, "error": "JSON must include objectid1, objectid2, and radnew."}), 400

        plan_holder = {}

        def schedule(universe):
            if not isinstance(universe, dict):
                raise TransferError("Universe does not exist.")
            now_ms = time.time() * 1000
            current_time = simulation_time(universe, now_ms)
            plan = build_transfer_plan(universe, object_id, target_id, target_radius, now=current_time)
            plan_holder["plan"] = plan
            updated = apply_transfer_plan(universe, plan)
            # An action checkpoints the shared time anchor. Normal movement
            # no longer causes periodic Firebase writes.
            updated["time"] = current_time
            updated["time_updated_at_ms"] = now_ms
            events = updated.setdefault("events", {})
            if isinstance(events, dict):
                events[f"transfer_{object_id}_{round(current_time * 1000)}"] = {
                    "type": "TRANSFER_SCHEDULED",
                    "object_id": object_id,
                    "target_id": target_id,
                    "occurred_at": current_time,
                    "start_time": plan.start_time,
                    "arrival_time": plan.arrival_time,
                }
            return updated

        try:
            repository.transaction_universe(universe_id, schedule)
            plan = plan_holder["plan"]
        except ManeuverBlockedError as error:
            return jsonify({"ok": False, "error": str(error)}), 409
        except TransferError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        except TransactionConflictError as error:
            return jsonify({"ok": False, "error": str(error)}), 409

        return jsonify({
            "ok": True,
            "objectid1": object_id,
            "objectid2": target_id,
            "radnew": float(target_radius),
            "t1": plan.start_time,
            "t2": plan.arrival_time,
            "curve_ids": {"transfer": plan.transfer_curve_key, "destination_orbit": plan.destination_curve_key},
        }), 201

    @app.post("/universes/<universe_id>/shots")
    def fire_shot(universe_id: str):
        request_id = uuid.uuid4().hex[:8]
        started_at = time.perf_counter()
        app.logger.info("SHOT %s entered universe=%s", request_id, universe_id)
        payload = request.get_json(silent=True) or {}
        object_id = payload.get("objectid")
        gun_id = payload.get("gun_id")
        rotation = payload.get("rotation")
        client_fired_at = payload.get("client_fired_at")
        if not isinstance(object_id, str) or not isinstance(gun_id, str) or rotation is None:
            return jsonify({"ok": False, "error": "JSON must include objectid, gun_id, and rotation."}), 400
        if client_fired_at is not None and not isinstance(client_fired_at, (int, float)):
            return jsonify({"ok": False, "error": "client_fired_at must be a numeric simulation time."}), 400
        try:
            universe = repository.get_universe(universe_id)
            read_completed_at = time.perf_counter()
            app.logger.info(
                "SHOT %s Firebase read completed in %.3fs",
                request_id,
                read_completed_at - started_at,
            )
            shot = prepare_shot(
                universe_id, universe, object_id, gun_id, float(rotation),
                projectile_range=settings.projectile_range,
                projectile_blast_impact=settings.projectile_blast_impact,
                projectile_retention_seconds=settings.projectile_retention_seconds,
                client_fired_at=float(client_fired_at) if client_fired_at is not None else None,
                client_fire_time_tolerance_seconds=settings.client_fire_time_tolerance_seconds,
            )
            prepared_at = time.perf_counter()
            app.logger.info(
                "SHOT %s validation/preparation completed in %.3fs",
                request_id,
                prepared_at - read_completed_at,
            )
            repository.atomic_update(shot.updates)
            app.logger.info(
                "SHOT %s Firebase targeted update completed in %.3fs (total %.3fs)",
                request_id,
                time.perf_counter() - prepared_at,
                time.perf_counter() - started_at,
            )
        except ProjectileError as error:
            app.logger.warning("SHOT %s rejected after %.3fs: %s", request_id, time.perf_counter() - started_at, error)
            return jsonify({"ok": False, "error": str(error)}), 400
        except Exception:
            app.logger.exception("SHOT %s failed after %.3fs", request_id, time.perf_counter() - started_at)
            raise
        app.logger.info("SHOT %s responded in %.3fs", request_id, time.perf_counter() - started_at)
        return jsonify({"ok": True, "projectile_id": shot.projectile_id, "fired_at": shot.fired_at}), 201

    @app.post("/universes/<universe_id>/projectiles/<projectile_id>/verify-hit")
    def verify_projectile_hit(universe_id: str, projectile_id: str):
        payload = request.get_json(silent=True) or {}
        target_id = payload.get("target_id")
        hit_time = payload.get("hit_time")
        if not isinstance(target_id, str) or not isinstance(hit_time, (int, float)):
            return jsonify({"ok": False, "error": "JSON must include target_id and numeric hit_time."}), 400
        committed: dict[str, object] = {}

        def commit(current):
            if not isinstance(current, dict):
                committed.update(status="rejected", reason="Universe does not exist.")
                return current
            committed.update(apply_client_reported_projectile_hit(
                current, projectile_id, target_id, float(hit_time),
                settings.star_death_blast_radius, settings.star_death_blast_damage,
            ))
            return current

        try:
            repository.transaction_universe(universe_id, commit)
        except TransactionConflictError as error:
            return jsonify({"ok": False, "error": str(error)}), 409
        return jsonify({"ok": True, "hit_time": hit_time, **committed})

    @app.post("/universes/<universe_id>/collisions/verify")
    def verify_collision(universe_id: str):
        payload = request.get_json(silent=True) or {}
        first_id, second_id, hit_time = payload.get("object_id_1"), payload.get("object_id_2"), payload.get("hit_time")
        if not isinstance(first_id, str) or not isinstance(second_id, str) or not isinstance(hit_time, (int, float)):
            return jsonify({"ok": False, "error": "JSON must include object_id_1, object_id_2, and numeric hit_time."}), 400
        result_holder: dict[str, object] = {}

        def verify(universe):
            if not isinstance(universe, dict):
                result_holder.update(status="rejected", reason="Universe does not exist.")
                return universe
            server_time = simulation_time(universe, time.time() * 1000)
            tolerance = max(0.0, settings.client_fire_time_tolerance_seconds)
            if abs(float(hit_time) - server_time) > tolerance:
                result_holder.update(status="rejected", reason=f"Client hit time differs from Flask by more than {tolerance:g}s.")
                return universe
            result_holder.update(verify_and_apply_collision(
                universe, first_id, second_id, float(hit_time), settings.hit_distance_tolerance,
            ))
            return universe

        try:
            repository.transaction_universe(universe_id, verify)
        except TransactionConflictError as error:
            return jsonify({"ok": False, "error": str(error)}), 409
        return jsonify({"ok": True, **result_holder})

    if settings.simulation_enabled:
        cleaner_thread = Thread(target=runner.run_projectile_cleanup_forever, name="projectile-cleanup-worker", daemon=True)
        cleaner_thread.start()
        app.config["projectile_cleanup_thread"] = cleaner_thread
        if settings.projectile_processing_enabled:
            projectile_thread = Thread(target=runner.run_projectile_processing_forever, name="projectile-processing-worker", daemon=True)
            projectile_thread.start()
            app.config["projectile_processing_thread"] = projectile_thread
            app.logger.info("Projectile processing worker started in a background thread (%.2fs ticks).", settings.projectile_processing_seconds)
        else:
            app.logger.info("Client-verified projectile mode enabled; continuous projectile polling is not started.")
        if settings.simulation_write_positions:
            thread = Thread(target=runner.run_forever, name="simulation-worker", daemon=True)
            thread.start()
            app.config["simulation_thread"] = thread
            app.logger.info("Legacy position-writing simulation worker started (%.2fs ticks).", settings.tick_seconds)
        else:
            app.logger.info("Event-driven simulation mode enabled; normal position worker is not started.")
        app.logger.info("Projectile cleanup worker started in a background thread (%.2fs ticks).", settings.projectile_cleanup_seconds)

    return app


def hit_verification_diagnostics(
    universe: dict, projectile_id: str, target_id: str, client_hit_time: float, client_distance: float | None,
) -> dict:
    """Return request-only geometry details; nothing here is persisted to Firebase."""
    diagnostics: dict[str, float | str | None] = {
        "client_hit_time": client_hit_time,
        "client_distance": client_distance,
    }
    objects = universe.get("objects")
    if not isinstance(objects, dict):
        return diagnostics
    projectile = objects.get(projectile_id)
    target = objects.get(target_id)
    if not isinstance(projectile, dict) or not isinstance(target, dict):
        return diagnostics
    base_time = float(universe.get("time", 0))
    # Curves are analytic, so verify at the exact time claimed by the client.
    # The current Firebase snapshot is only the phase reference, not a lower
    # bound for the historical collision calculation.
    evaluated_at = client_hit_time
    diagnostics["flask_evaluated_at"] = evaluated_at
    curve = next((curve for _, curve in curve_items(projectile.get("curves")) if curve.get("type") == "STRAIGHT_LINE"), None)
    projectile_position = straight_line_position(curve, evaluated_at) if curve else None
    target_position = position_for_object_at_time(target, objects, evaluated_at)
    if not isinstance(projectile_position, dict) or not isinstance(target_position, dict):
        return diagnostics
    try:
        diagnostics["flask_distance"] = math.hypot(
            float(projectile_position["x"]) - float(target_position["x"]),
            float(projectile_position["y"]) - float(target_position["y"]),
        )
        radius = projectile.get("hit_radius")
        diagnostics["hit_radius"] = float(radius) if isinstance(radius, (int, float)) else None
    except (KeyError, TypeError, ValueError):
        pass
    return diagnostics


def diagnostics_indicate_hit(diagnostics: dict, tolerance: float = 0.01) -> bool:
    distance, radius = diagnostics.get("flask_distance"), diagnostics.get("hit_radius")
    return isinstance(distance, (int, float)) and isinstance(radius, (int, float)) and distance <= radius + max(0.0, tolerance)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    host = "0.0.0.0"
    port = 5001
    logging.getLogger(__name__).info("Flask API listening at http://localhost:%s", port)
    # Disable the development reloader: it creates a second Flask process,
    # which would otherwise create a second simulation worker.
    create_app().run(host=host, port=port, debug=True, use_reloader=False)
