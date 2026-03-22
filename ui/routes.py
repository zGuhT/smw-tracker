from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(tags=["ui"])


def _ctx(request: Request, **extra) -> dict:
    """Build template context with is_local flag."""
    return {"request": request, "is_local": getattr(request.state, "is_local", True), **extra}


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("home.html", _ctx(request))


@router.get("/stats-page", response_class=HTMLResponse)
def stats_page(request: Request):
    return templates.TemplateResponse("stats.html", _ctx(request))


@router.get("/game/{game_name}", response_class=HTMLResponse)
def game_detail_page(request: Request, game_name: str):
    return templates.TemplateResponse("game.html", _ctx(request, game_name=game_name))


@router.get("/game/{game_name}/setup", response_class=HTMLResponse)
def game_setup_page(request: Request, game_name: str):
    return templates.TemplateResponse("setup.html", _ctx(request, game_name=game_name))


@router.get("/overlay", response_class=HTMLResponse)
def overlay_page(request: Request):
    return templates.TemplateResponse("overlay.html", _ctx(request))


@router.get("/live", response_class=HTMLResponse)
def live_page(request: Request):
    return templates.TemplateResponse("live.html", _ctx(request))


@router.get("/auth/page", response_class=HTMLResponse)
def auth_page(request: Request):
    import os
    turnstile_key = os.environ.get("TURNSTILE_SITE_KEY", "")
    return templates.TemplateResponse("auth.html", _ctx(request, turnstile_site_key=turnstile_key))


@router.get("/u/{username}", response_class=HTMLResponse)
def user_profile_page(request: Request, username: str):
    """Public profile page for a user — shows their games, sessions, and live link."""
    from core.user_service import get_user_by_username
    user = get_user_by_username(username)
    if not user:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "User not found"}, status_code=404)
    return templates.TemplateResponse("profile.html", _ctx(
        request,
        profile_user_id=user["id"],
        profile_username=user["username"],
        profile_display_name=user.get("display_name") or user["username"],
    ))


@router.get("/u/{username}/game/{game_name}", response_class=HTMLResponse)
def user_game_detail_page(request: Request, username: str, game_name: str):
    """Per-user game detail page."""
    from core.user_service import get_user_by_username
    user = get_user_by_username(username)
    if not user:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "User not found"}, status_code=404)
    return templates.TemplateResponse("game.html", _ctx(
        request,
        game_name=game_name,
        profile_user_id=user["id"],
        profile_username=user["username"],
    ))
