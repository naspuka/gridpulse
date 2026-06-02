{{ config(materialized='view') }}

-- Light pass-through over raw.carbon_intensity. Only normalisation is to
-- lower-case the intensity index — the CHECK constraint in 004 already
-- allows the well-known set, but we double-quote here in case NESO's API
-- ever sends "Low" (Pascal) versus "low".

select
    region_id,
    period_start_utc,
    period_end_utc,
    forecast_gco2_per_kwh,
    actual_gco2_per_kwh,
    lower(intensity_index) as intensity_index,
    ingested_at_utc
from {{ source('raw', 'carbon_intensity') }}
