"""
Event and progress recording.
"""
from __future__ import annotations

import json
from typing import Any

from core import db
from core.session_service import get_or_create_active_session, touch_active_session
from core.smw_levels import get_level_name, normalize_level_id
from core.time_utils import utc_now_iso


def _resolve_level_name(
    level_id: str | None, level_name: str | None, game_name: str | None = None
) -> tuple[str | None, str | None]:
    normalized_level_id = normalize_level_id(level_id)
    resolved_level_name = level_name or get_level_name(normalized_level_id, game_name=game_name)
    return normalized_level_id, resolved_level_name


def record_event(
    event_type: str,
    game_name: str,
    level_id: str | None = None,
    level_name: str | None = None,
    x_position: int | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = get_or_create_active_session(game_name=game_name)
    session_id = session["id"]
    now = utc_now_iso()

    level_id, level_name = _resolve_level_name(level_id, level_name, game_name=game_name)
    details_json = json.dumps(details or {})

    event_id = db.insert_returning_id(
        """
        INSERT INTO game_events (session_id, game_name, event_type, event_time,
                                 level_id, level_name, x_position, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, game_name, event_type, now, level_id, level_name, x_position, details_json, now),
    )
    db.commit()

    touch_active_session(session_id)

    return {
        "id": event_id,
        "session_id": session_id,
        "event_type": event_type,
        "game_name": game_name,
        "level_id": level_id,
        "level_name": level_name,
        "x_position": x_position,
        "details": details or {},
    }


def record_progress(
    game_name: str,
    level_id: str | None = None,
    level_name: str | None = None,
    x_position: int | None = None,
) -> dict[str, Any]:
    session = get_or_create_active_session(game_name=game_name)
    session_id = session["id"]
    now = utc_now_iso()

    level_id, level_name = _resolve_level_name(level_id, level_name, game_name=game_name)

    snapshot_id = db.insert_returning_id(
        """
        INSERT INTO progress_snapshots (session_id, game_name, snapshot_time,
                                        level_id, level_name, x_position, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, game_name, now, level_id, level_name, x_position, now),
    )
    db.commit()

    touch_active_session(session_id)

    return {
        "id": snapshot_id,
        "session_id": session_id,
        "game_name": game_name,
        "level_id": level_id,
        "level_name": level_name,
        "x_position": x_position,
    }
