-- 004 — raw.carbon_intensity hypertable.
--
-- One row per (region, half-hour). region_id = 0 for the national rollup
-- (from /intensity, with `actual` populated as half-hours realise);
-- region_id 1..14 for DNO regions (from /regional, `actual_gco2_per_kwh`
-- always NULL because the API doesn't expose realised regional values).
--
-- Hypertable: chunked monthly. At ~720 rows/day (15 regions × 48 half-hours)
-- that's ~22k rows/chunk — comfortably cache-resident. 90-day retention drops
-- chunks older than that.

CREATE TABLE raw.carbon_intensity (
    region_id              SMALLINT      NOT NULL REFERENCES ref.dno_region(region_id),
    period_start_utc       TIMESTAMPTZ   NOT NULL,
    period_end_utc         TIMESTAMPTZ   NOT NULL,
    forecast_gco2_per_kwh  SMALLINT      NOT NULL,
    -- Always NULL for regional rows; carries the realised value for national
    -- half-hours that have fully elapsed.
    actual_gco2_per_kwh    SMALLINT,
    intensity_index        TEXT          NOT NULL,
    ingested_at_utc        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (region_id, period_start_utc),
    CHECK (period_end_utc > period_start_utc),
    CHECK (intensity_index IN ('very low', 'low', 'moderate', 'high', 'very high'))
);

-- Hypertable on period_start_utc. Monthly chunks fit our row volume well.
SELECT create_hypertable(
    'raw.carbon_intensity',
    'period_start_utc',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists       => TRUE
);

-- Auto-drop chunks older than 90 days (the hot-store window).
SELECT add_retention_policy(
    'raw.carbon_intensity',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

-- "Last N hours / latest period" queries hit this index.
CREATE INDEX IF NOT EXISTS raw_carbon_intensity_period_desc_idx
    ON raw.carbon_intensity (period_start_utc DESC);

COMMENT ON TABLE  raw.carbon_intensity                       IS 'Half-hourly carbon intensity from the CI API, per region. Idempotent natural-key upserts.';
COMMENT ON COLUMN raw.carbon_intensity.forecast_gco2_per_kwh IS 'gCO2/kWh forecast at ingest time. Always present.';
COMMENT ON COLUMN raw.carbon_intensity.actual_gco2_per_kwh   IS 'gCO2/kWh realised. NULL until the half-hour ends (national) or always (regional).';
COMMENT ON COLUMN raw.carbon_intensity.ingested_at_utc       IS 'Server clock at insert/upsert time. Source-of-truth for "freshness" SLOs.';
