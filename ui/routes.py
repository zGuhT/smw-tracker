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
