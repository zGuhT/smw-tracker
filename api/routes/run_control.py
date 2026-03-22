"""Manual run control endpoints — split, undo, pause/resume, reset."""
from __future__ import annotations

import json
import time as _time
from typing import Any

from fastapi import APIRouter

from core import db
from core.level_names import resolve_level_name
from core.session_service import get_active_session, stop_active_session
from core.splits_service import record_split
from core.time_utils import utc_now_iso

router = APIRouter(prefix="/run", tags=["run-control"])


def _get_run_state() -> dict[str, Any]:
    """Get current run timing state from DB events."""
    active = get_active_session()
    if not active:
        return {"active": False}

    session_id = active["id"]
    game_name = active["game_name"]

    # Check for pause state
    pause_event = db.fetchone(
        """SELECT details_json FROM game_events
           WHERE session_id = ? AND event_type IN ('run_pause', 'run_resume')
           ORDER BY id DESC LIMIT 1""",
        (session_id,),
    )
    is_paused = False
    if pause_event and pause_event["details_json"]:
        try:
            details = json.loads(pause_event["details_json"])
            is_paused = details.get("paused", False)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "active": True,
        "session_id": session_id,
        "game_name": game_name,
        "is_paused": is_paused,
    }


@router.post("/split")
def manual_split():
    """Manually end the current split — records for the run level being timed, not the hardware level."""
    active = get_active_session()
    if not active:
        return {"error": "No active session"}

    session_id = active["id"]
    game_name = active["game_name"]
    now = _time.time()

    # Find which run level we should be splitting
    # = the next level in the run definition that doesn't have a split yet
    from core.run_service import get_default_run_config
    run_config = get_default_run_config(game_name)

    # Get already-completed splits for this session
    completed = db.fetchall(
        "SELECT level_id FROM level_splits WHERE session_id = ? AND game_name = ? ORDER BY entered_at",
        (session_id, game_name),
    )
    completed_ids = [r["level_id"] for r in completed]

    level_id = None
    level_name = "Manual Split"

    if run_config and run_config.get("levels"):
        # Find first run level not yet split
        for rl in run_config["levels"]:
            lid = rl.get("level_id", "")
            exit_type = rl.get("exit_type", "normal")
            split_key = f"{lid}:secret" if exit_type == "secret" else lid
            if split_key not in completed_ids:
                level_id = split_key
                level_name = resolve_level_name(split_key, game_name)
                break

    if not level_id:
        # Fallback: use hardware level
        latest = db.fetchone(
            "SELECT level_id FROM progress_snapshots WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        level_id = latest["level_id"] if latest else "manual"
        level_name = resolve_level_name(level_id, game_name) if level_id != "manual" else "Manual Split"

    # Find when this split started
    last_split = db.fetchone(
        "SELECT exited_at FROM level_splits WHERE session_id = ? AND game_name = ? ORDER BY entered_at DESC LIMIT 1",
        (session_id, game_name),
    )

    if last_split and last_split["exited_at"]:
        split_start = last_split["exited_at"]
    else:
        run_start_event = db.fetchone(
            "SELECT details_json FROM game_events WHERE session_id = ? AND event_type = 'run_start' ORDER BY id ASC LIMIT 1",
            (session_id,),
        )
        split_start = now
        if run_start_event and run_start_event["details_json"]:
            try:
                details = json.loads(run_start_event["details_json"])
                split_start = details.get("timer_epoch", now)
            except (json.JSONDecodeError, TypeError):
                pass

    split_ms = max(0, int((now - split_start) * 1000))

    # Count deaths since last split
    death_count = 0
    last_exit_event = db.fetchone(
        "SELECT event_time FROM game_events WHERE session_id = ? AND event_type = 'exit' ORDER BY id DESC LIMIT 1",
        (session_id,),
    )
    if last_exit_event:
        row = db.fetchone(
            "SELECT COUNT(*) AS c FROM game_events WHERE session_id = ? AND event_type = 'death' AND event_time > ?",
            (session_id, last_exit_event["event_time"]),
        )
        death_count = row["c"] if row else 0
    else:
        row = db.fetchone(
            "SELECT COUNT(*) AS c FROM game_events WHERE session_id = ? AND event_type = 'death'",
            (session_id,),
        )
        death_count = row["c"] if row else 0

    # Record the split
    result = record_split(
        session_id=session_id, game_name=game_name,
        level_id=level_id, level_name=level_name,
        split_ms=split_ms, entered_at=split_start, exited_at=now,
        death_count=death_count, best_x=None,
    )

    # Post exit event so tracker stays in sync
    now_iso = utc_now_iso()
    db.execute(
        """INSERT INTO game_events (session_id, game_name, event_type, event_time,
            level_id, level_name, x_position, details_json, created_at)
        VALUES (?, ?, 'exit', ?, ?, ?, NULL, ?, ?)""",
        (session_id, game_name, now_iso, level_id, level_name,
         json.dumps({"manual": True, "split_ms": split_ms}), now_iso),
    )
    db.commit()

    return {"success": True, "split_ms": split_ms, "level_id": level_id, "level_name": level_name}


@router.post("/undo")
def undo_last_split():
    """Remove the last completed split and restore timing."""
    active = get_active_session()
    if not active:
        return {"error": "No active session"}

    session_id = active["id"]
    game_name = active["game_name"]

    # Find last split
    last = db.fetchone(
        "SELECT id, level_id, level_name, split_ms FROM level_splits WHERE session_id = ? AND game_name = ? ORDER BY entered_at DESC LIMIT 1",
        (session_id, game_name),
    )
    if not last:
        return {"error": "No splits to undo"}

    # Delete it
    db.execute("DELETE FROM level_splits WHERE id = ?", (last["id"],))
    db.commit()

    return {"success": True, "undone_level": last["level_name"], "undone_ms": last["split_ms"]}


@router.post("/pause")
def pause_resume():
    """Toggle pause/resume for the run timer."""
    active = get_active_session()
    if not active:
        return {"error": "No active session"}

    session_id = active["id"]
    game_name = active["game_name"]
    now = _time.time()
    now_iso = utc_now_iso()

    # Check current pause state
    state = _get_run_state()
    is_paused = state.get("is_paused", False)
    new_paused = not is_paused

    db.execute(
        """INSERT INTO game_events (session_id, game_name, event_type, event_time,
            level_id, level_name, x_position, details_json, created_at)
        VALUES (?, ?, ?, ?, NULL, NULL, NULL, ?, ?)""",
        (session_id, game_name,
         "run_pause" if new_paused else "run_resume",
         now_iso,
         json.dumps({"paused": new_paused, "epoch": now}),
         now_iso),
    )
    db.commit()

    return {"success": True, "paused": new_paused}


@router.post("/reset")
def reset_run(reset_snes: bool = True):
    """Reset the current run — stop session and optionally soft-reset the SNES.
    If the run is complete (all levels split), keeps all splits intact.
    If incomplete, preserves gold splits and deletes the rest.
    """
    active = get_active_session()
    if not active:
        return {"error": "No active session"}

    session_id = active["id"]
    game_name = active["game_name"]

    # Check if run is complete — use session's run definition, not default
    from core.run_service import get_full_run_config, get_default_run_config
    run_def_id = active.get("run_definition_id")
    run_config = get_full_run_config(run_def_id) if run_def_id else get_default_run_config(game_name)
    run_level_ids = set()
    if run_config and run_config.get("levels"):
        for rl in run_config["levels"]:
            lid = rl.get("level_id", "")
            exit_type = rl.get("exit_type", "normal")
            run_level_ids.add(f"{lid}:secret" if exit_type == "secret" else lid)

    current_splits = db.fetchall(
        "SELECT id, level_id, split_ms FROM level_splits WHERE session_id = ? AND game_name = ?",
        (session_id, game_name),
    )
    completed_ids = {s["level_id"] for s in current_splits}
    run_complete = run_level_ids and run_level_ids.issubset(completed_ids)

    golds_kept = 0
    splits_deleted = 0

    if run_complete:
        # Run finished — keep ALL splits, this is a valid completed run
        golds_kept = len(current_splits)
    else:
        # Incomplete run — keep golds, delete the rest
        for split in current_splits:
            best = db.fetchone(
                "SELECT MIN(split_ms) AS best_ms FROM level_splits WHERE game_name = ? AND level_id = ?",
                (game_name, split["level_id"]),
            )
            if best and best["best_ms"] is not None and split["split_ms"] <= best["best_ms"]:
                golds_kept += 1
            else:
                db.execute("DELETE FROM level_splits WHERE id = ?", (split["id"],))
                splits_deleted += 1

    # Delete run_start events
    db.execute("DELETE FROM game_events WHERE session_id = ? AND event_type = 'run_start'", (session_id,))
    db.commit()

    # Stop the session
    stop_active_session()

    # Soft-reset the SNES
    snes_reset = False
    if reset_snes:
        try:
            from hardware.qusb_client import QUsb2SnesClient
            qusb = QUsb2SnesClient()
            qusb.connect()
            qusb.auto_attach_first_device(wait=False)
            qusb.reset()
            qusb.close()
            snes_reset = True
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("SNES reset failed: %s", exc)

    return {
        "success": True, "game_name": game_name,
        "snes_reset": snes_reset, "run_complete": run_complete,
        "golds_kept": golds_kept, "splits_deleted": splits_deleted,
    }
