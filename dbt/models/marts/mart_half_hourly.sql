{{ config(
    materialized='table',
    unique_key=['region_id', 'period_start_utc'],
    indexes=[
        {'columns': ['period_start_utc'], 'type': 'btree'},
    ]
) }}

-- The "everything joined on the half-hour grain" table for a given region.
-- One row per (region_id, period_start_utc).
--
-- Generation mix is national-only and lives in its own mart
-- (mart_generation_mix_long). Joining it here would force every regional
-- row to repeat the same fuel breakdown — wasteful.

with carbon as (
    select * from {{ ref('stg_carbon_intensity') }}
),
price as (
    select * from {{ ref('stg_agile_price') }}
)

select
    c.region_id,
    c.period_start_utc,
    c.period_end_utc,
    c.forecast_gco2_per_kwh,
    c.actual_gco2_per_kwh,
    c.intensity_index,
    p.price_pence_per_kwh_inc_vat,
    p.price_pence_per_kwh_exc_vat
from carbon c
left join price p
    on  c.region_id        = p.region_id
    and c.period_start_utc = p.period_start_utc
