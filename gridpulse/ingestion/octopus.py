"""Octopus Energy ingestion — Agile unit rates.

Two entry points:
- `fetch_agile_rates_for_region(region_id, octopus_code)` → all rows for one DNO.
- `fetch_agile_rates_all_regions(regions)` → loops the 14 DNOs in one call,
  used by the Dagster asset.

Both yield `AgilePriceRow` records tagged with the right `region_id`. The
endpoint returns the latest ~96 rows by default; we don't paginate yet
(we run daily after Octopus publishes the next day's prices, so one page is
enough to keep the table fresh).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from gridpulse.contracts.octopus import AgilePriceRow, AgileRatesResponse
from gridpulse.ingestion.http import (
    http_client,
    http_retry,
    raise_for_transient_status,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.octopus.energy"
# Current Agile product (replaced AGILE-FLEX-22-11-25 in late 2024). Keep
# this constant — Octopus rotates products every few years; when they do,
# update this and the historical price re-loads from the new product code.
AGILE_PRODUCT = "AGILE-24-10-01"


def _tariff_code(octopus_code: str) -> str:
    """Build the tariff code for one DNO letter, e.g. 'C' → 'E-1R-AGILE-24-10-01-C'."""
    return f"E-1R-{AGILE_PRODUCT}-{octopus_code}"


def fetch_agile_rates_for_region(
    *,
    region_id: int,
    octopus_code: str,
    page_size: int = 96,
) -> list[AgilePriceRow]:
    """Fetch the latest `page_size` half-hours of Agile prices for one region."""
    tariff = _tariff_code(octopus_code)
    path = f"/v1/products/{AGILE_PRODUCT}/electricity-tariffs/{tariff}/standard-unit-rates/"
    log.info("fetching Agile rates: region_id=%d octopus_code=%s", region_id, octopus_code)
    with http_client(base_url=BASE_URL) as client:
        for attempt in http_retry():
            with attempt:
                response = client.get(path, params={"page_size": str(page_size)})
                raise_for_transient_status(response)
                payload = response.json()
    parsed = AgileRatesResponse(**payload)
    rows = parsed.to_rows(region_id=region_id)
    log.info("Agile fetch produced %d row(s) for region_id=%d", len(rows), region_id)
    return rows


def fetch_agile_rates_all_regions(
    regions: Iterable[tuple[int, str]],
    *,
    page_size: int = 96,
) -> list[AgilePriceRow]:
    """Loop a sequence of (region_id, octopus_code) pairs. Used by the Dagster asset.

    Errors on any one region propagate — partial success is masked by the
    Dagster asset's retry behaviour, and tenacity has already handled the
    transient flakes inside each call.
    """
    out: list[AgilePriceRow] = []
    for region_id, octopus_code in regions:
        out.extend(
            fetch_agile_rates_for_region(
                region_id=region_id,
                octopus_code=octopus_code,
                page_size=page_size,
            )
        )
    log.info("Agile fetch (all-regions) produced %d row(s)", len(out))
    return out
