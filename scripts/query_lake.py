"""DuckDB-on-Iceberg ad-hoc query script.

The point of this script (per CLAUDE.md's interview-soundbite section):
8 years of half-hourly data, queried in seconds, on a £7/month VM, by
pushing predicates into Iceberg's partition stats. Run a sample query and
print timing + rows so the value of the dual-storage architecture is
immediately visible.

Run inside the dagster container so R2/catalog credentials are present:

    docker compose exec dagster-daemon python -m scripts.query_lake

Or with --query "..." for ad-hoc SQL. Use the `iceberg_scan('...')` UDF
returned by DuckDB's Iceberg extension to address tables.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Any

import duckdb

from gridpulse.storage.iceberg import NAMESPACE

log = logging.getLogger(__name__)


_DEFAULT_QUERY = f"""
-- Average national carbon intensity per month, last 24 months.
SELECT
    date_trunc('month', period_start_utc) AS month,
    avg(actual_gco2_per_kwh)               AS avg_actual_gco2_per_kwh,
    avg(forecast_gco2_per_kwh)             AS avg_forecast_gco2_per_kwh,
    count(*)                               AS half_hours
FROM iceberg_scan('s3://${{R2_BUCKET}}/{NAMESPACE}/carbon_intensity')
WHERE region_id = 0
  AND period_start_utc >= now() - INTERVAL 24 MONTH
GROUP BY 1
ORDER BY 1 DESC
LIMIT 24;
"""


def _wire_duckdb_for_r2(con: duckdb.DuckDBPyConnection) -> None:
    """INSTALL iceberg, register an S3 SECRET that points at R2."""
    con.execute("INSTALL iceberg; LOAD iceberg;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    # Our catalog is the SQL catalog (Postgres), not a file-based one. DuckDB
    # can't see our metadata pointer, so it has to glob R2 to find the
    # current snapshot. Safe for our one-writer / scheduled cadence.
    con.execute("SET unsafe_enable_version_guessing = true;")
    endpoint = os.environ["R2_ENDPOINT"]
    # DuckDB wants endpoint as host only (no scheme); strip if present.
    if endpoint.startswith("https://"):
        endpoint = endpoint.removeprefix("https://")
    con.execute(
        """
        CREATE OR REPLACE SECRET r2 (
            TYPE       S3,
            KEY_ID     $key,
            SECRET     $secret,
            ENDPOINT   $endpoint,
            REGION     'auto',
            URL_STYLE  'path'
        )
        """,
        {
            "key": os.environ["R2_ACCESS_KEY_ID"],
            "secret": os.environ["R2_SECRET_ACCESS_KEY"],
            "endpoint": endpoint,
        },
    )


def run(query: str) -> int:
    con = duckdb.connect()
    _wire_duckdb_for_r2(con)

    # Substitute env vars into ${VAR} placeholders for convenience in the SQL.
    bucket = os.environ["R2_BUCKET"]
    query = query.replace("${R2_BUCKET}", bucket)

    started = time.monotonic()
    result: list[tuple[Any, ...]] = con.execute(query).fetchall()
    elapsed = time.monotonic() - started

    columns = [d[0] for d in con.description]
    print("\t".join(columns))
    for row in result:
        print("\t".join(str(c) for c in row))
    log.info("%d row(s) in %.3fs", len(result), elapsed)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--query", default=_DEFAULT_QUERY, help="SQL to run. Default = monthly intensity rollup."
    )
    args = parser.parse_args()
    try:
        return run(args.query)
    except Exception as exc:  # noqa: BLE001
        log.error("query failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
