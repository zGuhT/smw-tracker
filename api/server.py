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
    """Block write operations and admin pages for non-local requests."""

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

        request.state.is_local = is_local

        if is_local:
            return await call_next(request)

        # Public user — block write operations (except live push with API key)
        path = request.url.path
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            # Allow /live/push through — it has its own API key auth
            if path == "/live/push":
                return await call_next(request)
            return JSONResponse({"error": "Read-only access"}, status_code=403)

        # Block setup pages
        if "/setup" in path:
            return JSONResponse({"error": "Admin only"}, status_code=403)
        if path == "/overlay":
            return JSONResponse({"error": "Admin only"}, status_code=403)

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    close_thread_connection()


app = FastAPI(title="SMW Tracker", lifespan=lifespan)
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
app.include_router(ui_router)
