from __future__ import annotations

from fastapi import APIRouter

from core.models import ProgressSnapshotRequest, TrackingEventRequest
from core.tracking_service import record_event, record_progress

router = APIRouter(prefix="/tracking", tags=["tracking"])


@router.post("/event")
def tracking_event(payload: TrackingEventRequest):
    return record_event(
        event_type=payload.event_type,
        game_name=payload.game_name,
        level_id=payload.level_id,
        level_name=payload.level_name,
        x_position=payload.x_position,
        details=payload.details,
    )


@router.post("/progress")
def tracking_progress(payload: ProgressSnapshotRequest):
    return record_progress(
        game_name=payload.game_name,
        level_id=payload.level_id,
        level_name=payload.level_name,
        x_position=payload.x_position,
    )
