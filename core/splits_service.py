"""
Level split tracking — LiveSplit-style PB and best segment queries.
Supports run-definition-ordered display.
"""
from __future__ import annotations

from typing import Any

from core import db
from core.time_utils import utc_now_iso


def record_split(
    session_id: int, game_name: str, level_id: str, level_name: str | None,
    split_ms: int, entered_at: float, exited_at: float,
    death_count: int = 0, best_x: int | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    split_id = db.insert_returning_id(
        """INSERT INTO level_splits (session_id, game_name, level_id, level_name,
            split_ms, entered_at, exited_at, death_count, best_x, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, game_name, level_id, level_name,
         split_ms, entered_at, exited_at, death_count, best_x, now),
    )
    db.commit()
    return {"id": split_id, "split_ms": split_ms}


def get_best_segments(game_name: str) -> list[dict[str, Any]]:
    return db.fetchall(
        """SELECT level_id, COALESCE(MAX(level_name), level_id) AS level_name,
                  MIN(split_ms) AS best_ms, COUNT(*) AS attempt_count,
                  MIN(death_count) AS best_death_count
           FROM level_splits WHERE game_name = ?
           GROUP BY level_id ORDER BY MIN(entered_at)""",
        (game_name,),
    )


def get_sum_of_best(game_name: str) -> int:
    row = db.fetchone(
        """SELECT COALESCE(SUM(best_ms), 0) AS sob
           FROM (SELECT MIN(split_ms) AS best_ms FROM level_splits
                 WHERE game_name = ? GROUP BY level_id)""",
        (game_name,),
    )
    return row["sob"] if row else 0


def get_pb_run(game_name: str) -> dict[str, Any] | None:
    max_row = db.fetchone(
        """SELECT MAX(level_count) AS max_levels FROM (
            SELECT COUNT(DISTINCT level_id) AS level_count
            FROM level_splits WHERE game_name = ? GROUP BY session_id)""",
        (game_name,),
    )
    if not max_row or not max_row["max_levels"]:
        return None

    pb_session = db.fetchone(
        """SELECT session_id, COUNT(DISTINCT level_id) AS levels_completed,
                  SUM(split_ms) AS total_ms, SUM(death_count) AS total_deaths
           FROM level_splits WHERE game_name = ?
           GROUP BY session_id HAVING COUNT(DISTINCT level_id) = ?
           ORDER BY SUM(split_ms) ASC LIMIT 1""",
        (game_name, max_row["max_levels"]),
    )
    if not pb_session:
        return None

    splits = db.fetchall(
        """SELECT level_id, COALESCE(level_name, level_id) AS level_name,
                  split_ms, death_count, best_x
           FROM level_splits WHERE session_id = ? AND game_name = ?
           ORDER BY entered_at""",
        (pb_session["session_id"], game_name),
    )

    return {
        "session_id": pb_session["session_id"],
        "levels_completed": pb_session["levels_completed"],
        "total_ms": pb_session["total_ms"],
        "total_deaths": pb_session["total_deaths"],
        "splits": splits,
    }


def get_current_run_splits(session_id: int, game_name: str) -> list[dict[str, Any]]:
    return db.fetchall(
        """SELECT level_id, COALESCE(level_name, level_id) AS level_name,
                  split_ms, death_count, best_x
           FROM level_splits WHERE session_id = ? AND game_name = ?
           ORDER BY entered_at""",
        (session_id, game_name),
    )


def _level_id_filter(level_ids: list[str]) -> tuple[str, list[str]]:
    """Build a SQL IN clause for level IDs."""
    placeholders = ",".join("?" for _ in level_ids)
    return f"level_id IN ({placeholders})", list(level_ids)


def get_best_segments_for_run(game_name: str, run_level_ids: list[str]) -> list[dict[str, Any]]:
    """Get best segments scoped to specific levels (from a run definition)."""
    if not run_level_ids:
        return get_best_segments(game_name)
    in_clause, params = _level_id_filter(run_level_ids)
    return db.fetchall(
        f"""SELECT level_id, COALESCE(MAX(level_name), level_id) AS level_name,
                  MIN(split_ms) AS best_ms, COUNT(*) AS attempt_count,
                  MIN(death_count) AS best_death_count
           FROM level_splits WHERE game_name = ? AND {in_clause}
           GROUP BY level_id ORDER BY MIN(entered_at)""",
        [game_name] + params,
    )


def get_sum_of_best_for_run(game_name: str, run_level_ids: list[str]) -> int:
    """Get SOB scoped to specific levels."""
    if not run_level_ids:
        return get_sum_of_best(game_name)
    in_clause, params = _level_id_filter(run_level_ids)
    row = db.fetchone(
        f"""SELECT COALESCE(SUM(best_ms), 0) AS sob
           FROM (SELECT MIN(split_ms) AS best_ms FROM level_splits
                 WHERE game_name = ? AND {in_clause} GROUP BY level_id)""",
        [game_name] + params,
    )
    return row["sob"] if row else 0


def get_pb_run_for_levels(game_name: str, run_level_ids: list[str]) -> dict[str, Any] | None:
    """Get PB run scoped to specific levels. A 'complete' run must have all the listed levels."""
    if not run_level_ids:
        return get_pb_run(game_name)

    target_count = len(run_level_ids)
    in_clause, params = _level_id_filter(run_level_ids)

    # Find sessions that completed ALL run levels
    pb_session = db.fetchone(
        f"""SELECT session_id, COUNT(DISTINCT level_id) AS levels_completed,
                  SUM(split_ms) AS total_ms, SUM(death_count) AS total_deaths
           FROM level_splits WHERE game_name = ? AND {in_clause}
           GROUP BY session_id HAVING COUNT(DISTINCT level_id) = ?
           ORDER BY SUM(split_ms) ASC LIMIT 1""",
        [game_name] + params + [target_count],
    )
    if not pb_session:
        return None

    splits = db.fetchall(
        f"""SELECT level_id, COALESCE(level_name, level_id) AS level_name,
                  split_ms, death_count, best_x
           FROM level_splits WHERE session_id = ? AND game_name = ? AND {in_clause}
           ORDER BY entered_at""",
        [pb_session["session_id"], game_name] + params,
    )

    return {
        "session_id": pb_session["session_id"],
        "levels_completed": pb_session["levels_completed"],
        "total_ms": pb_session["total_ms"],
        "total_deaths": pb_session["total_deaths"],
        "splits": splits,
    }


def get_level_history(game_name: str, level_id: str) -> list[dict[str, Any]]:
    return db.fetchall(
        """SELECT ls.id, ls.session_id, ls.split_ms, ls.death_count,
                  ls.best_x, ls.created_at, s.start_time AS session_start
           FROM level_splits ls JOIN sessions s ON s.id = ls.session_id
           WHERE ls.game_name = ? AND ls.level_id = ?
           ORDER BY ls.entered_at DESC LIMIT 50""",
        (game_name, level_id),
    )


def get_game_split_summary(game_name: str, run_id: int | None = None) -> dict[str, Any]:
    """
    Return a complete split summary for a game.
    If run_id is provided, scopes PB/SOB/segments to that run's levels.
    """
    # Build run level IDs for scoping
    run_level_ids: list[str] = []
    if run_id:
        from core.run_service import get_run_levels
        from core.level_names import resolve_level_name
        run_levels = get_run_levels(run_id)
        for rl in run_levels:
            lid = rl.get("level_id") or ""
            exit_type = rl.get("exit_type", "normal")
            run_level_ids.append(f"{lid}:secret" if exit_type == "secret" else lid)

    # Use scoped versions when we have run level IDs
    if run_level_ids:
        pb = get_pb_run_for_levels(game_name, run_level_ids)
        all_segments = get_best_segments_for_run(game_name, run_level_ids)
        sob = get_sum_of_best_for_run(game_name, run_level_ids)
    else:
        pb = get_pb_run(game_name)
        all_segments = get_best_segments(game_name)
        sob = get_sum_of_best(game_name)

    total_attempts_row = db.fetchone(
        "SELECT COUNT(DISTINCT session_id) AS attempts FROM level_splits WHERE game_name = ?",
        (game_name,),
    )
    total_attempts = total_attempts_row["attempts"] if total_attempts_row else 0

    # Build lookup of best segments
    seg_lookup: dict[str, dict] = {}
    for seg in all_segments:
        seg_lookup[seg["level_id"]] = seg

    # Build PB lookup
    pb_lookup: dict[str, int] = {}
    if pb and pb.get("splits"):
        for s in pb["splits"]:
            pb_lookup[s["level_id"]] = s["split_ms"]

    # Determine level order
    ordered_level_ids: list[tuple[str, str]] = []  # (level_id, level_name)

    if run_level_ids:
        # Use run definition order (already built above)
        from core.level_names import resolve_level_name
        for split_key in run_level_ids:
            display_name = resolve_level_name(split_key, game_name)
            ordered_level_ids.append((split_key, display_name))
    else:
        from core.level_names import resolve_level_name
        for seg in all_segments:
            display_name = resolve_level_name(seg["level_id"], game_name)
            ordered_level_ids.append((seg["level_id"], display_name))

    # Build comparison list
    comparison = []
    cumulative_pb = 0
    cumulative_best = 0
    for split_key, display_name in ordered_level_ids:
        seg = seg_lookup.get(split_key)
        best_ms = seg["best_ms"] if seg else None
        pb_ms = pb_lookup.get(split_key)
        attempt_count = seg["attempt_count"] if seg else 0

        if best_ms is not None:
            cumulative_best += best_ms
        if pb_ms is not None:
            cumulative_pb += pb_ms

        comparison.append({
            "level_id": split_key,
            "level_name": display_name,
            "best_ms": best_ms,
            "pb_ms": pb_ms,
            "diff_ms": (pb_ms - best_ms) if (pb_ms is not None and best_ms is not None) else None,
            "attempt_count": attempt_count,
            "cumulative_pb_ms": cumulative_pb if pb_ms is not None else None,
            "cumulative_best_ms": cumulative_best,
        })

    return {
        "pb": pb,
        "segments": comparison,
        "sum_of_best_ms": sob,
        "total_attempts": total_attempts,
        "pb_total_ms": pb["total_ms"] if pb else None,
    }
