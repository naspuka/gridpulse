"""PyIceberg catalog + table accessors.

Design per docs/lakehouse-design.md:

- **Catalog**: SQL catalog (`pyiceberg.catalog.sql.SqlCatalog`) backed by our
  existing Postgres in the `iceberg_catalog` schema. No new infrastructure;
  same `pg_dump` covers the catalog; atomic catalog updates via Postgres txns.
- **Warehouse**: Cloudflare R2, S3-compatible. Region "auto" per R2 docs.
- **Tables**: mirror raw.{carbon_intensity, generation_mix, agile_price}.
  See `_schemas.py` for the concrete column definitions; partition spec is
  always `DayTransform(period_start_utc)` (daily partitions).

Conventions:
- One catalog per process. Lazy `get_catalog()` for cheap imports.
- `iceberg_catalog` is the Postgres schema PyIceberg writes catalog metadata
  into; the warehouse path is just an R2 prefix (`s3://<bucket>/`).
- Namespace = "gridpulse". Tables addressed as `gridpulse.carbon_intensity`,
  etc. Naming matches the Postgres source tables (without the schema prefix).
"""

from __future__ import annotations

import logging
import os
from typing import Final

from pyiceberg.catalog import Catalog
from pyiceberg.catalog.sql import SqlCatalog

log = logging.getLogger(__name__)

# Namespace lives at the top of the warehouse hierarchy.
NAMESPACE: Final[str] = "gridpulse"

_catalog: Catalog | None = None


def _r2_warehouse_uri() -> str:
    """`s3://<bucket>/` — PyIceberg appends `<namespace>/<table>/` for layout."""
    bucket = os.environ.get("R2_BUCKET")
    if not bucket:
        raise RuntimeError("R2_BUCKET not set; Iceberg cannot locate warehouse")
    return f"s3://{bucket}/"


def get_catalog() -> Catalog:
    """Process-wide singleton catalog. Cheap to call; lazy-initialised."""
    global _catalog
    if _catalog is not None:
        return _catalog

    # PyIceberg expects a SQLAlchemy-style URL for the catalog backend.
    # We reuse the same Postgres credentials as the rest of the stack — see
    # docs/lakehouse-design.md for the rationale.
    catalog_uri = os.environ.get("ICEBERG_CATALOG_URI")
    if not catalog_uri:
        raise RuntimeError("ICEBERG_CATALOG_URI not set")

    r2_endpoint = os.environ.get("R2_ENDPOINT")
    r2_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (r2_endpoint and r2_key and r2_secret):
        raise RuntimeError("R2_ENDPOINT / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY required")

    _catalog = SqlCatalog(
        NAMESPACE,
        **{
            "uri": catalog_uri,
            "warehouse": _r2_warehouse_uri(),
            "s3.endpoint": r2_endpoint,
            "s3.access-key-id": r2_key,
            "s3.secret-access-key": r2_secret,
            # R2 ignores region but boto3/pyiceberg require *something*.
            "s3.region": "auto",
            # PyIceberg pins the SQLAlchemy URL prefix; ours uses `postgresql://`
            # which is the canonical form.
            "init_catalog_tables": True,
        },
    )
    log.info("Iceberg catalog initialised (warehouse=%s)", _r2_warehouse_uri())
    return _catalog


def close_catalog() -> None:
    """Drop the singleton. For tests mostly; production lets process exit handle it."""
    global _catalog
    _catalog = None
