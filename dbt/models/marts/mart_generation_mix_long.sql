{{ config(
    materialized='table',
    unique_key=['period_start_utc', 'fuel'],
    indexes=[
        {'columns': ['period_start_utc'], 'type': 'btree'},
    ]
) }}

-- Long-format generation mix for the donut + per-fuel charts.
-- Already pivoted in stg_generation_mix; this mart is essentially the
-- staging view materialised plus a derived `share_of_generation_pct`
-- column so the FastAPI layer doesn't have to compute it.

with mix as (
    select * from {{ ref('stg_generation_mix') }}
),
totals as (
    -- Total includes storage so the percentages add up to 100. When
    -- storage_mw is negative (charging), it reduces the denominator —
    -- which is the right semantic for "what share of grid demand is X".
    select
        period_start_utc,
        sum(mw) as total_mw
    from mix
    group by 1
)

select
    m.period_start_utc,
    m.fuel,
    m.mw,
    m.is_renewable,
    case
        when t.total_mw > 0 then 100.0 * m.mw / t.total_mw
        else null
    end as share_of_generation_pct
from mix m
left join totals t using (period_start_utc)
