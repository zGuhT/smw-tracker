"""
Community config routes — share and import game configurations.

  GET  /community/configs/{game_name}  — list published configs for a game
  GET  /community/configs              — list all published configs
  POST /community/publish/{game_name}  — publish your current config for a game
  POST /community/import/{config_id}   — import a community config into your local DB
  POST /community/verify/{config_id}   — upvote/verify a config
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from core import db
from core.auth_service import get_user_from_session_token
from core.export_service import export_game_config, import_game_config
from core.time_utils import utc_now_iso

router = APIRouter(prefix="/community", tags=["community"])


def _get_user(request: Request) -> dict | None:
    """Get authenticated user from session cookie."""
    token = request.cookies.get("smw_session")
    return get_user_from_session_token(token)


@router.get("/configs")
def list_all_configs():
    """List all published community configs, grouped by game."""
    rows = db.fetchall(
        """SELECT cc.id, cc.game_name, cc.description, cc.verification_count,
                  cc.created_at, u.username, u.display_name
           FROM community_configs cc
           JOIN users u ON u.id = cc.user_id
           ORDER BY cc.game_name, cc.verification_count DESC, cc.id DESC"""
    )
    return rows


@router.get("/configs/{game_name}")
def list_configs_for_game(game_name: str):
    """List published configs for a specific game."""
    rows = db.fetchall(
        """SELECT cc.id, cc.game_name, cc.description, cc.verification_count,
                  cc.created_at, u.username, u.display_name,
                  cc.config_json
           FROM community_configs cc
           JOIN users u ON u.id = cc.user_id
           WHERE cc.game_name = ?
           ORDER BY cc.verification_count DESC, cc.id DESC""",
        (game_name,),
    )
    # Parse config_json to show level/run counts
    for row in rows:
        try:
            config = json.loads(row["config_json"])
            row["level_count"] = len(config.get("levels", []))
            row["run_count"] = len(config.get("runs", []))
        except (json.JSONDecodeError, TypeError):
            row["level_count"] = 0
            row["run_count"] = 0
        # Don't send full config_json in listing
        del row["config_json"]
    return rows


@router.post("/publish/{game_name}")
async def publish_config(request: Request, game_name: str):
    """Publish your current game config to the community."""
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    # Get the current config for this game
    config = export_game_config(game_name)
    if not config.get("levels") and not config.get("runs"):
        return JSONResponse({"error": "No levels or runs defined for this game"}, status_code=400)

    try:
        body = await request.json()
        description = (body.get("description") or "").strip()
    except Exception:
        description = ""

    if not description:
        level_count = len(config.get("levels", []))
        run_count = len(config.get("runs", []))
        description = f"{level_count} levels, {run_count} run(s)"

    now = utc_now_iso()
    config_id = db.insert_returning_id(
        """INSERT INTO community_configs (game_name, user_id, config_json, description, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        (game_name, user["id"], json.dumps(config), description, now),
    )
    db.commit()

    return {
        "ok": True,
        "config_id": config_id,
        "message": f"Published config for {game_name}",
    }


@router.post("/import/{config_id}")
async def import_community_config(request: Request, config_id: int):
    """Import a community config into the local database."""
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    row = db.fetchone("SELECT config_json, game_name FROM community_configs WHERE id = ?", (config_id,))
    if not row:
        raise HTTPException(404, "Config not found")

    try:
        config = json.loads(row["config_json"])
    except (json.JSONDecodeError, TypeError):
        return JSONResponse({"error": "Invalid config data"}, status_code=500)

    # Check if user wants to overwrite
    try:
        body = await request.json()
        overwrite = body.get("overwrite", False)
    except Exception:
        overwrite = False

    result = import_game_config(config, overwrite=overwrite)
    return {"ok": True, "result": result}


@router.post("/verify/{config_id}")
async def verify_config(request: Request, config_id: int):
    """Upvote/verify a community config. Each user can verify once."""
    user = _get_user(request)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)

    # Check config exists
    config = db.fetchone("SELECT id, user_id FROM community_configs WHERE id = ?", (config_id,))
    if not config:
        raise HTTPException(404, "Config not found")

    # Can't verify your own
    if config["user_id"] == user["id"]:
        return JSONResponse({"error": "You can't verify your own config"}, status_code=400)

    # Check if already verified
    existing = db.fetchone(
        "SELECT id FROM config_verifications WHERE config_id = ? AND user_id = ?",
        (config_id, user["id"]),
    )
    if existing:
        return JSONResponse({"error": "You've already verified this config"}, status_code=400)

    now = utc_now_iso()
    db.execute(
        "INSERT INTO config_verifications (config_id, user_id, created_at) VALUES (?, ?, ?)",
        (config_id, user["id"], now),
    )
    db.execute(
        "UPDATE community_configs SET verification_count = verification_count + 1 WHERE id = ?",
        (config_id,),
    )
    db.commit()

    return {"ok": True, "message": "Config verified!"}
