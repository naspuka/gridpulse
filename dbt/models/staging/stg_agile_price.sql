{{ config(materialized='view') }}

-- Pass-through over raw.agile_price. No renames needed.

select
    region_id,
    period_start_utc,
    period_end_utc,
    price_pence_per_kwh_inc_vat,
    price_pence_per_kwh_exc_vat,
    ingested_at_utc
from {{ source('raw', 'agile_price') }}
