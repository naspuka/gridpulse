"""One-off backfill: Carbon Intensity 2018→ direct into Iceberg.

Bypasses Postgres entirely — the lakehouse retains full history while
Postgres only keeps 90 days. Funnelling 2M+ rows through Postgres just to
delete most of them is wasteful and risks blowing the hypertable cache.

Strategy:
- Loop months from --from (default 2018-05-10, CI API epoch) to today.
- Hit `/intensity/{from}/{to}` paginated by 14 days (API limit).
- For each chunk: pydantic-validate, then APPEND to Iceberg.
- Idempotency NOT guaranteed for the regional rollups by the chunk-append
  pattern; that's why this is a one-off script, not an asset.

Run inside the dagster container so all env vars are set:

    docker compose exec dagster-daemon python -m scripts.backfill_carbon_intensity \\
        --from 2018-05-10 --to 2026-06-01

Restart from a partial state by passing a later `--from`; existing data is
not de-duplicated (Iceberg has no PK), so set `--from` to the last fully-
backfilled month boundary if you re-run.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime, timedelta

import pyarrow as pa

from gridpulse.contracts.carbon_intensity import CarbonIntensityNationalResponse
from gridpulse.ingestion.carbon_intensity import BASE_URL
from gridpulse.ingestion.http import http_client, http_retry, raise_for_transient_status
from gridpulse.storage.iceberg import NAMESPACE, get_catalog

log = logging.getLogger(__name__)

# CI API epoch — they started publishing 2018-05-10.
DEFAULT_START = date(2018, 5, 10)
# 14 days is the CI API's stated max range per /intensity/{from}/{to} request.
CHUNK_DAYS = 14


def _fetch_range(start: datetime, end: datetime) -> list[dict]:
    """Hit /intensity/{from}/{to} for one [start, end) window; return Arrow-ready dicts."""
    from_iso = start.strftime("%Y-%m-%dT%H:%MZ")
    to_iso = end.strftime("%Y-%m-%dT%H:%MZ")
    with http_client(base_url=BASE_URL) as client:
        for attempt in http_retry():
            with attempt:
                resp = client.get(f"/intensity/{from_iso}/{to_iso}")
                raise_for_transient_status(resp)
                payload = resp.json()
    parsed = CarbonIntensityNationalResponse(**payload)
    return [
        {
            "region_id": r.region_id,
            "period_start_utc": r.period_start_utc,
            "period_end_utc": r.period_end_utc,
            "forecast_gco2_per_kwh": r.forecast_gco2_per_kwh,
            "actual_gco2_per_kwh": r.actual_gco2_per_kwh,
            "intensity_index": r.intensity_index,
        }
        for r in parsed.to_rows()
    ]


def backfill(start_date: date, end_date: date) -> int:
    table = get_catalog().load_table(f"{NAMESPACE}.carbon_intensity")
    total = 0
    cursor = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(end_date, datetime.min.time(), tzinfo=UTC)

    while cursor < end:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        rows = _fetch_range(cursor, chunk_end)
        if rows:
            arrow_tbl = pa.Table.from_pylist(rows)
            table.append(arrow_tbl)
            total += len(rows)
        log.info(
            "%s → %s: %d row(s) appended (cumulative %d)",
            cursor.date(),
            chunk_end.date(),
            len(rows),
            total,
        )
        cursor = chunk_end
    return total


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument(
        "--to", dest="end", type=date.fromisoformat, default=datetime.now(UTC).date()
    )
    args = parser.parse_args()

    log.info("backfilling Carbon Intensity national: %s → %s", args.start, args.end)
    try:
        total = backfill(args.start, args.end)
    except Exception as exc:  # noqa: BLE001
        log.error("backfill failed: %s", exc)
        return 1
    log.info("done — %d row(s) appended", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
