-- 006 — raw.agile_price hypertable.
--
-- One row per (region, half-hour). 14 DNO regions only (no NATIONAL — Agile
-- prices are per-DNO; there's no national rollup at this layer). Both VAT
-- variants stored explicitly so we don't have to recompute (VAT rate has
-- changed in the past). Pence per kWh, REAL precision is fine.
--
-- Hypertable: monthly chunks (~20k rows/chunk at 14 × 48/day). 90-day retention.

CREATE TABLE raw.agile_price (
    region_id                       SMALLINT      NOT NULL REFERENCES ref.dno_region(region_id),
    period_start_utc                TIMESTAMPTZ   NOT NULL,
    period_end_utc                  TIMESTAMPTZ   NOT NULL,
    price_pence_per_kwh_inc_vat     REAL          NOT NULL,
    price_pence_per_kwh_exc_vat     REAL          NOT NULL,
    ingested_at_utc                 TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (region_id, period_start_utc),
    CHECK (period_end_utc > period_start_utc),
    -- region_id 0 is the NATIONAL sentinel, which doesn't make sense here.
    CHECK (region_id BETWEEN 1 AND 14)
);

SELECT create_hypertable(
    'raw.agile_price',
    'period_start_utc',
    chunk_time_interval => INTERVAL '1 month',
    if_not_exists       => TRUE
);

SELECT add_retention_policy(
    'raw.agile_price',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS raw_agile_price_period_desc_idx
    ON raw.agile_price (period_start_utc DESC);

COMMENT ON TABLE  raw.agile_price                            IS 'Octopus Agile half-hourly unit rates per DNO. Source: AGILE-24-10-01 product (rotates every few years).';
COMMENT ON COLUMN raw.agile_price.price_pence_per_kwh_inc_vat IS 'Customer-facing price including 5% domestic VAT.';
COMMENT ON COLUMN raw.agile_price.price_pence_per_kwh_exc_vat IS 'Wholesale-aligned price excluding VAT.';
