"""
Public games library routes — browse all games, view details, add to profile.

  GET  /games/library         — list all games with level/run/player stats
  GET  /games/library/{game}  — detail for a specific game
  POST /games/add-to-profile  — add a game to the user's library (creates empty session)
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core import db
from core.auth_service import get_user_from_session_token
from core.time_utils import utc_now_iso

router = APIRouter(prefix="/games", tags=["games"])


@router.get("/library")
def games_library():
    """List all games that have level definitions, with community stats."""
    games = db.fetchall("""
        SELECT gl.game_name,
               COUNT(DISTINCT gl.id) AS level_count,
               (SELECT COUNT(*) FROM run_definitions rd WHERE rd.game_name = gl.game_name) AS run_count,
               (SELECT COUNT(DISTINCT s.user_id) FROM sessions s
                WHERE s.game_name = gl.game_name AND s.user_id IS NOT NULL) AS player_count,
               (SELECT COUNT(*) FROM sessions s WHERE s.game_name = gl.game_name) AS session_count,
               (SELECT COUNT(*) FROM community_configs cc WHERE cc.game_name = gl.game_name) AS config_count
        FROM game_levels gl
        GROUP BY gl.game_name
        ORDER BY player_count DESC, session_count DESC, gl.game_name
    """)

    # Attach metadata (boxart etc.)
    from core.metadata_service import get_metadata_by_game_name
    for g in games:
        meta = get_metadata_by_game_name(g["game_name"])
        g["display_name"] = meta.get("display_name") if meta else None
        g["boxart_url"] = meta.get("boxart_url") if meta else None
        g["platform"] = meta.get("platform_name", "SNES") if meta else "SNES"

    return games


@router.get("/library/{game_name}")
def game_detail(game_name: str):
    """Get details for a specific game — levels, runs, player stats."""
    levels = db.fetchall(
        "SELECT id, level_name, level_id, has_secret_exit FROM game_levels WHERE game_name = ? ORDER BY id",
        (game_name,),
    )
    runs = db.fetchall(
        "SELECT id, run_name, is_default, start_delay_ms FROM run_definitions WHERE game_name = ? ORDER BY id",
        (game_name,),
    )

    # Player leaderboard for this game — best total times
    from core.splits_service import get_pb_run_for_levels
    from core.run_service import get_default_run_for_game

    default_run = get_default_run_for_game(game_name)
    leaderboard = []

    if default_run:
        # Get all users who have played this game
        players = db.fetchall(
            """SELECT DISTINCT s.user_id, u.username, u.display_name
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.game_name = ? AND s.user_id IS NOT NULL""",
            (game_name,),
        )
        run_level_ids = [
            rl["level_id"] for rl in db.fetchall(
                """SELECT gl.level_id FROM run_levels rl
                   JOIN game_levels gl ON gl.id = rl.game_level_id
                   WHERE rl.run_definition_id = ? ORDER BY rl.sort_order""",
                (default_run["id"],),
            )
        ]

    stats = db.fetchone("""
        SELECT COUNT(DISTINCT s.user_id) AS player_count,
               COUNT(*) AS total_sessions,
               SUM(CASE WHEN ge.event_type = 'death' THEN 1 ELSE 0 END) AS total_deaths
        FROM sessions s
        LEFT JOIN game_events ge ON ge.session_id = s.id
        WHERE s.game_name = ?
    """, (game_name,))

    from core.metadata_service import get_metadata_by_game_name
    meta = get_metadata_by_game_name(game_name)

    return {
        "game_name": game_name,
        "display_name": meta.get("display_name") if meta else game_name,
        "boxart_url": meta.get("boxart_url") if meta else None,
        "platform": meta.get("platform_name", "SNES") if meta else "SNES",
        "level_count": len(levels),
        "run_count": len(runs),
        "runs": runs,
        "stats": stats,
    }


@router.post("/add-to-profile")
async def add_game_to_profile(request: Request):
    """Add a game to the user's profile by creating a placeholder session."""
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    game_name = (body.get("game_name") or "").strip()
    if not game_name:
        return JSONResponse({"error": "game_name required"}, status_code=400)

    # Check if user already has this game
    existing = db.fetchone(
        "SELECT id FROM sessions WHERE user_id = ? AND game_name = ? LIMIT 1",
        (user["id"], game_name),
    )
    if existing:
        return {"ok": True, "message": "Game already in your library", "already_exists": True}

    # Create a placeholder session (0 duration, not active)
    now = utc_now_iso()
    db.insert_returning_id(
        """INSERT INTO sessions (user_id, game_name, platform, start_time, end_time,
                                is_active, last_event_time, created_at, updated_at)
        VALUES (?, ?, 'SNES', ?, ?, 0, ?, ?, ?)""",
        (user["id"], game_name, now, now, now, now, now),
    )
    db.commit()

    return {"ok": True, "message": f"Added {game_name} to your library"}


def _get_user(request: Request) -> dict | None:
    token = request.cookies.get("smw_session")
    return get_user_from_session_token(token)
