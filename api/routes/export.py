"""API routes for exporting and importing game configs."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from core.export_service import export_all_games, export_game_config, import_game_config

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/game/{game_name}")
def export_game(game_name: str):
    return export_game_config(game_name)


@router.get("/all")
def export_all():
    return export_all_games()


@router.post("/import/json")
async def import_config_json(request: Request, overwrite: bool = Query(False)):
    """Import game config from JSON body."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    results = []
    try:
        if isinstance(data, list):
            for game_data in data:
                if isinstance(game_data, dict) and "game_name" in game_data:
                    results.append(import_game_config(game_data, overwrite=overwrite))
        elif isinstance(data, dict) and "game_name" in data:
            results.append(import_game_config(data, overwrite=overwrite))
        else:
            return JSONResponse(status_code=400, content={"error": "Expected JSON with 'game_name' field"})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})

    return {"imported": results}
