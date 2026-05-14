"""Asset definitions. Stub for Phase 1B; replaced with real ingestion assets in Phase 2."""

from __future__ import annotations

from dagster import AssetExecutionContext, asset


@asset(
    description=(
        "Phase 1B stub — proves the Dagster webserver and daemon can load the package "
        "and materialise an asset. Replaced in Phase 2 with the Carbon Intensity ingest."
    ),
)
def stub_asset(context: AssetExecutionContext) -> None:
    context.log.info("stub asset ran — replace me in Phase 2")
