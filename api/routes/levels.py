"""API routes for game level definitions."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from core.level_service import (
    create_level, delete_level, get_levels_for_game, update_level,
)

router = APIRouter(prefix="/levels", tags=["levels"])


class LevelCreateRequest(BaseModel):
    game_name: str = Field(..., min_length=1)
    level_name: str = Field(..., min_length=1)
    level_id: str | None = None
    has_secret_exit: bool = False


class LevelUpdateRequest(BaseModel):
    level_name: str | None = None
    level_id: str | None = None
    has_secret_exit: bool | None = None


@router.get("/{game_name}")
def list_levels(game_name: str):
    return get_levels_for_game(game_name)


@router.post("/")
def create_level_route(payload: LevelCreateRequest):
    return create_level(
        game_name=payload.game_name, level_name=payload.level_name,
        level_id=payload.level_id, has_secret_exit=payload.has_secret_exit,
    )


@router.put("/{level_db_id}")
def update_level_route(level_db_id: int, payload: LevelUpdateRequest):
    result = update_level(
        level_db_id, level_name=payload.level_name,
        level_id=payload.level_id, has_secret_exit=payload.has_secret_exit,
    )
    if not result:
        raise HTTPException(404, "Level not found")
    return result


@router.delete("/{level_db_id}")
def delete_level_route(level_db_id: int):
    delete_level(level_db_id)
    return {"success": True}


@router.post("/{level_db_id}/capture")
async def capture_level_id(request: Request, level_db_id: int):
    """Read current level ID from hardware.

    On localhost: reads directly from QUsb2Snes.
    On the web: queues a command for the user's local tracker.
    """
    is_local = getattr(request.state, "is_local", False)

    if is_local:
        # Direct hardware read
        from core.level_service import set_level_id_from_hardware
        from hardware.smw_memory_map import LEVEL_ID
        try:
            from hardware.qusb_client import QUsb2SnesClient
            from core.smw_levels import normalize_level_id
            qusb = QUsb2SnesClient()
            qusb.connect()
            qusb.auto_attach_first_device(wait=False)
            raw = qusb.read_u8(LEVEL_ID.address)
            qusb.close()
            hw_level_id = normalize_level_id(f"{raw:02X}")
            result = set_level_id_from_hardware(level_db_id, hw_level_id)
            if not result:
                raise HTTPException(404, "Level not found")
            return {"success": True, "level_id": hw_level_id, "level": result}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, f"Hardware not available: {exc}")
    else:
        # Remote: queue command for user's local tracker
        from core.auth_service import get_user_from_session_token
        session_token = request.cookies.get("smw_session")
        user = get_user_from_session_token(session_token)
        if not user:
            raise HTTPException(401, "Not logged in")

        from core.live_state import live_state
        user_id = str(user["id"])

        # Check if user's tracker is online
        state = live_state.get_state(user_id=user_id)
        if not state:
            raise HTTPException(503,
                "Your tracker is not connected. Start it with: "
                "python run_tracker.py --cloud --api-key YOUR_KEY")

        cmd_id = live_state.queue_command(user_id, {
            "type": "capture_level",
            "level_db_id": level_db_id,
        })

        # Poll for result (the tracker executes within ~500ms)
        import asyncio
        for _ in range(10):  # Wait up to 5 seconds
            await asyncio.sleep(0.5)
            result = live_state.get_command_result(user_id, cmd_id)
            if result:
                if result.get("success"):
                    # Update the level in the cloud DB
                    from core.level_service import set_level_id_from_hardware
                    updated = set_level_id_from_hardware(level_db_id, result["level_id"])
                    return {"success": True, "level_id": result["level_id"], "level": updated}
                else:
                    raise HTTPException(503, result.get("error", "Capture failed"))

        raise HTTPException(504, "Tracker did not respond in time. Is it running?")
