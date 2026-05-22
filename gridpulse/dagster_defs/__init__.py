"""Dagster `Definitions` — assets, schedules, sensors. Loaded by webserver and daemon."""

from dagster import AssetSelection, Definitions, ScheduleDefinition, define_asset_job

from .assets import carbon_intensity_national, carbon_intensity_regional

# Both Carbon Intensity assets in one job — they hit the same source API and
# share the same 30-min cadence, so it's tidier to run them together. Dagster
# still tracks per-asset materialisations in the UI.
_carbon_intensity_job = define_asset_job(
    name="carbon_intensity_ingest",
    selection=AssetSelection.assets(carbon_intensity_national, carbon_intensity_regional),
)

# Cron at :02 and :32 of every hour — five minutes into each half-hour, which
# gives the CI API time to publish the previous half-hour's `actual` value
# before we re-fetch it.
carbon_intensity_30min_schedule = ScheduleDefinition(
    name="carbon_intensity_30min",
    job=_carbon_intensity_job,
    cron_schedule="2,32 * * * *",
    execution_timezone="UTC",
    description="Pulls /intensity + /regional every 30 minutes, 2 min past each half-hour.",
)

defs = Definitions(
    assets=[carbon_intensity_national, carbon_intensity_regional],
    jobs=[_carbon_intensity_job],
    schedules=[carbon_intensity_30min_schedule],
)
