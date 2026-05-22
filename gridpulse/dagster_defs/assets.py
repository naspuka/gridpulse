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
from gridpulse.ingestion.carbon_intensity import fetch_national, fetch_regional
from gridpulse.storage.postgres import upsert_carbon_intensity_rows


def _materialize_result(
    rows_written: int, rows: list[CarbonIntensityRow], source: str
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
    forecasts = [r.forecast_gco2_per_kwh for r in rows]
    return MaterializeResult(
        metadata={
            "source": MetadataValue.text(source),
            "rows_written": MetadataValue.int(rows_written),
            "latest_period_utc": MetadataValue.text(latest_period),
            "forecast_min_gco2_per_kwh": MetadataValue.int(min(forecasts)),
            "forecast_max_gco2_per_kwh": MetadataValue.int(max(forecasts)),
            "regions": MetadataValue.int(len({r.region_id for r in rows})),
        }
    )


@asset(
    description=(
        "Carbon Intensity API — national rollup (region_id=0), current half-hour. "
        "Both forecast and actual gCO2/kWh; actual fills in once the half-hour realises."
    ),
    group_name="carbon_intensity",
    compute_kind="python",
)
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
def carbon_intensity_regional(context: AssetExecutionContext) -> MaterializeResult:
    rows = fetch_regional()
    written = upsert_carbon_intensity_rows(rows)
    context.log.info(
        "regional: %d row(s) upserted across %d region(s)",
        written,
        len({r.region_id for r in rows}),
    )
    return _materialize_result(written, rows, source="carbonintensity.org.uk /regional")
