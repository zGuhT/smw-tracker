"""
Stats queries — all aggregation pushed to SQL.
Includes per-game detail queries for the game detail page.
"""
from __future__ import annotations

from typing import Any

from core import db
from core.time_utils import utc_now_iso

_DUR = db.duration_sql()
_DATE = db.date_sql()


def get_most_played_games() -> list[dict[str, Any]]:
    now = utc_now_iso()
    return db.fetchall(
        f"""
        SELECT
            game_name,
            SUM({_DUR})
                AS total_playtime_seconds,
            COUNT(*) AS session_count
        FROM sessions
        GROUP BY game_name
        ORDER BY total_playtime_seconds DESC
        """,
        (now,),
    )


def get_playtime_trend() -> list[dict[str, Any]]:
    now = utc_now_iso()
    return db.fetchall(
        f"""
        SELECT
            {_DATE} AS date,
            SUM({_DUR})
                AS total_playtime_seconds
        FROM sessions
        GROUP BY {_DATE}
        ORDER BY date
        """,
        (now,),
    )


def get_sessions_per_day() -> list[dict[str, Any]]:
    return db.fetchall(
        f"""
        SELECT {_DATE} AS date, COUNT(*) AS session_count
        FROM sessions
        GROUP BY {_DATE}
        ORDER BY date
        """
    )


def get_death_stats() -> list[dict[str, Any]]:
    from core.level_names import resolve_level_name
    rows = db.fetchall(
        f"""
        SELECT level_id, game_name, COUNT(*) AS death_count,
               COUNT(DISTINCT session_id) AS sessions_with_deaths
        FROM game_events
        WHERE event_type = 'death'
        GROUP BY game_name, level_id
        ORDER BY death_count DESC
        LIMIT 20
        """
    )
    for row in rows:
        row["level"] = resolve_level_name(row.get("level_id"), row.get("game_name"))
        att_row = db.fetchone(
            "SELECT COUNT(*) AS c FROM level_splits WHERE game_name = ? AND level_id = ?",
            (row["game_name"], row["level_id"]),
        )
        att = att_row["c"] if att_row else 1
        row["attempts"] = att
        row["avg_deaths"] = round(row["death_count"] / max(att, 1), 1)
    return rows


def get_recent_sessions(limit: int = 20) -> list[dict[str, Any]]:
    now = utc_now_iso()
    return db.fetchall(
        f"""
        SELECT
            id, game_name, platform, start_time, end_time, is_active,
            {_DUR}
                AS duration_seconds
        FROM sessions
        ORDER BY id DESC
        LIMIT ?
        """,
        (now, limit),
    )


# ── Per-game detail queries ──

def get_game_summary(game_name: str) -> dict[str, Any]:
    """Return aggregate stats for a single game."""
    now = utc_now_iso()

    totals = db.fetchone(
        f"""
        SELECT
            COUNT(*) AS session_count,
            SUM({_DUR})
                AS total_playtime_seconds,
            MIN(start_time) AS first_played,
            MAX(start_time) AS last_played
        FROM sessions
        WHERE game_name = ?
        """,
        (now, game_name),
    ) or {}

    death_row = db.fetchone(
        "SELECT COUNT(*) AS total_deaths FROM game_events WHERE game_name = ? AND event_type = 'death'",
        (game_name,),
    )

    exit_row = db.fetchone(
        "SELECT COUNT(*) AS total_exits FROM game_events WHERE game_name = ? AND event_type = 'exit'",
        (game_name,),
    )

    return {
        "game_name": game_name,
        "session_count": totals.get("session_count", 0),
        "total_playtime_seconds": totals.get("total_playtime_seconds", 0),
        "first_played": totals.get("first_played"),
        "last_played": totals.get("last_played"),
        "total_deaths": death_row["total_deaths"] if death_row else 0,
        "total_exits": exit_row["total_exits"] if exit_row else 0,
    }


def get_game_deaths_by_level(game_name: str) -> list[dict[str, Any]]:
    """Return death counts per level with attempt count and average."""
    from core.level_names import resolve_level_name
    rows = db.fetchall(
        f"""
        SELECT ge.level_id,
               COUNT(*) AS death_count,
               COUNT(DISTINCT ge.session_id) AS sessions_with_deaths
        FROM game_events ge
        WHERE ge.game_name = ? AND ge.event_type = 'death'
        GROUP BY ge.level_id
        ORDER BY death_count DESC
        """,
        (game_name,),
    )
    # Get attempt count per level from splits
    attempts = {}
    att_rows = db.fetchall(
        "SELECT level_id, COUNT(*) AS attempts FROM level_splits WHERE game_name = ? GROUP BY level_id",
        (game_name,),
    )
    for ar in att_rows:
        attempts[ar["level_id"]] = ar["attempts"]

    for row in rows:
        row["level"] = resolve_level_name(row.get("level_id"), game_name)
        att = attempts.get(row["level_id"], 1)
        row["attempts"] = att
        row["avg_deaths"] = round(row["death_count"] / max(att, 1), 1)
    return rows


def get_game_sessions(game_name: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent sessions for a specific game."""
    now = utc_now_iso()
    return db.fetchall(
        f"""
        SELECT
            id, game_name, platform, start_time, end_time, is_active,
            {_DUR}
                AS duration_seconds
        FROM sessions
        WHERE game_name = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (now, game_name, limit),
    )


def get_game_playtime_trend(game_name: str) -> list[dict[str, Any]]:
    """Return daily playtime for a specific game."""
    now = utc_now_iso()
    return db.fetchall(
        f"""
        SELECT
            {_DATE} AS date,
            SUM({_DUR})
                AS total_playtime_seconds
        FROM sessions
        WHERE game_name = ?
        GROUP BY {_DATE}
        ORDER BY date
        """,
        (now, game_name),
    )


def get_death_heatmap(game_name: str, level_id: str | None = None) -> list[dict[str, Any]]:
    """Return death positions for heatmap visualization.
    Groups deaths by level_id and x_position bucket (rounded to nearest 16px).
    """
    from core.level_names import resolve_level_name

    if level_id:
        rows = db.fetchall(
            """SELECT level_id, x_position, COUNT(*) AS count
               FROM game_events
               WHERE game_name = ? AND event_type = 'death'
                 AND level_id = ? AND x_position IS NOT NULL
               GROUP BY level_id, x_position
               ORDER BY x_position""",
            (game_name, level_id),
        )
    else:
        rows = db.fetchall(
            """SELECT level_id, x_position, COUNT(*) AS count
               FROM game_events
               WHERE game_name = ? AND event_type = 'death'
                 AND x_position IS NOT NULL
               GROUP BY level_id, x_position
               ORDER BY level_id, x_position""",
            (game_name,),
        )

    # Bucket into 32px ranges and resolve names
    buckets: dict[str, dict[int, int]] = {}
    for row in rows:
        lid = row["level_id"] or "?"
        bucket = (row["x_position"] // 32) * 32
        if lid not in buckets:
            buckets[lid] = {}
        buckets[lid][bucket] = buckets[lid].get(bucket, 0) + row["count"]

    result = []
    for lid, positions in buckets.items():
        level_name = resolve_level_name(lid, game_name)
        total = sum(positions.values())
        hotspots = sorted(positions.items(), key=lambda x: -x[1])[:10]  # Top 10 death spots
        result.append({
            "level_id": lid,
            "level_name": level_name,
            "total_deaths": total,
            "positions": [{"x": x, "count": c} for x, c in sorted(positions.items())],
            "hotspots": [{"x": x, "count": c} for x, c in hotspots],
        })

    return sorted(result, key=lambda x: -x["total_deaths"])


def get_run_history(game_name: str, run_definition_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Return completed runs with their splits, optionally filtered by run definition."""
    from core.level_names import resolve_level_name

    if run_definition_id:
        sessions = db.fetchall(
            """SELECT DISTINCT ls.session_id, s.start_time, s.run_definition_id,
                      COUNT(DISTINCT ls.level_id) AS levels_completed,
                      SUM(ls.split_ms) AS total_ms,
                      SUM(ls.death_count) AS total_deaths
               FROM level_splits ls
               JOIN sessions s ON s.id = ls.session_id
               WHERE ls.game_name = ? AND s.run_definition_id = ?
               GROUP BY ls.session_id
               ORDER BY s.start_time DESC
               LIMIT ?""",
            (game_name, run_definition_id, limit),
        )
    else:
        sessions = db.fetchall(
            """SELECT DISTINCT ls.session_id, s.start_time, s.run_definition_id,
                      COUNT(DISTINCT ls.level_id) AS levels_completed,
                      SUM(ls.split_ms) AS total_ms,
                      SUM(ls.death_count) AS total_deaths
               FROM level_splits ls
               JOIN sessions s ON s.id = ls.session_id
               WHERE ls.game_name = ?
               GROUP BY ls.session_id
               ORDER BY s.start_time DESC
               LIMIT ?""",
            (game_name, limit),
        )

    runs = []
    for sess in sessions:
        splits = db.fetchall(
            """SELECT level_id, COALESCE(level_name, level_id) AS level_name,
                      split_ms, death_count
               FROM level_splits
               WHERE session_id = ? AND game_name = ?
               ORDER BY entered_at""",
            (sess["session_id"], game_name),
        )
        for s in splits:
            s["level_name"] = resolve_level_name(s["level_id"], game_name)

        runs.append({
            "session_id": sess["session_id"],
            "date": sess["start_time"],
            "run_definition_id": sess["run_definition_id"],
            "levels_completed": sess["levels_completed"],
            "total_ms": sess["total_ms"],
            "total_deaths": sess["total_deaths"],
            "splits": splits,
        })

    return runs


def get_pb_progression(game_name: str, run_definition_id: int | None = None) -> list[dict[str, Any]]:
    """Return PB times over time for a specific run definition."""
    if run_definition_id:
        # Get the expected level count from the run definition
        from core.run_service import get_run_levels
        run_levels = get_run_levels(run_definition_id)
        expected_levels = len(run_levels)

        sessions = db.fetchall(
            """SELECT ls.session_id, s.start_time,
                      COUNT(DISTINCT ls.level_id) AS levels_completed,
                      SUM(ls.split_ms) AS total_ms
               FROM level_splits ls
               JOIN sessions s ON s.id = ls.session_id
               WHERE ls.game_name = ? AND s.run_definition_id = ?
               GROUP BY ls.session_id
               ORDER BY s.start_time ASC""",
            (game_name, run_definition_id),
        )
    else:
        sessions = db.fetchall(
            """SELECT ls.session_id, s.start_time,
                      COUNT(DISTINCT ls.level_id) AS levels_completed,
                      SUM(ls.split_ms) AS total_ms
               FROM level_splits ls
               JOIN sessions s ON s.id = ls.session_id
               WHERE ls.game_name = ?
               GROUP BY ls.session_id
               ORDER BY s.start_time ASC""",
            (game_name,),
        )
        expected_levels = max((s["levels_completed"] for s in sessions), default=0) if sessions else 0

    if not sessions or expected_levels == 0:
        return []

    pb_history = []
    current_pb = None

    for sess in sessions:
        if sess["levels_completed"] < expected_levels:
            continue
        total = sess["total_ms"]
        if current_pb is None or total < current_pb:
            current_pb = total
            pb_history.append({
                "date": sess["start_time"],
                "session_id": sess["session_id"],
                "total_ms": total,
                "levels_completed": sess["levels_completed"],
            })

    return pb_history
