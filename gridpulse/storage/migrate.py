"""Apply SQL migrations in numeric order, tracking state in a `_migrations` table.

Usage:
    uv run python -m gridpulse.storage.migrate
    # or inside the container:
    docker compose run --rm migrate

Conventions:
- Migration files live in `gridpulse/storage/migrations/`, named `NNN_description.sql`.
- Files are applied in lexical (= numeric) order.
- Each file runs inside a single transaction. Failures roll back; success records the
  version in `public._migrations`.
- Re-running the migrator is safe: already-applied versions are skipped.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS public._migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def apply_migrations(database_url: str | None = None) -> int:
    """Apply pending migrations. Returns the count of newly-applied files."""
    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL not set")

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        log.info("no migration files found in %s", MIGRATIONS_DIR)
        return 0

    applied_count = 0
    with psycopg.connect(database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(BOOTSTRAP_SQL)
            cur.execute("SELECT version FROM public._migrations")
            applied: set[str] = {row[0] for row in cur.fetchall()}
        conn.commit()

        for path in files:
            version = path.stem
            if version in applied:
                log.info("skip  %s (already applied)", version)
                continue
            log.info("apply %s", version)
            sql = path.read_text()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO public._migrations (version) VALUES (%s)",
                        (version,),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                log.exception("failed %s", version)
                raise
            applied_count += 1

    log.info("done — %d new migration(s) applied", applied_count)
    return applied_count


def main() -> int:
    try:
        apply_migrations()
    except Exception as exc:  # noqa: BLE001 — top-level CLI handler
        log.error("migration failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
