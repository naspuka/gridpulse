"""FastAPI app entrypoint — Phase 5 serving layer.

App-factory shape so tests can spin up fresh instances. Middleware:
- Sentry SDK init (before app construction so handler exceptions are captured)
- slowapi rate limit (only mounted on /api/v1/*)
- security-conscious response headers on HTML routes
- structured exception handlers for 404 / 500

`/healthz` remains unauthenticated for Caddy upstream checks; everything
else lives under `/` (HTML) or `/api/v1/...` (JSON).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from gridpulse.api import queries
from gridpulse.lib.observability import init_sentry

log = logging.getLogger(__name__)

# Init Sentry before constructing the app so any import-time or handler
# exceptions get captured. No-op when SENTRY_DSN isn't set.
init_sentry(component="api")


# ---------------------------------------------------------------------------
# Templating + static files
# ---------------------------------------------------------------------------

_API_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = _API_DIR / "templates"
STATIC_DIR = _API_DIR / "static"

# Both dirs are committed (empty `.gitkeep` initially); create at runtime
# defensively so the app boots even before Phase 5C-1 ships the templates.
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Rate limiting (slowapi)
# ---------------------------------------------------------------------------

# Per docs/api-design.md: 30/min per IP on /api/v1/*. HTML routes uncapped.
# get_remote_address inspects X-Forwarded-For — works behind Caddy + Cloudflare.
limiter = Limiter(key_func=get_remote_address, default_limits=[])


# ---------------------------------------------------------------------------
# Lifespan: warm the connection pool on startup so the first request isn't
# slow. close_pool on shutdown so tests stay tidy.
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    from gridpulse.storage.postgres import close_pool, get_pool

    try:
        get_pool()
        log.info("Postgres connection pool initialised")
    except Exception as exc:  # noqa: BLE001 — log but keep the app up
        log.warning("Postgres pool init failed (will lazy-init): %s", exc)
    yield
    with suppress(Exception):
        close_pool()


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="GridPulse",
        description=(
            "Real-time UK energy intelligence. Half-hourly carbon intensity, "
            "generation mix, and Octopus Agile prices. Data sources attributed "
            "on the live site footer."
        ),
        version="0.1.0",
        lifespan=_lifespan,
    )

    # Rate-limit hook + handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Static assets (we serve a tiny CSS file later; CDN does most of the work).
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Routes are mounted from sibling modules to keep this file as the
    # composition root only.
    from gridpulse.api.routes import html as html_routes
    from gridpulse.api.routes import json_api as json_routes

    app.include_router(json_routes.router)
    app.include_router(html_routes.router)

    # HTML 404 — fall back to JSON for /api/v1/*, render the template otherwise.
    @app.exception_handler(404)
    async def _not_found(request: Request, exc: HTTPException):  # noqa: ARG001
        if request.url.path.startswith("/api/"):
            return await http_exception_handler(request, exc)
        return HTMLResponse(
            content=templates.get_template("404.html").render(
                request=request,
                regions=[],
                now_utc=__import__("datetime").datetime.now(__import__("datetime").UTC),
            ),
            status_code=404,
        )

    @app.exception_handler(500)
    async def _server_error(request: Request, exc: Exception):  # noqa: ARG001
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "internal server error"}, status_code=500)
        return HTMLResponse(
            content=templates.get_template("500.html").render(
                request=request,
                regions=[],
                now_utc=__import__("datetime").datetime.now(__import__("datetime").UTC),
            ),
            status_code=500,
        )

    return app


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:  # noqa: ARG001
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded — try again shortly"},
        headers={"Retry-After": "60"},
    )


app = create_app()


# ---------------------------------------------------------------------------
# /healthz — kept unauthenticated for Caddy + the CI smoke test
# ---------------------------------------------------------------------------


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict[str, Any]:
    import os

    return {
        "status": "ok" if queries.db_ok() else "degraded",
        "db": "ok" if queries.db_ok() else "fail",
        "version": os.getenv("GIT_SHA", "dev"),
        "environment": os.getenv("ENVIRONMENT", "local"),
    }
