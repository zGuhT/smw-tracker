"""API routes for run definitions and their ordered level lists."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from core.run_service import (
    create_run, delete_run, get_default_run_config, get_full_run_config,
    get_runs_for_game, set_run_levels, update_run,
)

router = APIRouter(prefix="/runs", tags=["runs"])


class RunCreateRequest(BaseModel):
    game_name: str = Field(..., min_length=1)
    run_name: str = Field(..., min_length=1)
    is_default: bool = False
    start_delay_ms: int = 0


class RunUpdateRequest(BaseModel):
    run_name: str | None = None
    is_default: bool | None = None
    start_delay_ms: int | None = None


class RunLevelEntry(BaseModel):
    game_level_id: int
    exit_type: str = "normal"
    sort_order: int = 0


class SetRunLevelsRequest(BaseModel):
    levels: list[RunLevelEntry]


@router.get("/game/{game_name}")
def list_runs(game_name: str):
    return get_runs_for_game(game_name)


@router.get("/game/{game_name}/default")
def get_default_run(game_name: str):
    config = get_default_run_config(game_name)
    if not config:
        return {"run": None, "levels": []}
    return config


@router.post("/")
def create_run_route(payload: RunCreateRequest):
    return create_run(
        game_name=payload.game_name, run_name=payload.run_name,
        is_default=payload.is_default, start_delay_ms=payload.start_delay_ms,
    )


@router.get("/{run_id}")
def get_run(run_id: int):
    config = get_full_run_config(run_id)
    if not config:
        raise HTTPException(404, "Run not found")
    return config


@router.put("/{run_id}")
def update_run_route(run_id: int, payload: RunUpdateRequest):
    result = update_run(
        run_id, run_name=payload.run_name,
        is_default=payload.is_default, start_delay_ms=payload.start_delay_ms,
    )
    if not result:
        raise HTTPException(404, "Run not found")
    return result


@router.delete("/{run_id}")
def delete_run_route(run_id: int):
    delete_run(run_id)
    return {"success": True}


@router.put("/{run_id}/levels")
def update_run_levels(run_id: int, payload: SetRunLevelsRequest):
    from core.run_service import get_run_by_id
    if not get_run_by_id(run_id):
        raise HTTPException(404, "Run not found")
    levels = [{"game_level_id": l.game_level_id, "exit_type": l.exit_type,
               "sort_order": l.sort_order} for l in payload.levels]
    return set_run_levels(run_id, levels)
