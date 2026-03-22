"""
Live tracking routes:
  POST /live/push     — tracker pushes state (API key auth)
  GET  /live/state    — poll current state (public)
  GET  /live/stream   — SSE real-time stream (public)
"""
from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.live_state import live_state

router = APIRouter(prefix="/live", tags=["live"])


def _check_api_key(request: Request) -> bool:
    """Validate the tracker's API key."""
    expected = os.environ.get("SMW_API_KEY", "")
    if not expected:
        return True  # No key configured = allow all (local dev)
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:] == expected
    return request.query_params.get("api_key") == expected


@router.post("/push")
async def live_push(request: Request):
    """Receive full session state from the local tracker."""
    if not _check_api_key(request):
        return JSONResponse({"error": "Invalid API key"}, status_code=401)
    try:
        payload = await request.json()
        live_state.update(payload)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/state")
async def live_get_state():
    """Poll the current live state (public)."""
    state = live_state.get_state()
    if state is None:
        return {"is_active": False}
    return state


@router.get("/stream")
async def live_stream():
    """SSE stream of live state updates (public)."""
    queue = live_state.subscribe()

    async def event_generator():
        try:
            # Send current state immediately
            current = live_state.get_state()
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
            live_state.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
