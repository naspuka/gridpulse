"""Carbon Intensity API ingestion.

Two entry points — one per endpoint:

- `fetch_national()` → 1 row, the current half-hour (national, with `actual`).
- `fetch_regional()` → 14 rows, current half-hour per DNO (forecast only).

Both:
- use the shared `http_client` + `http_retry` for transient-error recovery,
- validate every response through pydantic, exploding loudly on schema drift,
- return `CarbonIntensityRow` instances ready for `raw.carbon_intensity` upsert.

The module is pure: no Dagster, no Postgres, no env. Easy to unit-test;
re-usable from the CLI for ad-hoc runs.
"""

from __future__ import annotations

import logging

from gridpulse.contracts.carbon_intensity import (
    CarbonIntensityNationalResponse,
    CarbonIntensityRegionalResponse,
    CarbonIntensityRow,
)
from gridpulse.ingestion.http import (
    http_client,
    http_retry,
    raise_for_transient_status,
)

log = logging.getLogger(__name__)

# Carbon Intensity API base. CC-BY 4.0 — attribution required (handled in
# the FastAPI footer per docs/api-design.md).
BASE_URL = "https://api.carbonintensity.org.uk"


def fetch_national() -> list[CarbonIntensityRow]:
    """Fetch the current half-hour national carbon intensity.

    Hits `/intensity`. Returns one row (region_id=0), with `actual` populated
    if the half-hour has fully elapsed.
    """
    log.info("fetching national carbon intensity")
    with http_client(base_url=BASE_URL) as client:
        for attempt in http_retry():
            with attempt:
                response = client.get("/intensity")
                raise_for_transient_status(response)
                payload = response.json()

    parsed = CarbonIntensityNationalResponse(**payload)
    rows = parsed.to_rows()
    log.info("national fetch produced %d row(s)", len(rows))
    return rows


def fetch_regional() -> list[CarbonIntensityRow]:
    """Fetch the current half-hour regional carbon intensity for all 14 DNOs.

    Hits `/regional`. Returns 14 rows (region_ids 1..14); the 4 rollup
    regions (England, Scotland, Wales, GB) are dropped by the contract.
    """
    log.info("fetching regional carbon intensity")
    with http_client(base_url=BASE_URL) as client:
        for attempt in http_retry():
            with attempt:
                response = client.get("/regional")
                raise_for_transient_status(response)
                payload = response.json()

    parsed = CarbonIntensityRegionalResponse(**payload)
    rows = parsed.to_rows()
    log.info("regional fetch produced %d row(s)", len(rows))
    return rows
