"""FastAPI app entrypoint.

V1 starts as a `/healthz`-only stub. Routes get added in Phase 5 (serving layer).
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from fastapi import FastAPI

from gridpulse.lib.observability import init_sentry

# Init Sentry before constructing the app so request-handler exceptions get
# captured. No-op if SENTRY_DSN isn't set (local dev friendly).
init_sentry(component="api")

app = FastAPI(title="GridPulse", version="0.1.0")


def _db_ok(database_url: str | None) -> bool:
    if not database_url:
        return False
    try:
        with psycopg.connect(database_url, connect_timeout=2) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() == (1,)
    except Exception:
        return False


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """Liveness + DB reachability. Used by CI smoke and Caddy upstream checks."""
    db_ok = _db_ok(os.environ.get("DATABASE_URL"))
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "fail",
        "version": os.getenv("GIT_SHA", "dev"),
        "environment": os.getenv("ENVIRONMENT", "local"),
    }
