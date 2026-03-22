"""
Live tracking routes:
  POST /live/push          — tracker pushes state (API key auth, resolves user)
  GET  /live/state         — poll current state (public, optional ?user=)
  GET  /live/stream        — SSE real-time stream (public, optional ?user=)
  GET  /live/health        — health check with sync freshness (public)
  GET  /live/active        — list all users currently live (public)
"""
from __future__ import annotations

import asyncio
import json
import os
import time as _time

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.live_state import DEFAULT_USER, live_state

router = APIRouter(prefix="/live", tags=["live"])


def _extract_api_key(request: Request) -> str | None:
    """Extract API key from Authorization header or query param."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("api_key")


def _check_api_key(request: Request) -> bool:
    """Validate the tracker's API key against the users table.

    Accepts any valid user API key from the database.
    Falls back to SMW_API_KEY env var for backward compatibility.
    If neither is configured, allows all (local dev).
    """
    key = _extract_api_key(request)
    if not key:
        # No key provided — only allow if no auth is configured at all
        env_key = os.environ.get("SMW_API_KEY", "")
        return not env_key  # Allow if no env key set (local dev)

    # Check against users table first
    try:
        from core.user_service import get_user_by_api_key
        user = get_user_by_api_key(key)
        if user:
            return True
    except Exception:
        pass

    # Fall back to legacy single env var
    env_key = os.environ.get("SMW_API_KEY", "")
    if env_key and key == env_key:
        return True

    return False


def _resolve_user_id(request: Request) -> str:
    """Resolve user_id from API key via the users table, falling back to default."""
    key = _extract_api_key(request)
    if not key:
        return DEFAULT_USER
    try:
        from core.user_service import get_user_by_api_key
        user = get_user_by_api_key(key)
        if user:
            return str(user["id"])
    except Exception:
        pass
    return DEFAULT_USER


@router.post("/push")
async def live_push(request: Request):
    """Receive full session state from the local tracker and sync to cloud DB."""
    if not _check_api_key(request):
        return JSONResponse({"error": "Invalid API key"}, status_code=401)
    try:
        payload = await request.json()
        user_id = _resolve_user_id(request)

        # Enrich payload with cloud run config (run levels, PB, SOB)
        game_name = payload.get("game_name")
        if game_name and payload.get("is_active"):
            try:
                _enrich_payload_from_cloud(payload, game_name, int(user_id) if user_id != DEFAULT_USER else None)
            except Exception as exc:
                import logging, traceback
                logging.getLogger(__name__).error("Payload enrichment failed: %s\n%s", exc, traceback.format_exc())

        live_state.update(payload, user_id=user_id)

        # Sync session data to cloud DB
        if user_id != DEFAULT_USER:
            try:
                _sync_session_to_db(payload, int(user_id))
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Session sync failed: %s", exc)

        # Drain any pending commands for this user
        commands = live_state.drain_commands(user_id)

        return {
            "ok": True,
            "user_id": user_id,
            "commands": commands,
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


# Cache for enrichment data (avoid querying DB on every push)
_enrich_cache: dict[str, dict] = {}
_enrich_cache_split_count: dict[str, int] = {}


def _enrich_payload_from_cloud(payload: dict, game_name: str, user_id: int | None) -> None:
    """Add run_levels, PB, SOB, and best segments from the cloud DB to the payload.

    Only refreshes when split count changes to avoid hammering the DB every 500ms.
    """
    from core import db
    from core.level_names import resolve_level_name

    splits = payload.get("splits", [])
    split_count = len(splits)
    cache_key = f"{game_name}:{user_id or 'global'}"

    # Check if we need to refresh the cache
    cached = _enrich_cache.get(cache_key)
    cached_split_count = _enrich_cache_split_count.get(cache_key)
    if (cached is not None
            and cached_split_count == split_count
            and cached.get("run_levels")):  # Don't cache empty run_levels
        payload.update(cached)
        return

    # Build run_levels from cloud DB
    from core.run_service import get_default_run_config
    run_config = get_default_run_config(game_name)

    enrichment = {}

    if run_config:
        enrichment["run_name"] = run_config.get("run_name")
        enrichment["run_delay_ms"] = run_config.get("start_delay_ms", 0)

        run_levels = []
        for rl in run_config.get("levels", []):
            lid = rl.get("level_id", "")
            exit_type = rl.get("exit_type", "normal")
            split_key = f"{lid}:secret" if exit_type == "secret" else lid
            run_levels.append({
                "level_id": split_key,
                "level_name": resolve_level_name(split_key, game_name),
                "exit_type": exit_type,
            })
        enrichment["run_levels"] = run_levels

        run_level_ids = [rl["level_id"] for rl in run_levels]

        # PB splits
        from core.splits_service import get_pb_run_for_levels, get_best_segments_for_run, get_sum_of_best_for_run
        pb_result = get_pb_run_for_levels(game_name, run_level_ids)
        enrichment["pb_splits"] = pb_result.get("splits", []) if pb_result else []
        enrichment["pb_total_ms"] = pb_result["total_ms"] if pb_result else None

        # Best segments
        best_segs = get_best_segments_for_run(game_name, run_level_ids)
        enrichment["best_segments"] = {s["level_id"]: s["best_ms"] for s in best_segs}

        # Sum of best
        sob = get_sum_of_best_for_run(game_name, run_level_ids)
        enrichment["sum_of_best_ms"] = sob

        # Run completion check
        if splits:
            completed_ids = {s["level_id"] for s in splits}
            enrichment["run_complete"] = all(lid in completed_ids for lid in run_level_ids)

    # Cache it (only run_levels, PB, SOB — NOT current_level_name which changes every push)
    _enrich_cache[cache_key] = enrichment
    _enrich_cache_split_count[cache_key] = split_count

    payload.update(enrichment)

    # Resolve current level name AFTER cache (changes every level enter, not just on splits)
    current_level_id = payload.get("current_level_id")
    if current_level_id and game_name:
        # First check run_levels (the authoritative level-to-name mapping from setup)
        resolved_from_run = None
        run_levels_list = payload.get("run_levels") or []
        for rl in run_levels_list:
            base_rl_id = rl["level_id"].split(":")[0] if ":" in rl["level_id"] else rl["level_id"]
            if base_rl_id == current_level_id:
                resolved_from_run = rl["level_name"]
                break
        if resolved_from_run:
            payload["current_level_name"] = resolved_from_run
        else:
            resolved_name = resolve_level_name(current_level_id, game_name)
            if resolved_name and resolved_name != current_level_id:
                payload["current_level_name"] = resolved_name

    # Resolve split level names (not cached — splits change during a run)
    splits = payload.get("splits", [])
    if splits:
        run_levels_list = payload.get("run_levels") or []
        rl_lookup = {}
        for rl in run_levels_list:
            base_id = rl["level_id"].split(":")[0] if ":" in rl["level_id"] else rl["level_id"]
            rl_lookup[base_id] = rl["level_name"]
            rl_lookup[rl["level_id"]] = rl["level_name"]
        for s in splits:
            lid = s.get("level_id")
            if lid and (not s.get("level_name") or s["level_name"] == lid):
                s["level_name"] = rl_lookup.get(lid) or resolve_level_name(lid, game_name)


def _sync_session_to_db(payload: dict, user_id: int) -> None:
    """Sync pushed session state to the cloud database.

    Creates or updates the session row and syncs splits.
    This runs on every push (every 500ms) so it must be fast.
    """
    from core import db
    from core.time_utils import utc_now_iso

    game_name = payload.get("game_name") or ""
    is_active = payload.get("is_active", False)

    # Filter out non-game states (FXPak menu, no ROM loaded, test artifacts)
    # A real game name should be at least 2 chars and not a known placeholder
    _IGNORE_GAMES = {"", "AnyGame", "TrackGame", "TestGame", "Unknown"}
    is_real_game = is_active and game_name and game_name not in _IGNORE_GAMES and len(game_name) >= 2

    if not is_real_game:
        # Session ended or no game — ensure any active session for this user is closed
        active = db.fetchone(
            "SELECT id FROM sessions WHERE user_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        if active:
            now = utc_now_iso()
            db.execute(
                "UPDATE sessions SET end_time = ?, is_active = 0, updated_at = ? WHERE id = ?",
                (now, now, active["id"]),
            )
            db.commit()
        return

    platform = payload.get("platform", "SNES")
    start_time = payload.get("start_time")
    now = utc_now_iso()

    # Find or create session
    active = db.fetchone(
        "SELECT id, game_name FROM sessions WHERE user_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
        (user_id,),
    )

    if active and active["game_name"] == game_name:
        session_id = active["id"]
        # Touch the session
        db.execute("UPDATE sessions SET last_event_time = ?, updated_at = ? WHERE id = ?",
                   (now, now, session_id))
    else:
        # Close old session if different game
        if active:
            db.execute(
                "UPDATE sessions SET end_time = ?, is_active = 0, updated_at = ? WHERE id = ?",
                (now, now, active["id"]),
            )

        # Create new session
        session_id = db.insert_returning_id(
            """INSERT INTO sessions (user_id, game_name, platform, start_time, end_time,
                                    is_active, last_event_time, created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, 1, ?, ?, ?)""",
            (user_id, game_name, platform, start_time or now, now, now, now),
        )

    db.commit()

    # Sync splits — replace all splits for this session with the pushed ones
    splits = payload.get("splits", [])
    if splits and session_id:
        existing_count = db.fetchone(
            "SELECT COUNT(*) AS c FROM level_splits WHERE session_id = ? AND game_name = ?",
            (session_id, game_name),
        )
        # Only sync if split count changed (avoid redundant writes)
        if existing_count and existing_count["c"] != len(splits):
            # Delete old and insert new
            db.execute("DELETE FROM level_splits WHERE session_id = ? AND game_name = ?",
                       (session_id, game_name))
            for s in splits:
                db.execute(
                    """INSERT INTO level_splits (session_id, game_name, level_id, level_name,
                        split_ms, entered_at, exited_at, death_count, best_x, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, game_name, s.get("level_id"), s.get("level_name"),
                     s.get("split_ms", 0), s.get("entered_at", 0), s.get("exited_at", 0),
                     s.get("death_count", 0), s.get("best_x"), now),
                )
            db.commit()

    # Sync death events with positions (for heatmap data)
    death_events = payload.get("death_events", [])
    deaths_count = payload.get("deaths_this_session", 0)
    if session_id and (death_events or deaths_count):
        existing_deaths = db.fetchone(
            "SELECT COUNT(*) AS c FROM game_events WHERE session_id = ? AND event_type = 'death'",
            (session_id,),
        )
        current = existing_deaths["c"] if existing_deaths else 0

        if death_events and len(death_events) > current:
            # We have detailed death events — insert the new ones with positions
            new_events = death_events[current:]
            for de in new_events:
                db.execute(
                    """INSERT INTO game_events (session_id, game_name, event_type, event_time,
                        level_id, level_name, x_position, details_json, created_at)
                    VALUES (?, ?, 'death', ?, ?, ?, ?, '{}', ?)""",
                    (session_id, game_name, de.get("event_time") or now,
                     de.get("level_id"), de.get("level_name"),
                     de.get("x_position"), now),
                )
            db.commit()
        elif deaths_count > current:
            # Fallback: no detailed events, just insert count-based placeholders
            for _ in range(deaths_count - current):
                db.execute(
                    """INSERT INTO game_events (session_id, game_name, event_type, event_time,
                        level_id, level_name, x_position, details_json, created_at)
                    VALUES (?, ?, 'death', ?, ?, ?, NULL, '{}', ?)""",
                    (session_id, game_name, now,
                     payload.get("current_level_id"), payload.get("current_level_name"), now),
                )
            db.commit()


@router.get("/state")
async def live_get_state(user: str = Query(DEFAULT_USER)):
    """Poll the current live state (public). Use ?user=<id> for multi-user."""
    state = live_state.get_state(user_id=user)
    if state is None:
        return {"is_active": False}
    return state


@router.get("/stream")
async def live_stream(user: str = Query(DEFAULT_USER)):
    """SSE stream of live state updates (public). Use ?user=<id> for multi-user."""
    queue = live_state.subscribe(user_id=user)

    async def event_generator():
        try:
            # Send current state immediately
            current = live_state.get_state(user_id=user)
            if current:
                yield f"data: {json.dumps(current)}\n\n"

            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(payload)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            live_state.unsubscribe(queue, user_id=user)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/health")
async def live_health(user: str = Query(DEFAULT_USER)):
    """Health check with sync freshness info."""
    updated = live_state.get_updated_at(user_id=user)
    now = _time.time()
    age = now - updated if updated > 0 else None
    state = live_state.get_state(user_id=user)
    return {
        "ok": True,
        "has_state": state is not None,
        "is_active": state.get("is_active", False) if state else False,
        "last_push_age_seconds": round(age, 1) if age is not None else None,
        "subscribers": len(live_state._get_user(user).subscribers),
    }


@router.get("/active")
async def live_active_users():
    """List all users currently live (public)."""
    return live_state.get_active_users()


@router.get("/debug-enrich/{game_name}")
async def debug_enrich(game_name: str):
    """Debug: check what run config the cloud has for a game."""
    from core.run_service import get_default_run_config, get_default_run_for_game
    from core import db

    default_run = get_default_run_for_game(game_name)
    run_config = get_default_run_config(game_name)

    # Also check what game names exist in run_definitions
    all_runs = db.fetchall("SELECT id, game_name, run_name, is_default FROM run_definitions ORDER BY id")

    return {
        "game_name_queried": game_name,
        "default_run": default_run,
        "run_config_found": run_config is not None,
        "run_config_levels": len(run_config.get("levels", [])) if run_config else 0,
        "all_run_definitions": all_runs,
    }


# ── Remote commands (web → local tracker) ──

@router.post("/command/{user_id}")
async def queue_command(request: Request, user_id: str):
    """Queue a command for a user's local tracker.

    Authenticated users can only send commands to their own tracker.
    """
    from core.auth_service import get_user_from_session_token
    session_token = request.cookies.get("smw_session")
    auth_user = get_user_from_session_token(session_token)
    if not auth_user or str(auth_user["id"]) != user_id:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    cmd_type = body.get("type")
    if not cmd_type:
        return JSONResponse({"error": "Command type required"}, status_code=400)

    # Validate command types
    valid_types = {"capture_level", "reset_run", "start_run", "stop_run", "snes_reset"}
    if cmd_type not in valid_types:
        return JSONResponse({"error": f"Unknown command type: {cmd_type}"}, status_code=400)

    cmd_id = live_state.queue_command(user_id, body)
    return {"ok": True, "command_id": cmd_id}


@router.post("/command-result")
async def submit_command_result(request: Request):
    """Local tracker submits result of a command execution."""
    if not _check_api_key(request):
        return JSONResponse({"error": "Invalid API key"}, status_code=401)
    user_id = _resolve_user_id(request)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    cmd_id = body.get("command_id")
    if not cmd_id:
        return JSONResponse({"error": "command_id required"}, status_code=400)

    live_state.store_command_result(user_id, cmd_id, body)
    return {"ok": True}


@router.get("/command-result/{user_id}/{command_id}")
async def get_command_result(request: Request, user_id: str, command_id: str):
    """Poll for command result (web polls until tracker responds)."""
    result = live_state.get_command_result(user_id, command_id)
    if result is None:
        return {"ok": True, "pending": True}
    return {"ok": True, "pending": False, "result": result}
