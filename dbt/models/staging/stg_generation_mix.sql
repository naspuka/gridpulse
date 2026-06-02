{{ config(materialized='view') }}

-- Wide → long pivot. The raw table is one column per fuel (mirrors the NESO
-- wire shape); analyst-friendly is one row per (period, fuel). This is the
-- textbook source-shaped-staging-vs-mart-shaped pattern from CLAUDE.md.
--
-- 11 fuels total. STORAGE can be negative (charging). We carry the
-- is_renewable flag for downstream "% renewable" donut calculations.

with raw_mix as (
    select * from {{ source('raw', 'generation_mix') }}
)

select period_start_utc, 'gas'      as fuel, gas_mw           as mw, false as is_renewable from raw_mix
union all
select period_start_utc, 'coal'     as fuel, coal_mw          as mw, false as is_renewable from raw_mix
union all
select period_start_utc, 'nuclear'  as fuel, nuclear_mw       as mw, false as is_renewable from raw_mix
union all
select period_start_utc, 'wind'     as fuel, wind_mw          as mw, true  as is_renewable from raw_mix
union all
select period_start_utc, 'wind_emb' as fuel, wind_embedded_mw as mw, true  as is_renewable from raw_mix
union all
select period_start_utc, 'hydro'    as fuel, hydro_mw         as mw, true  as is_renewable from raw_mix
union all
select period_start_utc, 'imports'  as fuel, imports_mw       as mw, false as is_renewable from raw_mix
union all
select period_start_utc, 'biomass'  as fuel, biomass_mw       as mw, true  as is_renewable from raw_mix
union all
select period_start_utc, 'other'    as fuel, other_mw         as mw, false as is_renewable from raw_mix
union all
select period_start_utc, 'solar'    as fuel, solar_mw         as mw, true  as is_renewable from raw_mix
union all
select period_start_utc, 'storage'  as fuel, storage_mw       as mw, false as is_renewable from raw_mix
