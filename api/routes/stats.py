from __future__ import annotations

from fastapi import APIRouter, Query

from core import db
from core.metadata_service import get_metadata_by_game_name
from core.splits_service import get_game_split_summary, get_level_history
from core.stats_service import (
    get_death_stats,
    get_game_deaths_by_level,
    get_game_playtime_trend,
    get_game_sessions,
    get_game_summary,
    get_most_played_games,
    get_playtime_trend,
    get_recent_sessions,
    get_sessions_per_day,
)

router = APIRouter(prefix="/stats", tags=["stats"])


def _uid(user_id: int | None) -> int | None:
    """Normalize user_id: 0 and negative values become None."""
    return user_id if user_id and user_id > 0 else None


@router.get("/most-played")
def stats_most_played(user_id: int | None = Query(None)):
    return get_most_played_games(user_id=_uid(user_id))


@router.get("/playtime-trend")
def stats_playtime_trend(user_id: int | None = Query(None)):
    return get_playtime_trend(user_id=_uid(user_id))


@router.get("/sessions-per-day")
def stats_sessions_per_day(user_id: int | None = Query(None)):
    return get_sessions_per_day(user_id=_uid(user_id))


@router.get("/deaths")
def stats_deaths(user_id: int | None = Query(None)):
    return get_death_stats(user_id=_uid(user_id))


@router.get("/recent-sessions")
def stats_recent_sessions(limit: int = Query(20, ge=1, le=100),
                          user_id: int | None = Query(None)):
    return get_recent_sessions(limit=limit, user_id=_uid(user_id))


@router.get("/games")
def stats_all_games(user_id: int | None = Query(None)):
    games = get_most_played_games(user_id=_uid(user_id))
    result = []
    for game in games:
        game_name = game["game_name"]
        meta = get_metadata_by_game_name(game_name)
        result.append({
            **game,
            "display_name": meta.get("display_name", game_name) if meta else game_name,
            "boxart_url": meta.get("boxart_url") if meta else None,
            "platform_name": meta.get("platform_name") if meta else None,
        })
    return result


@router.get("/game/{game_name}")
def stats_game_detail(game_name: str, user_id: int | None = Query(None)):
    uid = _uid(user_id)
    summary = get_game_summary(game_name, user_id=uid)
    meta = get_metadata_by_game_name(game_name)
    deaths = get_game_deaths_by_level(game_name, user_id=uid)
    sessions = get_game_sessions(game_name, user_id=uid)
    playtime = get_game_playtime_trend(game_name, user_id=uid)

    from core.run_service import get_default_run_for_game, get_runs_for_game
    from core.stats_service import get_death_heatmap, get_run_history
    death_heatmap = get_death_heatmap(game_name, user_id=uid)
    run_history = get_run_history(game_name, user_id=uid)
    all_run_defs = get_runs_for_game(game_name)
    default_run = get_default_run_for_game(game_name)

    return {
        "summary": summary,
        "metadata": dict(meta) if meta else None,
        "deaths_by_level": deaths,
        "sessions": sessions,
        "playtime_trend": playtime,
        "death_heatmap": death_heatmap,
        "run_history": run_history,
        "run_definitions": all_run_defs,
        "default_run": dict(default_run) if default_run else None,
    }


@router.get("/game/{game_name}/run/{run_def_id}")
def stats_game_run(game_name: str, run_def_id: int, user_id: int | None = Query(None)):
    """Get run-specific stats."""
    uid = _uid(user_id)
    from core.stats_service import get_run_history, get_pb_progression

    splits = get_game_split_summary(game_name, run_id=run_def_id)
    run_history = get_run_history(game_name, run_definition_id=run_def_id, user_id=uid)
    pb_progression = get_pb_progression(game_name, run_definition_id=run_def_id, user_id=uid)

    attempt_row = db.fetchone(
        "SELECT COUNT(*) AS c FROM sessions WHERE game_name = ? AND run_definition_id = ?",
        (game_name, run_def_id),
    )

    return {
        "splits": splits,
        "run_history": run_history,
        "pb_progression": pb_progression,
        "run_attempts": attempt_row["c"] if attempt_row else 0,
    }


@router.get("/game/{game_name}/level/{level_id}")
def stats_level_history(game_name: str, level_id: str):
    return get_level_history(game_name, level_id)


@router.get("/game/{game_name}/compare")
def compare_runs(game_name: str, run_a: int = Query(...), run_b: int = Query(...)):
    """Compare two runs side by side."""
    from core.level_names import resolve_level_name
    from core.run_service import get_default_run_for_game

    def get_run_splits(session_id: int) -> dict:
        splits = db.fetchall(
            """SELECT level_id, COALESCE(level_name, level_id) AS level_name,
                      split_ms, death_count
               FROM level_splits WHERE session_id = ? AND game_name = ?
               ORDER BY entered_at""",
            (session_id, game_name),
        )
        for s in splits:
            s["level_name"] = resolve_level_name(s["level_id"], game_name)
        session = db.fetchone("SELECT start_time FROM sessions WHERE id = ?", (session_id,))
        total_ms = sum(s["split_ms"] for s in splits)
        total_deaths = sum(s["death_count"] for s in splits)
        return {
            "session_id": session_id,
            "date": session["start_time"] if session else None,
            "splits": splits,
            "total_ms": total_ms,
            "total_deaths": total_deaths,
        }

    a = get_run_splits(run_a)
    b = get_run_splits(run_b)

    best_segments = {}
    best_rows = db.fetchall(
        "SELECT level_id, MIN(split_ms) AS best_ms FROM level_splits WHERE game_name = ? GROUP BY level_id",
        (game_name,),
    )
    for row in best_rows:
        best_segments[row["level_id"]] = row["best_ms"]

    default_run = get_default_run_for_game(game_name)
    level_order = []
    if default_run:
        from core.run_service import get_run_levels
        run_levels = get_run_levels(default_run["id"])
        for rl in run_levels:
            lid = rl.get("level_id", "")
            exit_type = rl.get("exit_type", "normal")
            split_key = f"{lid}:secret" if exit_type == "secret" else lid
            level_order.append(split_key)

    a_lookup = {s["level_id"]: s for s in a["splits"]}
    b_lookup = {s["level_id"]: s for s in b["splits"]}

    if level_order:
        all_levels = level_order
    else:
        seen = set()
        all_levels = []
        for s in a["splits"] + b["splits"]:
            if s["level_id"] not in seen:
                all_levels.append(s["level_id"])
                seen.add(s["level_id"])

    comparison = []
    cum_a = 0
    cum_b = 0
    for lid in all_levels:
        sa = a_lookup.get(lid)
        sb = b_lookup.get(lid)
        a_ms = sa["split_ms"] if sa else None
        b_ms = sb["split_ms"] if sb else None
        best_ms = best_segments.get(lid)
        diff = (a_ms - b_ms) if a_ms is not None and b_ms is not None else None
        if a_ms is not None:
            cum_a += a_ms
        if b_ms is not None:
            cum_b += b_ms
        comparison.append({
            "level_id": lid,
            "level_name": resolve_level_name(lid, game_name),
            "a_ms": a_ms, "b_ms": b_ms, "diff_ms": diff,
            "a_deaths": sa["death_count"] if sa else None,
            "b_deaths": sb["death_count"] if sb else None,
            "best_ms": best_ms,
            "a_is_gold": a_ms is not None and best_ms is not None and a_ms <= best_ms,
            "b_is_gold": b_ms is not None and best_ms is not None and b_ms <= best_ms,
            "cumulative_a": cum_a if a_ms is not None else None,
            "cumulative_b": cum_b if b_ms is not None else None,
        })

    return {
        "run_a": a, "run_b": b, "comparison": comparison,
        "total_diff_ms": a["total_ms"] - b["total_ms"] if a["total_ms"] and b["total_ms"] else None,
    }
