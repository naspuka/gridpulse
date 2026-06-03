"""Iceberg archival assets.

Three jobs:
- `archive_to_iceberg`: nightly, overwrites yesterday's partition for all
  three tables. Idempotent — re-running the same date rewrites the partition.
- `expire_snapshots`: weekly, drops snapshots older than 30 days.

The partition-overwrite semantics are what makes archival safe under
late-arriving data: if a row arrives at 04:00 UTC after yesterday's 02:00
archive, the next night's run *re-overwrites yesterday* (we run with a 2-day
window — yesterday and the day before — to catch this).

This module does NOT use `from __future__ import annotations`.
"""

from datetime import UTC, datetime, timedelta

import pyarrow as pa
from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset
from pyiceberg.expressions import And, GreaterThanOrEqual, LessThan
from pyiceberg.table import Table

from gridpulse.lib.heartbeat import with_heartbeat
from gridpulse.storage.iceberg import NAMESPACE, get_catalog
from gridpulse.storage.postgres import get_pool

# Window we look back on each nightly archive run. Yesterday and the day
# before — catches late-arriving rows without rewriting weeks of history.
ARCHIVE_LOOKBACK_DAYS = 2

# How long to keep historical snapshots for time travel before expiring.
SNAPSHOT_RETENTION_DAYS = 30


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fetch_partition(pg_table: str, day_start: datetime) -> list[dict]:
    """SELECT * from Postgres for the [day_start, day_start+1) UTC range."""
    day_end = day_start + timedelta(days=1)
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM {pg_table}
            WHERE period_start_utc >= %s
              AND period_start_utc <  %s
            """,
            (day_start, day_end),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def _strip_ingest_metadata(rows: list[dict]) -> list[dict]:
    """Drop ingested_at_utc — Iceberg's snapshot timestamps make it redundant."""
    return [{k: v for k, v in r.items() if k != "ingested_at_utc"} for r in rows]


def _overwrite_day(table: Table, day_start: datetime, rows: list[dict]) -> int:
    """Partition-overwrite the (day_start, day_start+1) range with `rows`.

    Returns rows-written count. Empty `rows` still issues an overwrite — that
    way running this against a date with no Postgres data clears the Iceberg
    partition (rare but correct semantic for "this day had no data").
    """
    day_end = day_start + timedelta(days=1)
    overwrite_filter = And(
        GreaterThanOrEqual("period_start_utc", day_start.isoformat()),
        LessThan("period_start_utc", day_end.isoformat()),
    )

    if rows:
        # PyArrow table — PyIceberg uses Arrow as its in-memory format.
        arrow_tbl = pa.Table.from_pylist(rows)
        table.overwrite(df=arrow_tbl, overwrite_filter=overwrite_filter)
    else:
        # Drop the partition without writing anything new.
        table.delete(delete_filter=overwrite_filter)
    return len(rows)


def _archive_pg_to_iceberg(
    context: AssetExecutionContext,
    pg_table: str,
    iceberg_table_name: str,
) -> dict[str, int]:
    """Archive ARCHIVE_LOOKBACK_DAYS of `pg_table` rows into `iceberg_table_name`.

    Returns {day_iso: row_count} for the materialise metadata.
    """
    table = get_catalog().load_table(f"{NAMESPACE}.{iceberg_table_name}")

    # "Yesterday" relative to wall-clock UTC at materialisation time.
    today_utc = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    rows_per_day: dict[str, int] = {}

    for back in range(1, ARCHIVE_LOOKBACK_DAYS + 1):
        day_start = today_utc - timedelta(days=back)
        rows = _strip_ingest_metadata(_fetch_partition(pg_table, day_start))
        written = _overwrite_day(table, day_start, rows)
        rows_per_day[day_start.date().isoformat()] = written
        context.log.info(
            "%s: wrote %d row(s) for %s",
            iceberg_table_name,
            written,
            day_start.date().isoformat(),
        )
    return rows_per_day


def _md_for(name: str, days: dict[str, int]) -> dict:
    total = sum(days.values())
    return {
        f"{name}_total_rows": MetadataValue.int(total),
        f"{name}_per_day": MetadataValue.json(days),
    }


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@asset(
    description=(
        "Nightly archive: partition-overwrites the last 2 days of all three "
        "raw.* tables into Iceberg. Idempotent — late-arriving rows get "
        "picked up automatically on the next run."
    ),
    group_name="lakehouse",
    compute_kind="pyiceberg",
    deps=[
        "carbon_intensity_national",
        "carbon_intensity_regional",
        "generation_mix",
        "agile_price",
    ],
)
@with_heartbeat("archive_to_iceberg")
def archive_to_iceberg(context: AssetExecutionContext) -> MaterializeResult:
    ci = _archive_pg_to_iceberg(context, "raw.carbon_intensity", "carbon_intensity")
    gm = _archive_pg_to_iceberg(context, "raw.generation_mix", "generation_mix")
    ap = _archive_pg_to_iceberg(context, "raw.agile_price", "agile_price")
    return MaterializeResult(
        metadata={
            **_md_for("carbon_intensity", ci),
            **_md_for("generation_mix", gm),
            **_md_for("agile_price", ap),
            "archive_lookback_days": MetadataValue.int(ARCHIVE_LOOKBACK_DAYS),
        }
    )


@asset(
    description=(
        f"Weekly: expire Iceberg snapshots older than "
        f"{SNAPSHOT_RETENTION_DAYS} days. Drops the de-referenced Parquet "
        "files from R2 — the only Iceberg-side garbage collection we need."
    ),
    group_name="lakehouse",
    compute_kind="pyiceberg",
)
@with_heartbeat("expire_snapshots")
def expire_snapshots(context: AssetExecutionContext) -> MaterializeResult:
    cutoff = datetime.now(UTC) - timedelta(days=SNAPSHOT_RETENTION_DAYS)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    expired_per_table: dict[str, int] = {}
    for table_name in ("carbon_intensity", "generation_mix", "agile_price"):
        table = get_catalog().load_table(f"{NAMESPACE}.{table_name}")
        # PyIceberg's expire_snapshots API takes a millisecond timestamp.
        before_count = len(table.snapshots())
        table.expire_snapshots(expire_older_than=cutoff_ms)
        after_count = len(table.snapshots())
        expired = max(before_count - after_count, 0)
        expired_per_table[table_name] = expired
        context.log.info("%s: expired %d snapshot(s)", table_name, expired)

    return MaterializeResult(
        metadata={
            "cutoff_utc": MetadataValue.text(cutoff.isoformat()),
            "expired_per_table": MetadataValue.json(expired_per_table),
            "retention_days": MetadataValue.int(SNAPSHOT_RETENTION_DAYS),
        }
    )
