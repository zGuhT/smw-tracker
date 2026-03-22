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
        live_state.update(payload, user_id=user_id)

        # Sync session data to cloud DB
        if user_id != DEFAULT_USER:
            try:
                _sync_session_to_db(payload, int(user_id))
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Session sync failed: %s", exc)

        return {"ok": True, "user_id": user_id}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


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

    # Sync death count as events (just maintain the count)
    deaths = payload.get("deaths_this_session", 0)
    if deaths and session_id:
        existing_deaths = db.fetchone(
            "SELECT COUNT(*) AS c FROM game_events WHERE session_id = ? AND event_type = 'death'",
            (session_id,),
        )
        current = existing_deaths["c"] if existing_deaths else 0
        # Add missing death events
        for _ in range(deaths - current):
            db.execute(
                """INSERT INTO game_events (session_id, game_name, event_type, event_time,
                    level_id, level_name, x_position, details_json, created_at)
                VALUES (?, ?, 'death', ?, ?, ?, NULL, '{}', ?)""",
                (session_id, game_name, now,
                 payload.get("current_level_id"), payload.get("current_level_name"), now),
            )
        if deaths > current:
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
