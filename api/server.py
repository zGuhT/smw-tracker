"""
FastAPI application entry point.

- Uses lifespan context manager
- Public/private mode: local requests get full access, remote gets read-only
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from api.routes.metadata import router as metadata_router
from api.routes.session import router as session_router
from api.routes.stats import router as stats_router
from api.routes.tracking import router as tracking_router
from api.routes.levels import router as levels_router
from api.routes.runs import router as runs_router
from api.routes.export import router as export_router
from api.routes.run_control import router as run_control_router
from api.routes.live import router as live_router
from api.routes.users import router as users_router
from api.routes.auth import router as auth_router
from api.routes.community import router as community_router
from api.routes.games import router as games_router
from api.routes.leaderboard import router as leaderboard_router
from core.db import close_thread_connection, init_db
from ui.routes import router as ui_router

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "ui" / "static"

LOCAL_IPS = {"127.0.0.1", "::1", "localhost"}

# Read-only endpoints that public users CAN access
PUBLIC_SAFE_PREFIXES = (
    "/session/current",
    "/stats/",
    "/metadata/",
    "/static/",
    "/",
)

# Paths that are always blocked for public users
PUBLIC_BLOCKED_PATHS = (
    "/overlay",
    "/game/", # setup pages matched separately
)


class PublicAccessMiddleware(BaseHTTPMiddleware):
    """Access control: local users get full access, authenticated web users
    get setup/write access, anonymous public users get read-only."""

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        is_local = client_ip in LOCAL_IPS

        # Also check X-Forwarded-For for tunnel setups
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            is_local = forwarded.split(",")[0].strip() in LOCAL_IPS

        # Allow admin secret to bypass (set SMW_ADMIN_KEY env var)
        admin_key = os.environ.get("SMW_ADMIN_KEY")
        if admin_key and request.query_params.get("admin_key") == admin_key:
            is_local = True

        # Check for authenticated web user (session cookie)
        is_authenticated = False
        if not is_local:
            from core.auth_service import get_user_from_session_token
            session_token = request.cookies.get("smw_session")
            if session_token:
                user = get_user_from_session_token(session_token)
                if user:
                    is_authenticated = True
                    request.state.auth_user = user

        request.state.is_local = is_local
        request.state.is_authenticated = is_authenticated

        if is_local:
            return await call_next(request)

        path = request.url.path

        # Write operations
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            # Auth endpoints — always allowed (they handle their own validation)
            if path.startswith("/auth/"):
                return await call_next(request)
            # Live push — has its own API key auth
            if path == "/live/push" or path == "/live/command-result":
                return await call_next(request)
            # Authenticated users can write to levels, runs, export, run-control, commands
            if is_authenticated and any(path.startswith(p) for p in (
                "/levels/", "/runs/", "/export/", "/run/",
                "/session/", "/tracking/", "/community/",
                "/live/command/", "/games/",
            )):
                return await call_next(request)
            return JSONResponse({"error": "Read-only access — log in to make changes"}, status_code=403)

        # Setup pages — allow for authenticated users
        if "/setup" in path:
            if is_authenticated:
                return await call_next(request)
            return JSONResponse({"error": "Log in to access setup"}, status_code=403)

        # Overlay — local only
        if path == "/overlay":
            return JSONResponse({"error": "Admin only"}, status_code=403)

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Auto-create default user on first startup
    try:
        from core.user_service import get_or_create_default_user
        user = get_or_create_default_user()
        import logging
        logging.getLogger("smw").info("Default user ready: id=%s, username=%s", user["id"], user["username"])
    except Exception:
        pass
    yield
    close_thread_connection()


from version import __version__

app = FastAPI(title="SMW Tracker", version=__version__, lifespan=lifespan)
app.add_middleware(PublicAccessMiddleware)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(session_router)
app.include_router(tracking_router)
app.include_router(stats_router)
app.include_router(metadata_router)
app.include_router(levels_router)
app.include_router(runs_router)
app.include_router(export_router)
app.include_router(run_control_router)
app.include_router(live_router)
app.include_router(users_router)
app.include_router(auth_router)
app.include_router(community_router)
app.include_router(games_router)
app.include_router(leaderboard_router)
app.include_router(ui_router)
