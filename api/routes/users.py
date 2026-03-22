"""API routes for user management."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.user_service import (
    create_user,
    get_all_users,
    get_or_create_default_user,
    get_user_by_id,
    get_user_by_username,
)

router = APIRouter(prefix="/users", tags=["users"])


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    display_name: str | None = None


@router.get("/")
def list_users():
    """List all users (without API keys)."""
    return get_all_users()


@router.get("/default")
def get_default_user():
    """Get or create the default user."""
    user = get_or_create_default_user()
    return {"id": user["id"], "username": user["username"],
            "display_name": user["display_name"]}


@router.post("/")
def create_user_route(request: Request, payload: UserCreateRequest):
    """Create a new user. Admin only (local requests)."""
    is_local = getattr(request.state, "is_local", False)
    if not is_local:
        return JSONResponse({"error": "Admin only"}, status_code=403)

    existing = get_user_by_username(payload.username)
    if existing:
        raise HTTPException(409, f"Username '{payload.username}' already taken")

    user = create_user(username=payload.username, display_name=payload.display_name)
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "api_key": user["api_key"],  # Only shown on creation
    }


@router.get("/{user_id}")
def get_user(user_id: int):
    """Get a user by ID (without API key)."""
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    return {"id": user["id"], "username": user["username"],
            "display_name": user["display_name"],
            "created_at": user["created_at"]}
