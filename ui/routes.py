from __future__ import annotations
import os
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
router = APIRouter(tags=["ui"])


def _ctx(request: Request, **extra) -> dict:
    """Build template context with auth state."""
    auth_user = getattr(request.state, "auth_user", None)
    return {
        "request": request,
        "is_local": getattr(request.state, "is_local", True),
        "is_authenticated": getattr(request.state, "is_authenticated", False),
        "auth_user": auth_user,
        **extra,
    }


# ── Public pages ──

@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    """Landing page (logged out) or redirect to profile (logged in)."""
    if getattr(request.state, "is_authenticated", False):
        user = getattr(request.state, "auth_user", None)
        if user:
            return RedirectResponse(f"/u/{user['username']}", status_code=302)
    return templates.TemplateResponse("landing.html", _ctx(request))


@router.get("/download", response_class=HTMLResponse)
def download_page(request: Request):
    """Download/install instructions page (placeholder)."""
    return templates.TemplateResponse("download.html", _ctx(request))


@router.get("/games", response_class=HTMLResponse)
def games_library_page(request: Request):
    """Public games library — browse all games."""
    return templates.TemplateResponse("games_library.html", _ctx(request))


@router.get("/leaderboards", response_class=HTMLResponse)
def leaderboards_page(request: Request):
    """Public leaderboards page."""
    return templates.TemplateResponse("leaderboard.html", _ctx(request))


@router.get("/auth/page", response_class=HTMLResponse)
def auth_page(request: Request):
    turnstile_key = os.environ.get("TURNSTILE_SITE_KEY", "")
    return templates.TemplateResponse("auth.html", _ctx(request, turnstile_site_key=turnstile_key))


# ── User pages (public viewing, user-scoped) ──

@router.get("/u/{username}", response_class=HTMLResponse)
def user_profile_page(request: Request, username: str):
    """User's home page — their games, sessions, live link."""
    from core.user_service import get_user_by_username
    user = get_user_by_username(username)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    # Check if this is the logged-in user viewing their own profile
    auth_user = getattr(request.state, "auth_user", None)
    is_own_profile = auth_user and auth_user["id"] == user["id"]
    return templates.TemplateResponse("profile.html", _ctx(
        request,
        profile_user_id=user["id"],
        profile_username=user["username"],
        profile_display_name=user.get("display_name") or user["username"],
        is_own_profile=is_own_profile,
    ))


@router.get("/u/{username}/account", response_class=HTMLResponse)
def user_account_page(request: Request, username: str):
    """Account settings — API key, logout, details. Own account only."""
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user or auth_user["username"] != username:
        return RedirectResponse("/auth/page?login", status_code=302)
    from core import db
    full_user = db.fetchone("SELECT * FROM users WHERE id = ?", (auth_user["id"],))
    return templates.TemplateResponse("account.html", _ctx(
        request,
        account_user=full_user,
    ))


@router.get("/u/{username}/game/{game_name}", response_class=HTMLResponse)
def user_game_detail_page(request: Request, username: str, game_name: str):
    """Per-user game detail page."""
    from core.user_service import get_user_by_username
    user = get_user_by_username(username)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    return templates.TemplateResponse("game.html", _ctx(
        request,
        game_name=game_name,
        profile_user_id=user["id"],
        profile_username=user["username"],
    ))


# ── Game pages (shared data) ──

@router.get("/game/{game_name}", response_class=HTMLResponse)
def game_detail_page(request: Request, game_name: str):
    """Game detail — scoped to logged-in user if authenticated."""
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user:
        return RedirectResponse(f"/u/{auth_user['username']}/game/{game_name}", status_code=302)
    return templates.TemplateResponse("game.html", _ctx(
        request, game_name=game_name,
        profile_user_id=None, profile_username=None,
    ))


@router.get("/game/{game_name}/setup", response_class=HTMLResponse)
def game_setup_page(request: Request, game_name: str):
    return templates.TemplateResponse("setup.html", _ctx(request, game_name=game_name))


# ── Legacy/admin pages ──

@router.get("/tracker", response_class=HTMLResponse)
def web_tracker_page(request: Request):
    """Browser-based tracker client — connects to local QUsb2Snes and pushes to cloud."""
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user:
        return RedirectResponse("/auth/page?login&next=/tracker", status_code=302)
    return templates.TemplateResponse("web_tracker.html", _ctx(
        request,
        user_id=auth_user["id"],
    ))


@router.get("/overlay", response_class=HTMLResponse)
def overlay_page(request: Request):
    return templates.TemplateResponse("overlay.html", _ctx(request))


@router.get("/live", response_class=HTMLResponse)
def live_page(request: Request):
    return templates.TemplateResponse("live.html", _ctx(request))


@router.get("/stats-page", response_class=HTMLResponse)
def stats_page(request: Request):
    return templates.TemplateResponse("stats.html", _ctx(request))


@router.get("/run/{session_id}", response_class=HTMLResponse)
def share_run_page(request: Request, session_id: int):
    """Shareable run page with OG meta tags for social previews."""
    from core import db
    from core.level_names import resolve_level_name

    session = db.fetchone(
        "SELECT s.*, u.username, u.display_name FROM sessions s LEFT JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (session_id,),
    )
    if not session:
        return JSONResponse({"error": "Run not found"}, status_code=404)

    splits = db.fetchall(
        "SELECT level_id, split_ms, death_count FROM level_splits WHERE session_id = ? AND game_name = ? ORDER BY entered_at",
        (session_id, session["game_name"]),
    )
    total_ms = sum(s["split_ms"] for s in splits)
    total_deaths = sum(s["death_count"] for s in splits)

    # Format time for display
    total_sec = total_ms // 1000
    mins = total_sec // 60
    secs = total_sec % 60
    frac = (total_ms % 1000) // 10
    time_str = f"{mins}:{secs:02d}.{frac:02d}" if mins else f"{secs}.{frac:02d}"

    runner = session.get("display_name") or session.get("username") or "Unknown"
    game = session["game_name"]
    title = f"{runner} — {time_str} on {game}"
    description = f"{len(splits)} levels completed with {total_deaths} deaths"

    return templates.TemplateResponse("share_run.html", _ctx(
        request,
        session_id=session_id,
        game_name=game,
        runner=runner,
        username=session.get("username"),
        time_str=time_str,
        total_ms=total_ms,
        total_deaths=total_deaths,
        levels_completed=len(splits),
        start_time=session["start_time"],
        og_title=title,
        og_description=description,
    ))
