"""Session lifecycle with resolved level names and run-aware split data."""
from __future__ import annotations

from typing import Any

from core import db
from core.level_names import resolve_level_name, resolve_split_names
from core.time_utils import duration_seconds, utc_now_iso


def close_existing_active_sessions() -> None:
    now = utc_now_iso()
    db.execute("UPDATE sessions SET end_time = ?, is_active = 0, updated_at = ? WHERE is_active = 1", (now, now))
    db.commit()


def start_session(game_name: str, platform: str = "SNES", run_definition_id: int | None = None) -> dict[str, Any]:
    now = utc_now_iso()
    db.execute("UPDATE sessions SET end_time = ?, is_active = 0, updated_at = ? WHERE is_active = 1", (now, now))
    session_id = db.insert_returning_id(
        """INSERT INTO sessions (game_name, platform, start_time, end_time, is_active,
                                last_event_time, run_definition_id, created_at, updated_at)
        VALUES (?, ?, ?, NULL, 1, ?, ?, ?, ?)""",
        (game_name, platform, now, now, run_definition_id, now, now),
    )
    db.commit()
    return db.fetchone("SELECT * FROM sessions WHERE id = ?", (session_id,)) or {}


def stop_active_session() -> bool:
    now = utc_now_iso()
    active = db.fetchone("SELECT id FROM sessions WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
    if not active:
        return False
    db.execute("UPDATE sessions SET end_time = ?, is_active = 0, updated_at = ? WHERE id = ?",
               (now, now, active["id"]))
    db.commit()
    return True


def get_active_session() -> dict[str, Any] | None:
    return db.fetchone("SELECT * FROM sessions WHERE is_active = 1 ORDER BY id DESC LIMIT 1")


def touch_active_session(session_id: int) -> None:
    now = utc_now_iso()
    db.execute("UPDATE sessions SET last_event_time = ?, updated_at = ? WHERE id = ?", (now, now, session_id))
    db.commit()


def get_or_create_active_session(game_name: str, platform: str = "SNES", run_definition_id: int | None = None) -> dict[str, Any]:
    active = get_active_session()
    if active:
        # Update run_definition_id if not set yet
        if run_definition_id and not active.get("run_definition_id"):
            db.execute("UPDATE sessions SET run_definition_id = ? WHERE id = ?", (run_definition_id, active["id"]))
            db.commit()
        return active
    return start_session(game_name=game_name, platform=platform, run_definition_id=run_definition_id)


def get_current_session_payload() -> dict[str, Any]:
    """Build full session response with resolved names and run definition levels."""
    active = get_active_session()

    if not active:
        return {
            "id": None, "game_name": None, "platform": None,
            "start_time": None, "duration_seconds": None, "is_active": False,
            "current_level_id": None, "current_level_name": None,
            "current_x_position": None, "deaths_this_session": 0,
            "splits": [], "run_levels": [], "pb_splits": [],
            "pb_total_ms": None, "sum_of_best_ms": None,
            "run_name": None, "run_started": False,
        }

    session_id = active["id"]
    game_name = active["game_name"]

    latest_progress = db.fetchone(
        "SELECT level_id, level_name, x_position FROM progress_snapshots WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    )

    death_count_row = db.fetchone(
        "SELECT COUNT(*) AS death_count FROM game_events WHERE session_id = ? AND event_type = 'death'",
        (session_id,),
    )

    # Current run splits with resolved names
    current_splits = db.fetchall(
        """SELECT level_id, COALESCE(level_name, level_id) AS level_name,
                  split_ms, death_count, entered_at, exited_at
           FROM level_splits WHERE session_id = ? AND game_name = ? ORDER BY entered_at""",
        (session_id, game_name),
    )
    resolve_split_names(current_splits, game_name)

    # Calculate timing for live timer
    # current_split_start = exited_at of last completed split (epoch seconds)
    # run_start = timer_epoch from run_start event (includes delay)
    import time
    import json
    current_split_start: float | None = None
    run_start_epoch: float | None = None
    run_delay_ms: int = 0

    if current_splits:
        last_split = current_splits[-1]
        current_split_start = last_split.get("exited_at")
        # Run start is timer_epoch from run_start event
        run_start_event = db.fetchone(
            """SELECT details_json FROM game_events
               WHERE session_id = ? AND event_type = 'run_start'
               ORDER BY id ASC LIMIT 1""",
            (session_id,),
        )
        if run_start_event and run_start_event["details_json"]:
            try:
                details = json.loads(run_start_event["details_json"])
                run_start_epoch = details.get("timer_epoch")
                run_delay_ms = details.get("delay_ms", 0)
            except (json.JSONDecodeError, TypeError):
                pass
        if not run_start_epoch:
            run_start_epoch = current_splits[0].get("entered_at")
    else:
        # No splits yet — check for run_start event
        run_start_event = db.fetchone(
            """SELECT details_json FROM game_events
               WHERE session_id = ? AND event_type = 'run_start'
               ORDER BY id ASC LIMIT 1""",
            (session_id,),
        )
        if run_start_event and run_start_event["details_json"]:
            try:
                details = json.loads(run_start_event["details_json"])
                # start_epoch = when transition happened, timer_epoch = start_epoch + delay
                run_start_epoch = details.get("start_epoch")
                run_delay_ms = details.get("delay_ms", 0)
                # current_split_start is the timer_epoch (when the actual timer begins)
                current_split_start = details.get("timer_epoch")
            except (json.JSONDecodeError, TypeError):
                pass

    # Get default run definition for this game (cached per session)
    from core.run_service import get_default_run_config
    cache_key = f"{session_id}:{game_name}"
    if not hasattr(get_current_session_payload, "_cache") or get_current_session_payload._cache_key != cache_key:
        get_current_session_payload._cache_key = cache_key
        get_current_session_payload._cache = {}

    _c = get_current_session_payload._cache

    if "run_config" not in _c:
        _c["run_config"] = get_default_run_config(game_name)

    run_config = _c["run_config"]

    run_name = None
    run_levels = []
    if run_config:
        run_name = run_config.get("run_name")
        for rl in run_config.get("levels", []):
            lid = rl.get("level_id", "")
            exit_type = rl.get("exit_type", "normal")
            split_key = f"{lid}:secret" if exit_type == "secret" else lid
            run_levels.append({
                "level_id": split_key,
                "level_name": resolve_level_name(split_key, game_name),
                "exit_type": exit_type,
            })

    run_level_ids = [rl["level_id"] for rl in run_levels] if run_levels else []

    # PB/SOB/best segments — refresh when split count changes
    from core.splits_service import (
        get_best_segments_for_run, get_pb_run_for_levels, get_sum_of_best_for_run,
    )
    split_count = len(current_splits)
    if _c.get("_split_count") != split_count:
        _c["pb"] = get_pb_run_for_levels(game_name, run_level_ids)
        _c["sob"] = get_sum_of_best_for_run(game_name, run_level_ids)
        _c["best_segments"] = get_best_segments_for_run(game_name, run_level_ids)
        _c["_split_count"] = split_count

    pb = _c["pb"]
    sob = _c["sob"]
    best_segments = _c["best_segments"]

    pb_splits = []
    pb_total_ms = None
    if pb:
        pb_splits = pb.get("splits", [])
        resolve_split_names(pb_splits, game_name)
        pb_total_ms = pb.get("total_ms")

    # Build best segment lookup
    best_by_level = {}
    for seg in best_segments:
        best_by_level[seg["level_id"]] = seg["best_ms"]

    # Check if run is complete (all run levels have splits)
    run_complete = False
    if run_level_ids and current_splits:
        completed_ids = {s["level_id"] for s in current_splits}
        run_complete = all(lid in completed_ids for lid in run_level_ids)

    # Resolve current level name
    current_level_id = latest_progress["level_id"] if latest_progress else None
    current_level_name = resolve_level_name(current_level_id, game_name) if current_level_id else None

    # Check pause state
    pause_event = db.fetchone(
        """SELECT details_json FROM game_events
           WHERE session_id = ? AND event_type IN ('run_pause', 'run_resume')
           ORDER BY id DESC LIMIT 1""",
        (session_id,),
    )
    is_paused = False
    paused_at: float | None = None
    if pause_event and pause_event["details_json"]:
        try:
            pdetails = json.loads(pause_event["details_json"])
            is_paused = pdetails.get("paused", False)
            if is_paused:
                paused_at = pdetails.get("epoch")
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "id": session_id,
        "game_name": game_name,
        "platform": active["platform"],
        "start_time": active["start_time"],
        "duration_seconds": duration_seconds(active["start_time"], active["end_time"]),
        "is_active": bool(active["is_active"]),
        "current_level_id": current_level_id,
        "current_level_name": current_level_name,
        "current_x_position": latest_progress["x_position"] if latest_progress else None,
        "deaths_this_session": death_count_row["death_count"] if death_count_row else 0,
        "splits": current_splits,
        "run_levels": run_levels,
        "run_name": run_name,
        "pb_splits": pb_splits,
        "pb_total_ms": pb_total_ms,
        "sum_of_best_ms": sob,
        "best_segments": best_by_level,
        "current_split_start": current_split_start,
        "run_start_epoch": run_start_epoch,
        "run_delay_ms": run_delay_ms,
        "is_paused": is_paused,
        "paused_at": paused_at,
        "run_complete": run_complete,
        "server_time": time.time(),
    }
