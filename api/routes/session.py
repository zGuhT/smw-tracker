from __future__ import annotations

from fastapi import APIRouter

from core.models import SessionCurrentResponse, SessionStartRequest, SessionStopResponse
from core.session_service import get_current_session_payload, start_session, stop_active_session

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/start")
def session_start(payload: SessionStartRequest):
    return start_session(game_name=payload.game_name, platform=payload.platform)


@router.post("/stop", response_model=SessionStopResponse)
def session_stop():
    return {"success": stop_active_session()}


@router.get("/current")
def session_current():
    return get_current_session_payload()
