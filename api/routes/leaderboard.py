"""
Leaderboard routes — public stats and rankings across all users.

  GET /leaderboard/fastest/{game_name}   — fastest PB times for a game's default run
  GET /leaderboard/deaths/{game_name}    — death stats per user for a game
  GET /leaderboard/global                — global platform stats and rankings
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from core import db

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("/fastest/{game_name}")
def fastest_times(game_name: str, limit: int = Query(25, ge=1, le=100)):
    """Fastest completed run times for a game's default run definition."""
    # Find the default run
    default_run = db.fetchone(
        "SELECT id, run_name FROM run_definitions WHERE game_name = ? AND is_default = 1 LIMIT 1",
        (game_name,),
    )
    if not default_run:
        # Fall back to first run
        default_run = db.fetchone(
            "SELECT id, run_name FROM run_definitions WHERE game_name = ? ORDER BY id LIMIT 1",
            (game_name,),
        )
    if not default_run:
        return {"run_name": None, "times": []}

    # Get run level count for completion check
    run_level_count = db.fetchone(
        "SELECT COUNT(*) AS c FROM run_levels WHERE run_definition_id = ?",
        (default_run["id"],),
    )
    expected_levels = run_level_count["c"] if run_level_count else 0

    if expected_levels == 0:
        return {"run_name": default_run["run_name"], "times": []}

    # Find sessions where the user completed all levels in this run
    # Sum split times per session, only include sessions with all splits completed
    times = db.fetchall(
        """SELECT s.id AS session_id, s.user_id, u.username, u.display_name,
                  s.start_time,
                  COUNT(ls.id) AS split_count,
                  SUM(ls.split_ms) AS total_ms,
                  SUM(ls.death_count) AS total_deaths
           FROM sessions s
           JOIN users u ON u.id = s.user_id
           JOIN level_splits ls ON ls.session_id = s.id AND ls.game_name = ?
           WHERE s.game_name = ? AND s.user_id IS NOT NULL
           GROUP BY s.id, s.user_id, u.username, u.display_name, s.start_time
           HAVING COUNT(ls.id) >= ?
           ORDER BY SUM(ls.split_ms) ASC
           LIMIT ?""",
        (game_name, game_name, expected_levels, limit),
    )

    # Deduplicate — show only each user's best time
    seen_users = set()
    best_times = []
    for t in times:
        if t["user_id"] not in seen_users:
            seen_users.add(t["user_id"])
            best_times.append(t)

    return {
        "run_name": default_run["run_name"],
        "expected_levels": expected_levels,
        "times": best_times,
    }


@router.get("/deaths/{game_name}")
def death_rankings(game_name: str, limit: int = Query(25, ge=1, le=100)):
    """Death stats per user for a game."""
    stats = db.fetchall(
        """SELECT s.user_id, u.username, u.display_name,
                  COUNT(DISTINCT s.id) AS session_count,
                  SUM(ls.death_count) AS total_deaths,
                  ROUND(CAST(SUM(ls.death_count) AS NUMERIC) /
                        NULLIF(COUNT(ls.id), 0), 1) AS avg_deaths_per_level
           FROM sessions s
           JOIN users u ON u.id = s.user_id
           LEFT JOIN level_splits ls ON ls.session_id = s.id AND ls.game_name = ?
           WHERE s.game_name = ? AND s.user_id IS NOT NULL
           GROUP BY s.user_id, u.username, u.display_name
           ORDER BY total_deaths DESC
           LIMIT ?""",
        (game_name, game_name, limit),
    )
    return stats


@router.get("/global")
def global_stats():
    """Global platform stats and user rankings."""
    import logging
    log = logging.getLogger(__name__)

    # Overall stats
    try:
        totals = db.fetchone("""
            SELECT
                (SELECT COUNT(*) FROM users WHERE email_verified = 1 AND username != 'default') AS total_users,
                (SELECT COUNT(*) FROM sessions WHERE user_id IS NOT NULL) AS total_sessions,
                (SELECT COUNT(DISTINCT game_name) FROM sessions WHERE user_id IS NOT NULL) AS total_games,
                (SELECT COUNT(*) FROM game_events WHERE event_type = 'death') AS total_deaths
        """)
    except Exception as e:
        log.error("Global totals query failed: %s", e)
        totals = {"total_users": 0, "total_sessions": 0, "total_games": 0, "total_deaths": 0}

    # Most active users (by session count)
    try:
        most_active = db.fetchall("""
            SELECT s.user_id, u.username, u.display_name,
                   COUNT(*) AS session_count,
                   COUNT(DISTINCT s.game_name) AS games_played
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.user_id IS NOT NULL AND u.email_verified = 1 AND u.username != 'default'
            GROUP BY s.user_id, u.username, u.display_name
            ORDER BY session_count DESC
            LIMIT 10
        """)
    except Exception as e:
        log.error("Most active query failed: %s", e)
        most_active = []

    # Most deaths (total across all games)
    try:
        most_deaths = db.fetchall("""
            SELECT s.user_id, u.username, u.display_name,
                   SUM(ls.death_count) AS total_deaths,
                   COUNT(DISTINCT s.game_name) AS games_played
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            JOIN level_splits ls ON ls.session_id = s.id
            WHERE s.user_id IS NOT NULL AND u.email_verified = 1
            GROUP BY s.user_id, u.username, u.display_name
            ORDER BY total_deaths DESC
            LIMIT 10
        """)
    except Exception as e:
        log.error("Most deaths query failed: %s", e)
        most_deaths = []

    # Lowest average deaths per level (min 10 splits to qualify)
    try:
        most_efficient = db.fetchall("""
            SELECT s.user_id, u.username, u.display_name,
                   COUNT(ls.id) AS total_splits,
                   SUM(ls.death_count) AS total_deaths,
                   ROUND(CAST(SUM(ls.death_count) AS NUMERIC) / COUNT(ls.id), 2) AS avg_deaths_per_level
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            JOIN level_splits ls ON ls.session_id = s.id
            WHERE s.user_id IS NOT NULL AND u.email_verified = 1
            GROUP BY s.user_id, u.username, u.display_name
            HAVING COUNT(ls.id) >= 10
            ORDER BY avg_deaths_per_level ASC
            LIMIT 10
        """)
    except Exception as e:
        log.error("Most efficient query failed: %s", e)
        most_efficient = []

    # Most played games
    try:
        popular_games = db.fetchall("""
            SELECT s.game_name,
                   COUNT(DISTINCT s.user_id) AS player_count,
                   COUNT(*) AS session_count
            FROM sessions s
            WHERE s.user_id IS NOT NULL
            GROUP BY s.game_name
            ORDER BY player_count DESC, session_count DESC
            LIMIT 10
        """)
    except Exception as e:
        log.error("Popular games query failed: %s", e)
        popular_games = []

    return {
        "totals": totals,
        "most_active": most_active,
        "most_deaths": most_deaths,
        "most_efficient": most_efficient,
        "popular_games": popular_games,
    }
