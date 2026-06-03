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
from .iceberg_assets import archive_to_iceberg, expire_snapshots

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
# Job name MUST differ from the asset name — Dagster synthesises an internal
# op/graph from the job and the asset, and they share a namespace. Using
# the same string here triggered DagsterInvalidDefinitionError on prod.
_dbt_build_job = define_asset_job(
    name="transform",
    selection=AssetSelection.assets(dbt_build),
)
dbt_build_daily_schedule = ScheduleDefinition(
    name="transform_daily",
    job=_dbt_build_job,
    cron_schedule="0 4 * * *",
    execution_timezone="UTC",
    description="Daily dbt build at 04:00 UTC. Manual triggers in the UI as needed.",
)


# Iceberg archival — nightly at 02:00 UTC. Picks up the previous day(s) of
# raw.* rows and partition-overwrites them into Iceberg on R2. Runs before
# dbt at 04:00 so the lakehouse always reflects yesterday's final hot data.
_archive_to_iceberg_job = define_asset_job(
    name="archive",
    selection=AssetSelection.assets(archive_to_iceberg),
)
archive_to_iceberg_daily_schedule = ScheduleDefinition(
    name="archive_daily",
    job=_archive_to_iceberg_job,
    cron_schedule="0 2 * * *",
    execution_timezone="UTC",
    description="Nightly Postgres → Iceberg archive at 02:00 UTC (2-day rolling window).",
)

# Snapshot retention — weekly at 03:00 UTC Sunday. Drops Iceberg snapshots
# older than 30 days, freeing the dereferenced Parquet files on R2.
_expire_snapshots_job = define_asset_job(
    name="snapshot_gc",
    selection=AssetSelection.assets(expire_snapshots),
)
expire_snapshots_weekly_schedule = ScheduleDefinition(
    name="snapshot_gc_weekly",
    job=_expire_snapshots_job,
    cron_schedule="0 3 * * 0",
    execution_timezone="UTC",
    description="Weekly Iceberg snapshot expiry (>30 days), Sunday 03:00 UTC.",
)


defs = Definitions(
    assets=[
        carbon_intensity_national,
        carbon_intensity_regional,
        generation_mix,
        agile_price,
        dbt_build,
        archive_to_iceberg,
        expire_snapshots,
    ],
    jobs=[
        _carbon_intensity_job,
        _generation_mix_job,
        _agile_price_job,
        _dbt_build_job,
        _archive_to_iceberg_job,
        _expire_snapshots_job,
    ],
    schedules=[
        carbon_intensity_30min_schedule,
        generation_mix_30min_schedule,
        agile_price_daily_schedule,
        dbt_build_daily_schedule,
        archive_to_iceberg_daily_schedule,
        expire_snapshots_weekly_schedule,
    ],
)
