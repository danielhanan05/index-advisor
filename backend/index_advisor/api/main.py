from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from index_advisor.api.routers import recommendations, runs, setup, stats, targets, settings
from index_advisor.api.security import router as auth_router
from index_advisor.api.errors import http_exception_handler, validation_exception_handler
from index_advisor.db import has_storage_config
from index_advisor.api.scheduler import start_scheduler, stop_scheduler
from index_advisor.storage.migrations import apply_storage_migrations
from index_advisor.storage.retention import apply_storage_retention
from index_advisor.utils.logging_utils import configure_logging

logger = logging.getLogger(__name__)


def _web_dir() -> Path:
    """Return the bundled React build directory.

    Production packaging copies frontend/dist into backend/index_advisor/web.
    Development can keep using Vite on localhost:5173; this directory simply
    will not exist until a production frontend build is copied here.
    """
    return Path(__file__).resolve().parents[1] / "web"


def _mount_react_frontend(app: FastAPI) -> None:
    """Serve the built React frontend from FastAPI when it is bundled.

    This lets the packaged product run as a single local server:
    - /assets/* is served from the Vite build output.
    - Browser routes like /, /targets, /settings return index.html.

    API routes are registered before this function is called, so real backend
    endpoints continue to take precedence over the frontend catch-all route.
    """
    web_dir = _web_dir()
    index_file = web_dir / "index.html"
    assets_dir = web_dir / "assets"

    if not index_file.exists():
        logger.info("React web build not found at %s; API-only/dev mode is active.", web_dir)
        return

    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_react_app(full_path: str, request: Request):
        # Do not hide accidental API misses behind the React app. Missing API
        # routes should still return a normal API 404.
        if full_path.startswith(("auth/", "setup/", "targets", "runs", "recommendations", "summary", "settings", "scheduler", "query-stats", "table-stats", "engines", "health")):
            raise HTTPException(status_code=404, detail="API route not found")
        return FileResponse(index_file)

    logger.info("Serving bundled React frontend from %s", web_dir)


def _parse_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Run storage bootstrap once on startup."""
    configure_logging()
    if has_storage_config():
        try:
            apply_storage_migrations()
            apply_storage_retention(force=True)
        except Exception:
            logger.exception("Storage bootstrap failed on startup. /health and /setup/status will report the error.")
    else:
        logger.info("Storage database is not configured yet. First-time setup will create storage_db on the target PostgreSQL host.")

    await start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


app = FastAPI(
    title="Database Index Advisor API",
    version="0.2.0",
    description="API for reading workload statistics, validating recommendations, and applying approved indexes.",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Index-Advisor-Token"],
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.include_router(auth_router)
app.include_router(setup.router)
app.include_router(targets.router)
app.include_router(runs.router)
app.include_router(recommendations.router)
app.include_router(stats.router)
app.include_router(settings.router)


_mount_react_frontend(app)
