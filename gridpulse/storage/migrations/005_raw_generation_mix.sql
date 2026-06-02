-- 005 — raw.generation_mix hypertable.
--
-- One row per half-hour, national-only (no region). 11 fuel MW columns
-- (transmission + embedded wind kept separate; storage signed so negative
-- = charging). Total generation and NESO's own carbon intensity are stored
-- as a published total / cross-check field — dbt recomputes percentages
-- and aggregate buckets (renewable/fossil/low-carbon) from MW columns.
--
-- Hypertable: monthly chunks (~1.5k rows/chunk at 48/day). 90-day retention.

CREATE TABLE raw.generation_mix (
    period_start_utc                       TIMESTAMPTZ NOT NULL PRIMARY KEY,
    gas_mw                                 REAL        NOT NULL,
    coal_mw                                REAL        NOT NULL,
    nuclear_mw                             REAL        NOT NULL,
    wind_mw                                REAL        NOT NULL,   -- transmission-connected
    wind_embedded_mw                       REAL        NOT NULL,   -- embedded / behind-the-meter
    hydro_mw                               REAL        NOT NULL,
    imports_mw                             REAL        NOT NULL,
    biomass_mw                             REAL        NOT NULL,
    other_mw                               REAL        NOT NULL,
    solar_mw                               REAL        NOT NULL,
    storage_mw                             REAL        NOT NULL,   -- can be negative (charging)
    total_generation_mw                    REAL        NOT NULL,
    neso_carbon_intensity_gco2_per_kwh     REAL        NOT NULL,
    ingested_at_utc                        TIMESTAMPTZ NOT NULL DEFAULT now()
);

SELECT create_hypertable(
    'raw.generation_mix',
    'period_start_utc',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists       => TRUE
);

SELECT add_retention_policy(
    'raw.generation_mix',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS raw_generation_mix_period_desc_idx
    ON raw.generation_mix (period_start_utc DESC);

COMMENT ON TABLE  raw.generation_mix                                IS 'NESO half-hourly national generation mix; UTC; natural-key upserts.';
COMMENT ON COLUMN raw.generation_mix.wind_embedded_mw               IS 'Embedded (small / behind-the-meter) wind; separate from transmission-connected wind_mw.';
COMMENT ON COLUMN raw.generation_mix.storage_mw                     IS 'Net MW; negative = batteries/pumped storage charging from grid.';
COMMENT ON COLUMN raw.generation_mix.neso_carbon_intensity_gco2_per_kwh IS 'NESO''s own intensity number. Cross-check against the Carbon Intensity API row in raw.carbon_intensity (region_id=0).';
