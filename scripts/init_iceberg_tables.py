"""Create the three Iceberg tables in the SQL catalog if they don't already exist.

Idempotent — safe to re-run. Used by:
- First-time provisioning on prod (manual via `docker compose exec`).
- CI integration tests that need a live Iceberg catalog.

Usage:
    uv run python -m scripts.init_iceberg_tables
"""

from __future__ import annotations

import logging
import sys

from pyiceberg.exceptions import (
    NamespaceAlreadyExistsError,
    TableAlreadyExistsError,
)

from gridpulse.storage.iceberg import NAMESPACE, get_catalog
from gridpulse.storage.iceberg_schemas import TABLES

log = logging.getLogger(__name__)


def init() -> int:
    """Create the namespace + the three tables. Returns count of new tables."""
    catalog = get_catalog()

    # Namespace first — Iceberg requires it before tables can be created.
    try:
        catalog.create_namespace(NAMESPACE)
        log.info("created namespace %s", NAMESPACE)
    except NamespaceAlreadyExistsError:
        log.info("namespace %s already exists", NAMESPACE)

    new_count = 0
    for name, (schema, partition_spec) in TABLES.items():
        ident = f"{NAMESPACE}.{name}"
        try:
            catalog.create_table(
                identifier=ident,
                schema=schema,
                partition_spec=partition_spec,
            )
            log.info("created table %s", ident)
            new_count += 1
        except TableAlreadyExistsError:
            log.info("table %s already exists", ident)
    return new_count


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        count = init()
    except Exception as exc:  # noqa: BLE001 — top-level CLI handler
        log.error("iceberg init failed: %s", exc)
        return 1
    log.info("done — %d new table(s) created", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
