"""NESO Data Portal ingestion — generation mix.

One entry point:
- `fetch_recent_generation_mix(limit: int = 96)` → up to `limit` rows of the
  most recent half-hours (default 96 ≈ 2 days, comfortable buffer against the
  hourly NESO refresh cadence).

The CKAN resource id is hard-coded — NESO's "historic-generation-mix" dataset.
If they ever rotate it, an HTTP 404/500 here surfaces the breakage; we'll
update the constant in one place.
"""

from __future__ import annotations

import logging

from gridpulse.contracts.neso import (
    NesoGenerationMixResponse,
    NesoGenerationMixRow,
)
from gridpulse.ingestion.http import (
    http_client,
    http_retry,
    raise_for_transient_status,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.neso.energy"
# `historic-generation-mix` dataset — the CSV/parquet resource that NESO
# refreshes hourly with the latest half-hourly readings.
GENERATION_MIX_RESOURCE_ID = "f93d1835-75bc-43e5-84ad-12472b180a98"


def fetch_recent_generation_mix(limit: int = 96) -> list[NesoGenerationMixRow]:
    """Fetch the most recent `limit` half-hours of national generation mix.

    Defaults to 96 (≈ 2 days). NESO's update cadence is hourly-ish, so any
    schedule that catches a fresh window of ~50 hours is fine. The upsert
    in raw.generation_mix collapses re-fetched rows by natural key.
    """
    params = {
        "resource_id": GENERATION_MIX_RESOURCE_ID,
        "limit": str(limit),
        "sort": "DATETIME desc",
    }
    log.info("fetching NESO generation mix (limit=%d)", limit)
    with http_client(base_url=BASE_URL) as client:
        for attempt in http_retry():
            with attempt:
                response = client.get("/api/3/action/datastore_search", params=params)
                raise_for_transient_status(response)
                payload = response.json()

    parsed = NesoGenerationMixResponse(**payload)
    rows = parsed.to_rows()
    log.info("NESO fetch produced %d row(s)", len(rows))
    return rows
