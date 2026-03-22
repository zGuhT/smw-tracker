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
    """Receive full session state from the local tracker."""
    if not _check_api_key(request):
        return JSONResponse({"error": "Invalid API key"}, status_code=401)
    try:
        payload = await request.json()
        user_id = _resolve_user_id(request)
        live_state.update(payload, user_id=user_id)
        return {"ok": True, "user_id": user_id}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


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
