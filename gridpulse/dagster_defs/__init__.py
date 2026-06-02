"""Dagster `Definitions` — assets, schedules, sensors. Loaded by webserver and daemon."""

from dagster import AssetSelection, Definitions, ScheduleDefinition, define_asset_job

from gridpulse.lib.observability import init_sentry

from .assets import (
    agile_price,
    carbon_intensity_national,
    carbon_intensity_regional,
    generation_mix,
)
from .dbt_assets import dbt_build

# Init Sentry on Dagster module import. The webserver, daemon, and each
# spawned step subprocess all import this module, so each gets its own
# SDK instance. No-op if SENTRY_DSN isn't set.
init_sentry(component="dagster")


# Carbon Intensity — pair the two assets, run together every 30 min.
_carbon_intensity_job = define_asset_job(
    name="carbon_intensity_ingest",
    selection=AssetSelection.assets(carbon_intensity_national, carbon_intensity_regional),
)
carbon_intensity_30min_schedule = ScheduleDefinition(
    name="carbon_intensity_30min",
    job=_carbon_intensity_job,
    cron_schedule="2,32 * * * *",
    execution_timezone="UTC",
    description="Pulls /intensity + /regional every 30 minutes, 2 min past each half-hour.",
)

# NESO generation mix — every 30 min. NESO actually refreshes hourly-ish;
# 30 min keeps us within one refresh window without hammering them.
_generation_mix_job = define_asset_job(
    name="generation_mix_ingest",
    selection=AssetSelection.assets(generation_mix),
)
generation_mix_30min_schedule = ScheduleDefinition(
    name="generation_mix_30min",
    job=_generation_mix_job,
    cron_schedule="5,35 * * * *",
    execution_timezone="UTC",
    description="Pulls NESO generation mix every 30 minutes.",
)

# Octopus Agile — Octopus publishes the next day's prices around 16:00 UK time.
# Run once daily at 16:30 UK (= 15:30 UTC in summer, 16:30 in winter). We pick
# 16:30 UTC unconditionally — close enough either way; the upsert is idempotent.
_agile_price_job = define_asset_job(
    name="agile_price_ingest",
    selection=AssetSelection.assets(agile_price),
)
agile_price_daily_schedule = ScheduleDefinition(
    name="agile_price_daily",
    job=_agile_price_job,
    cron_schedule="30 16 * * *",
    execution_timezone="UTC",
    description="Pulls Octopus Agile rates for all 14 DNOs once a day after publication.",
)


# dbt build — pulled by an auto-materialise sensor downstream of every ingest.
# Run it explicitly via the UI or on a slow cadence; for now, daily at 04:00 UTC
# is enough (no marts in V1 are real-time-critical — FastAPI reads tables that
# dbt refreshes). Phase 5 may tighten this when we have user-facing latency
# requirements.
_dbt_build_job = define_asset_job(
    name="dbt_build",
    selection=AssetSelection.assets(dbt_build),
)
dbt_build_daily_schedule = ScheduleDefinition(
    name="dbt_build_daily",
    job=_dbt_build_job,
    cron_schedule="0 4 * * *",
    execution_timezone="UTC",
    description="Daily dbt build at 04:00 UTC. Manual triggers in the UI as needed.",
)


defs = Definitions(
    assets=[
        carbon_intensity_national,
        carbon_intensity_regional,
        generation_mix,
        agile_price,
        dbt_build,
    ],
    jobs=[
        _carbon_intensity_job,
        _generation_mix_job,
        _agile_price_job,
        _dbt_build_job,
    ],
    schedules=[
        carbon_intensity_30min_schedule,
        generation_mix_30min_schedule,
        agile_price_daily_schedule,
        dbt_build_daily_schedule,
    ],
)
