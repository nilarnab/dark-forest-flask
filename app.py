from __future__ import annotations

import json
import logging
import math
import time
import uuid
from threading import Thread

from flask import Flask, Response, jsonify, request, stream_with_context

from auth.routes import auth_blueprint
from config import Settings
from firebase.client import initialize_firebase
from firebase.repository import TransactionConflictError, UniverseRepository
from simulation.runner import SimulationRunner
from simulation.activity import UniverseActivityTracker
from simulation.projectile import ProjectileError, build_projectile
from simulation.clock import simulation_time
from simulation.movement import curve_items, position_for_object_at_time
from simulation.collision import verify_and_apply_collision
from simulation.universe import apply_projectile_processing, straight_line_position
from simulation.transfer import ManeuverBlockedError, TransferError, apply_transfer_plan, build_transfer_plan
from simulation.live_events import LiveEventBus
from universe_factory.config import UniverseGenerationConfig


def create_app() -> Flask:
    settings = Settings.from_environment()
    initialize_firebase(settings)
    repository = UniverseRepository()
    activity = UniverseActivityTracker(settings.universe_activity_timeout_seconds)
    live_events = LiveEventBus()
    universe_generation = UniverseGenerationConfig.from_environment()
    runner = SimulationRunner(repository, settings.tick_seconds, activity, settings.simulation_write_positions)
    runner.projectile_processing_seconds = settings.projectile_processing_seconds
    runner.projectile_cleanup_seconds = settings.projectile_cleanup_seconds
    runner.hit_event_retention_seconds = settings.hit_event_retention_seconds
    runner.hit_distance_tolerance = settings.hit_distance_tolerance

    app = Flask(__name__)
    # Gunicorn owns the process-wide logging configuration in Render. Set the
    # Flask logger explicitly so the per-request timing diagnostics below are
    # visible alongside Gunicorn's access logs.
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = True
    app.config["settings"] = settings
    app.config["simulation_runner"] = runner
    app.config["universe_activity"] = activity
    app.config["live_events"] = live_events
    app.config["universe_generation"] = universe_generation
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

    @app.get("/universes/<universe_id>/live-events")
    def stream_live_events(universe_id: str):
        def event_stream():
            for event in live_events.stream(universe_id):
                if event is None:
                    yield ": keepalive\n\n"
                else:
                    yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
        return Response(
            stream_with_context(event_stream()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/universes/<universe_id>/projectile-previews")
    def relay_projectile_preview(universe_id: str):
        """Fan out a cosmetic shot preview without waiting for Firebase."""
        payload = request.get_json(silent=True) or {}
        required_strings = ("projectile_id", "source_id")
        required_numbers = ("rotation", "velocity", "hit_radius", "fired_at", "range")
        start = payload.get("start_location")
        if (
            any(not isinstance(payload.get(key), str) for key in required_strings)
            or any(not isinstance(payload.get(key), (int, float)) for key in required_numbers)
            or not isinstance(start, dict)
            or not isinstance(start.get("x"), (int, float))
            or not isinstance(start.get("y"), (int, float))
        ):
            return jsonify({"ok": False, "error": "Invalid projectile preview payload."}), 400
        live_events.publish(universe_id, {
            "type": "PROJECTILE_FIRED_PREVIEW",
            "projectile_id": payload["projectile_id"],
            "source_id": payload["source_id"],
            "start_location": {"x": float(start["x"]), "y": float(start["y"])},
            "rotation": float(payload["rotation"]),
            "velocity": float(payload["velocity"]),
            "hit_radius": float(payload["hit_radius"]),
            "fired_at": float(payload["fired_at"]),
            "range": float(payload["range"]),
        })
        return jsonify({"ok": True}), 202

    @app.post("/universes/<universe_id>/projectile-previews/<preview_id>/cancel")
    def cancel_projectile_preview(universe_id: str, preview_id: str):
        live_events.publish(universe_id, {"type": "PROJECTILE_CANCELLED", "projectile_id": preview_id})
        return jsonify({"ok": True})

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
        projectile_id = f"projectile_{uuid.uuid4().hex}"
        fired_at_holder = {}
        projectile_event: dict[str, object] = {}

        def prepare_shot(universe):
            if not isinstance(universe, dict) or not isinstance(universe.get("objects"), dict):
                raise ProjectileError("Universe does not exist.")
            ship = universe["objects"].get(object_id)
            if not isinstance(ship, dict) or ship.get("type") != "ARTIFICIAL":
                raise ProjectileError("objectid must identify an ARTIFICIAL firing object.")
            attachments = ship.get("objects")
            gun = attachments.get(gun_id) if isinstance(attachments, dict) else None
            if not isinstance(gun, dict) or gun.get("type") != "GUN":
                raise ProjectileError("gun_id must identify an attached GUN.")
            velocity = gun.get("velocity")
            if not isinstance(velocity, (int, float)) or velocity <= 0:
                raise ProjectileError("The selected GUN needs a positive numeric velocity.")
            hit_radius = gun.get("hit_radius")
            if not isinstance(hit_radius, (int, float)) or hit_radius <= 0:
                raise ProjectileError("The selected GUN needs a positive numeric hit_radius.")
            now_ms = time.time() * 1000
            # Old universes may not have a clock anchor yet. Establish it on
            # the first action so shots can be timestamped between ticks.
            if not isinstance(universe.get("time_updated_at_ms"), (int, float)):
                universe["time_updated_at_ms"] = now_ms
            server_time = simulation_time(universe, now_ms)
            fired_at = server_time if client_fired_at is None else float(client_fired_at)
            tolerance = max(0.0, settings.client_fire_time_tolerance_seconds)
            if abs(fired_at - server_time) > tolerance:
                raise ProjectileError(
                    f"CLIENT TIME REJECTED: supplied time differs from Flask by more than {tolerance:g}s."
                )
            base_time = float(universe.get("time", 0))
            if fired_at < base_time:
                raise ProjectileError("CLIENT TIME REJECTED: supplied time predates the authoritative universe state.")
            firing_ship = dict(ship)
            # Reconstruct from the curve's own phase timestamp. In
            # event-driven mode `universe.time` is only a checkpoint.
            firing_position = position_for_object_at_time(ship, universe["objects"], fired_at)
            if firing_position is not None:
                firing_ship["location"] = firing_position
            fired_at_holder["value"] = fired_at
            projectile = build_projectile(
                firing_ship, fired_at, rotation, float(velocity), settings.projectile_range,
                source_objectid=object_id, hit_radius=float(hit_radius), blast_impact=settings.projectile_blast_impact,
                retention_seconds=settings.projectile_retention_seconds,
            )
            fire_event = {
                "type": "PROJECTILE_FIRED",
                "projectile_id": projectile_id,
                "source_id": object_id,
                "occurred_at": fired_at,
                "start_location": projectile["location"],
                "rotation": float(rotation),
                "velocity": float(velocity),
                "hit_radius": float(hit_radius),
                "range": settings.projectile_range,
            }
            projectile_event.update({
                "type": "PROJECTILE_FIRED",
                "projectile_id": projectile_id,
                "source_id": object_id,
                "start_location": projectile["location"],
                "rotation": float(rotation),
                "velocity": float(velocity),
                "hit_radius": float(hit_radius),
                "fired_at": fired_at,
                "range": settings.projectile_range,
            })
            # Avoid a Firebase transaction on the complete universe. On a
            # remote deployment, retrying that large transaction made firing
            # wait seconds behind unrelated updates. A shot only appends a new
            # object/event and advances the shared clock, so a targeted atomic
            # multi-location update is sufficient here.
            return {
                f"universes/{universe_id}/objects/{projectile_id}": projectile,
                f"universes/{universe_id}/events/fire_{projectile_id}": fire_event,
                f"universes/{universe_id}/time": server_time,
                f"universes/{universe_id}/time_updated_at_ms": now_ms,
            }

        try:
            universe = repository.get_universe(universe_id)
            read_completed_at = time.perf_counter()
            app.logger.info(
                "SHOT %s Firebase read completed in %.3fs",
                request_id,
                read_completed_at - started_at,
            )
            updates = prepare_shot(universe)
            prepared_at = time.perf_counter()
            app.logger.info(
                "SHOT %s validation/preparation completed in %.3fs",
                request_id,
                prepared_at - read_completed_at,
            )
            repository.atomic_update(updates)
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
        live_events.publish(universe_id, projectile_event)
        app.logger.info("SHOT %s responded in %.3fs", request_id, time.perf_counter() - started_at)
        return jsonify({"ok": True, "projectile_id": projectile_id, "fired_at": fired_at_holder["value"]}), 201

    @app.post("/universes/<universe_id>/projectiles/<projectile_id>/verify-hit")
    def verify_projectile_hit(universe_id: str, projectile_id: str):
        payload = request.get_json(silent=True) or {}
        target_id = payload.get("target_id")
        hit_time = payload.get("hit_time")
        client_distance = payload.get("client_distance")
        if not isinstance(target_id, str) or not isinstance(hit_time, (int, float)):
            return jsonify({"ok": False, "error": "JSON must include target_id and numeric hit_time."}), 400
        if client_distance is not None and not isinstance(client_distance, (int, float)):
            return jsonify({"ok": False, "error": "client_distance must be numeric when supplied."}), 400
        universe = repository.get_universe(universe_id)
        if not isinstance(universe, dict):
            return jsonify({"ok": False, "error": "Universe does not exist."}), 404
        outcomes = universe.get("recent_projectile_outcomes")
        outcome = outcomes.get(projectile_id) if isinstance(outcomes, dict) else None
        diagnostics = hit_verification_diagnostics(
            universe, projectile_id, target_id, float(hit_time),
            float(client_distance) if client_distance is not None else None,
        )
        if isinstance(outcome, dict):
            if outcome.get("status") == "HIT" and outcome.get("target_id") == target_id:
                return jsonify({"ok": True, "status": "confirmed", "hit_time": outcome.get("hit_time"), "diagnostics": diagnostics})
            return jsonify({"ok": True, "status": "rejected", "diagnostics": diagnostics, "flask_outcome": outcome})
        if diagnostics_indicate_hit(diagnostics, settings.hit_distance_tolerance):
            # Commit the verified client report immediately. This keeps the
            # browser responsive without waiting for the background projectile
            # loop, while Flask still decides whether the geometry is valid.
            committed: dict[str, object] = {}

            def commit(current):
                if not isinstance(current, dict):
                    committed.update(status="rejected")
                    return current
                outcomes = current.get("recent_projectile_outcomes")
                existing = outcomes.get(projectile_id) if isinstance(outcomes, dict) else None
                if isinstance(existing, dict):
                    committed.update(status="confirmed" if existing.get("status") == "HIT" and existing.get("target_id") == target_id else "rejected", outcome=existing)
                    return current
                # A tiny swept interval preserves the existing 'first object
                # struck wins' collision rule rather than trusting a target
                # selected by the browser.
                apply_projectile_processing(
                    current, float(hit_time) - 0.01, float(hit_time) + 0.01,
                    settings.hit_distance_tolerance,
                )
                outcomes = current.get("recent_projectile_outcomes")
                result = outcomes.get(projectile_id) if isinstance(outcomes, dict) else None
                committed.update(status="confirmed" if isinstance(result, dict) and result.get("status") == "HIT" and result.get("target_id") == target_id else "rejected", outcome=result)
                return current

            try:
                repository.transaction_universe(universe_id, commit)
            except TransactionConflictError as error:
                return jsonify({"ok": False, "error": str(error)}), 409
            return jsonify({"ok": True, "status": committed.get("status", "rejected"), "hit_time": hit_time, "diagnostics": diagnostics, "flask_outcome": committed.get("outcome")})
        objects = universe.get("objects")
        # With no outcome recorded, an active projectile means Flask has not
        # accepted this claimed collision; reject the cosmetic prediction.
        if isinstance(objects, dict) and projectile_id in objects:
            return jsonify({"ok": True, "status": "rejected", "diagnostics": diagnostics})
        return jsonify({"ok": True, "status": "pending", "diagnostics": diagnostics})

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
