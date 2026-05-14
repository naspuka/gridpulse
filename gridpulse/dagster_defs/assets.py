"""Asset definitions. Stub for Phase 1B; replaced with real ingestion assets in Phase 2."""

from dagster import asset


@asset(
    description=(
        "Phase 1B stub — proves the Dagster webserver and daemon can load the package "
        "and materialise an asset. Replaced in Phase 2 with the Carbon Intensity ingest."
    ),
)
def stub_asset(context) -> None:
    # Type-annotation on `context` intentionally omitted: Dagster's runtime validator
    # accepts only its own context classes by identity, and `from __future__ import
    # annotations` (which would defer the eval) combined with strict-mypy is more
    # ceremony than a stub deserves. Replaced in Phase 2 with a real typed signature.
    context.log.info("stub asset ran — replace me in Phase 2")
