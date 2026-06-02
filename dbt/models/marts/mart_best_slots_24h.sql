{{ config(
    materialized='table',
    unique_key=['region_id', 'period_start_utc'],
    indexes=[
        {'columns': ['region_id', 'cheapest_rank'], 'type': 'btree'},
        {'columns': ['region_id', 'greenest_rank'], 'type': 'btree'},
    ]
) }}

-- "When should I run the dishwasher tonight" mart.
-- Ranks the upcoming 24 hours per region by both price (Agile) and
-- carbon intensity (forecast). FastAPI hits this with a single PK lookup:
--   SELECT * FROM marts.mart_best_slots_24h
--   WHERE region_id = ? AND cheapest_rank <= 3
--   ORDER BY period_start_utc;
--
-- "Upcoming 24h" = the next 48 half-hours from now() at materialise time.
-- We refresh this mart after every ingest, so "now" is always within the
-- last 30 minutes of when it last ran.

with hh as (
    select * from {{ ref('mart_half_hourly') }}
    where period_start_utc >= now()
      and period_start_utc <  now() + interval '24 hours'
),
ranked as (
    select
        *,
        row_number() over (
            partition by region_id
            order by price_pence_per_kwh_inc_vat asc nulls last, period_start_utc
        ) as cheapest_rank,
        row_number() over (
            partition by region_id
            order by forecast_gco2_per_kwh asc nulls last, period_start_utc
        ) as greenest_rank
    from hh
)

select
    region_id,
    now() at time zone 'UTC' as computed_at_utc,
    period_start_utc,
    period_end_utc,
    price_pence_per_kwh_inc_vat,
    forecast_gco2_per_kwh,
    cheapest_rank,
    greenest_rank
from ranked
