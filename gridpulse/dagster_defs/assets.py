"""Asset definitions.

Phase 2 — Carbon Intensity ingestion:
- `carbon_intensity_national` runs the /intensity ingest (1 row per half-hour).
- `carbon_intensity_regional` runs the /regional ingest (14 rows per half-hour).

Both materialise every 30 minutes via `carbon_intensity_30min_schedule`
(defined in __init__.py). Both are idempotent — re-running the same half-hour
just upserts the same natural key.

Design notes:
- `/regional` returns all 14 DNO regions in a single API call. We do NOT
  partition this asset by region; partitioning would force us to make 14
  identical calls for one shared payload. The CI API has a soft rate
  limit and we should respect it.
- We log the row count and a short freshness summary into Dagster's
  metadata so the UI shows useful per-run stats without us building a
  separate observability layer.
- This module does NOT use `from __future__ import annotations`. Dagster's
  runtime validator does an identity check on the `context` parameter type
  and string-form (deferred) annotations break it.
"""

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from gridpulse.contracts.carbon_intensity import CarbonIntensityRow
from gridpulse.contracts.neso import NesoGenerationMixRow
from gridpulse.contracts.octopus import AgilePriceRow
from gridpulse.ingestion.carbon_intensity import fetch_national, fetch_regional
from gridpulse.ingestion.neso import fetch_recent_generation_mix
from gridpulse.ingestion.octopus import fetch_agile_rates_all_regions
from gridpulse.lib.heartbeat import with_heartbeat
from gridpulse.lib.regions import dno_regions_with_octopus_code
from gridpulse.storage.postgres import (
    upsert_agile_price_rows,
    upsert_carbon_intensity_rows,
    upsert_generation_mix_rows,
)


def _materialize_result(
    rows_written: int,
    rows: list[CarbonIntensityRow]
    | list[NesoGenerationMixRow]
    | list[AgilePriceRow],
    source: str,
) -> MaterializeResult:
    """Common Dagster metadata so each run shows useful stats in the UI."""
    if not rows:
        return MaterializeResult(
            metadata={
                "source": MetadataValue.text(source),
                "rows_written": MetadataValue.int(0),
            }
        )

    latest_period = max(r.period_start_utc for r in rows).isoformat()
    metadata: dict[str, MetadataValue] = {
        "source": MetadataValue.text(source),
        "rows_written": MetadataValue.int(rows_written),
        "latest_period_utc": MetadataValue.text(latest_period),
    }
    # Per-row-type extras — opportunistic; keep light so the UI stays readable.
    first = rows[0]
    if isinstance(first, CarbonIntensityRow):
        forecasts = [r.forecast_gco2_per_kwh for r in rows]  # type: ignore[attr-defined]
        metadata["forecast_min_gco2_per_kwh"] = MetadataValue.int(min(forecasts))
        metadata["forecast_max_gco2_per_kwh"] = MetadataValue.int(max(forecasts))
        metadata["regions"] = MetadataValue.int(len({r.region_id for r in rows}))  # type: ignore[attr-defined]
    elif isinstance(first, AgilePriceRow):
        prices = [r.price_pence_per_kwh_inc_vat for r in rows]  # type: ignore[attr-defined]
        metadata["price_min_pence"] = MetadataValue.float(min(prices))
        metadata["price_max_pence"] = MetadataValue.float(max(prices))
        metadata["regions"] = MetadataValue.int(len({r.region_id for r in rows}))  # type: ignore[attr-defined]
    elif isinstance(first, NesoGenerationMixRow):
        totals = [r.total_generation_mw for r in rows]  # type: ignore[attr-defined]
        metadata["total_generation_min_mw"] = MetadataValue.float(min(totals))
        metadata["total_generation_max_mw"] = MetadataValue.float(max(totals))
    return MaterializeResult(metadata=metadata)


@asset(
    description=(
        "Carbon Intensity API — national rollup (region_id=0), current half-hour. "
        "Both forecast and actual gCO2/kWh; actual fills in once the half-hour realises."
    ),
    group_name="carbon_intensity",
    compute_kind="python",
)
@with_heartbeat("carbon_intensity_national")
def carbon_intensity_national(context: AssetExecutionContext) -> MaterializeResult:
    rows = fetch_national()
    written = upsert_carbon_intensity_rows(rows)
    context.log.info("national: %d row(s) upserted", written)
    return _materialize_result(written, rows, source="carbonintensity.org.uk /intensity")


@asset(
    description=(
        "Carbon Intensity API — 14 DNO regions, current half-hour. Forecast only; "
        "the /regional endpoint does not expose realised values."
    ),
    group_name="carbon_intensity",
    compute_kind="python",
)
@with_heartbeat("carbon_intensity_regional")
def carbon_intensity_regional(context: AssetExecutionContext) -> MaterializeResult:
    rows = fetch_regional()
    written = upsert_carbon_intensity_rows(rows)
    context.log.info(
        "regional: %d row(s) upserted across %d region(s)",
        written,
        len({r.region_id for r in rows}),
    )
    return _materialize_result(written, rows, source="carbonintensity.org.uk /regional")


# ---------------------------------------------------------------------------
# NESO generation mix
# ---------------------------------------------------------------------------


@asset(
    description=(
        "NESO Data Portal — national generation mix per half-hour. Wide schema "
        "(11 fuel MW columns + total + NESO's own carbon intensity). UTC throughout."
    ),
    group_name="generation_mix",
    compute_kind="python",
)
@with_heartbeat("generation_mix")
def generation_mix(context: AssetExecutionContext) -> MaterializeResult:
    # 96 = ~2 days; comfortably overlaps NESO's hourly batches so a missed
    # run still backfills cleanly via the upsert.
    rows = fetch_recent_generation_mix(limit=96)
    written = upsert_generation_mix_rows(rows)
    context.log.info("generation_mix: %d row(s) upserted", written)
    return _materialize_result(written, rows, source="api.neso.energy /historic-generation-mix")


# ---------------------------------------------------------------------------
# Octopus Agile prices
# ---------------------------------------------------------------------------


@asset(
    description=(
        "Octopus Agile half-hourly unit rates for all 14 DNO regions. "
        "Daily schedule (Octopus publishes the next day's prices ~16:00 UK)."
    ),
    group_name="agile_price",
    compute_kind="python",
)
@with_heartbeat("agile_price")
def agile_price(context: AssetExecutionContext) -> MaterializeResult:
    regions = dno_regions_with_octopus_code()
    context.log.info("agile_price: looping %d region(s)", len(regions))
    # 96 rows / region = ~2 days, comfortably wider than the publish cadence.
    rows = fetch_agile_rates_all_regions(regions, page_size=96)
    written = upsert_agile_price_rows(rows)
    context.log.info(
        "agile_price: %d row(s) upserted across %d region(s)",
        written,
        len({r.region_id for r in rows}),
    )
    return _materialize_result(written, rows, source="api.octopus.energy AGILE-24-10-01")
