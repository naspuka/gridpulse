# Database design (Postgres + TimescaleDB)

Hot store. Postgres 16 + TimescaleDB extension. Last 90 days. UTC server timezone. UTF-8.

## The mental model — three zones

| Zone | Schema | Owner | Materialisation |
|---|---|---|---|
| Raw / landing | `raw` | Dagster ingestion | Tables (hypertables) |
| Staging | `staging` | dbt | Views (cheap, always fresh) |
| Marts | `marts` | dbt | Tables (refreshed after ingestion) |
| Reference | `ref` | hand-seeded SQL | Small dimension tables |
| Iceberg catalog | `iceberg_catalog` | PyIceberg | Internal — see [lakehouse-design.md](./lakehouse-design.md) |

The dbt rule of thumb: **staging never joins, marts never rename.** Each layer has one job.

The raw zone is your **audit trail**. If a downstream model has a bug, you re-run dbt — you don't re-fetch the API. That separation is what makes idempotency real.

## One-time setup

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS iceberg_catalog;

ALTER DATABASE gridpulse SET timezone TO 'UTC';
```

## Reference tables (`ref`)

### `ref.dno_region`

Canonical DNO table. Every source's region code maps into this. Includes a sentinel `region_id = 0` row for `'NATIONAL'` so all fact tables can FK uniformly.

```sql
CREATE TABLE ref.dno_region (
    region_id           SMALLINT     PRIMARY KEY,        -- internal id, 0=NATIONAL, 1..14 DNOs
    canonical_code      VARCHAR(8)   NOT NULL UNIQUE,    -- e.g. 'NATIONAL', 'LON', 'SWA'
    slug                VARCHAR(32)  NOT NULL UNIQUE,    -- e.g. 'national', 'london'
    name                TEXT         NOT NULL,
    octopus_code        CHAR(1)      UNIQUE,             -- 'C', 'K', ... (NULL for NATIONAL)
    carbon_intensity_id SMALLINT     UNIQUE,             -- the int id CI uses
    notes               TEXT
);
```

Seed via `gridpulse/storage/migrations/003_seed_dno_region.sql` — version-controlled, reproducible.

**Why `region_id = 0` for NATIONAL** rather than nullable FKs: uniform joins, no `IS NULL` branches in queries. Cheap sentinel; obvious sentinel.

## Raw layer (`raw`) — written by Dagster

### Conventions

- `TIMESTAMPTZ` everywhere. Never `TIMESTAMP`. Postgres stores tz-aware in UTC internally.
- `REAL` (4 bytes) for floats — energy data has ~3 sig figs; double precision is wasted.
- `SMALLINT` for `forecast_gco2_per_kwh` (range 0–600).
- PK is the **natural key** — what we upsert on.
- Hypertable on `period_start_utc`; monthly chunk interval; 90-day retention policy.
- `ingested_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()` — populated by the DB.

### `raw.carbon_intensity`

```sql
CREATE TABLE raw.carbon_intensity (
    region_id              SMALLINT      NOT NULL REFERENCES ref.dno_region(region_id),
    period_start_utc       TIMESTAMPTZ   NOT NULL,
    period_end_utc         TIMESTAMPTZ   NOT NULL,
    forecast_gco2_per_kwh  SMALLINT      NOT NULL,
    actual_gco2_per_kwh    SMALLINT,                  -- null until realised
    intensity_index        TEXT          NOT NULL,
    ingested_at_utc        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (region_id, period_start_utc)
);

SELECT create_hypertable('raw.carbon_intensity', 'period_start_utc',
                         chunk_time_interval => INTERVAL '1 month');
SELECT add_retention_policy('raw.carbon_intensity', INTERVAL '90 days');

CREATE INDEX ON raw.carbon_intensity (period_start_utc DESC);
```

### `raw.generation_mix`

National only — no region FK. Wide format (one column per fuel) mirrors the source.

```sql
CREATE TABLE raw.generation_mix (
    period_start_utc   TIMESTAMPTZ NOT NULL PRIMARY KEY,
    gas_mw             REAL,
    coal_mw            REAL,
    nuclear_mw         REAL,
    wind_mw            REAL,
    solar_mw           REAL,
    hydro_mw           REAL,
    biomass_mw         REAL,
    imports_mw         REAL,
    storage_mw         REAL,
    other_mw           REAL,
    ingested_at_utc    TIMESTAMPTZ NOT NULL DEFAULT now()
);

SELECT create_hypertable('raw.generation_mix', 'period_start_utc',
                         chunk_time_interval => INTERVAL '1 month');
SELECT add_retention_policy('raw.generation_mix', INTERVAL '90 days');
```

### `raw.agile_price`

```sql
CREATE TABLE raw.agile_price (
    region_id                       SMALLINT    NOT NULL REFERENCES ref.dno_region(region_id),
    period_start_utc                TIMESTAMPTZ NOT NULL,
    period_end_utc                  TIMESTAMPTZ NOT NULL,
    price_pence_per_kwh_inc_vat     REAL        NOT NULL,
    price_pence_per_kwh_exc_vat     REAL        NOT NULL,
    ingested_at_utc                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (region_id, period_start_utc)
);

SELECT create_hypertable('raw.agile_price', 'period_start_utc',
                         chunk_time_interval => INTERVAL '1 month');
SELECT add_retention_policy('raw.agile_price', INTERVAL '90 days');
```

### Why hypertables / monthly chunks

Timescale chunks the table by time. Queries like "last 24h" only scan the most recent chunk. Retention policy auto-drops old chunks (chunk drop, not row delete — fast).

Default chunk interval is 7 days; that's too granular for our row counts. Monthly = ~3 live chunks at 90-day retention. Easy to reason about.

## Idempotent upsert (the heart of it)

Every Dagster ingestion asset writes via this shape:

```sql
INSERT INTO raw.carbon_intensity (region_id, period_start_utc, period_end_utc,
                                  forecast_gco2_per_kwh, actual_gco2_per_kwh,
                                  intensity_index)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (region_id, period_start_utc) DO UPDATE SET
    period_end_utc        = EXCLUDED.period_end_utc,
    forecast_gco2_per_kwh = EXCLUDED.forecast_gco2_per_kwh,
    actual_gco2_per_kwh   = EXCLUDED.actual_gco2_per_kwh,
    intensity_index       = EXCLUDED.intensity_index,
    ingested_at_utc       = now();
```

Why this matters:

- First ingest sets `actual = NULL` (forecast only). Later ingest brings the realised actual — same row, updated, no duplicate.
- Re-running yesterday's asset: same result every time. **This is what idempotency means in practice** — and it's exactly the answer interviewers probe for.

## Staging layer (`staging`, dbt-owned)

dbt **views** by default — cheap, always fresh. Renames and light typing only.

```sql
CREATE VIEW staging.stg_carbon_intensity AS
SELECT
    region_id,
    period_start_utc,
    period_end_utc,
    forecast_gco2_per_kwh,
    actual_gco2_per_kwh,
    LOWER(intensity_index) AS intensity_index
FROM raw.carbon_intensity;
```

`stg_generation_mix` does the wide→long pivot — the single non-trivial transformation in staging:

```sql
SELECT period_start_utc, 'gas'     AS fuel, gas_mw     AS mw FROM raw.generation_mix
UNION ALL
SELECT period_start_utc, 'coal'    AS fuel, coal_mw    AS mw FROM raw.generation_mix
UNION ALL
-- ... etc
```

In practice this collapses to `dbt_utils.unpivot`, but the longhand version makes the intent obvious.

## Mart layer (`marts`, dbt-owned)

Materialised as **tables**, refreshed by dbt after each ingestion run. Sub-millisecond reads matter for the UI.

### `marts.mart_half_hourly`

The "everything joined on the half-hour grain" table. One row per `(region_id, period_start_utc)`.

```sql
CREATE TABLE marts.mart_half_hourly (
    region_id                       SMALLINT    NOT NULL,
    period_start_utc                TIMESTAMPTZ NOT NULL,
    period_end_utc                  TIMESTAMPTZ NOT NULL,
    forecast_gco2_per_kwh           SMALLINT,
    actual_gco2_per_kwh             SMALLINT,
    intensity_index                 TEXT,
    price_pence_per_kwh_inc_vat     REAL,
    is_post_2026_levy_reform        BOOLEAN     NOT NULL,   -- computed in dbt
    PRIMARY KEY (region_id, period_start_utc)
);

CREATE INDEX ON marts.mart_half_hourly (period_start_utc DESC);
```

Generation mix is national only and not joined here — would force every regional row to repeat the same fuel breakdown. Lives in its own mart.

### `marts.mart_generation_mix_long`

```sql
CREATE TABLE marts.mart_generation_mix_long (
    period_start_utc   TIMESTAMPTZ NOT NULL,
    fuel               TEXT        NOT NULL,
    mw                 REAL        NOT NULL,
    is_renewable       BOOLEAN     NOT NULL,    -- enrichment for "% renewable" donut
    PRIMARY KEY (period_start_utc, fuel)
);
```

### `marts.mart_best_slots_24h`

The "when should I run my dishwasher tonight" mart. Tiny table; recomputed every half-hour.

```sql
CREATE TABLE marts.mart_best_slots_24h (
    region_id                       SMALLINT    NOT NULL,
    computed_at_utc                 TIMESTAMPTZ NOT NULL,
    period_start_utc                TIMESTAMPTZ NOT NULL,
    period_end_utc                  TIMESTAMPTZ NOT NULL,
    price_pence_per_kwh_inc_vat     REAL,
    forecast_gco2_per_kwh           SMALLINT,
    cheapest_rank                   SMALLINT,    -- 1 = cheapest in next 24h
    greenest_rank                   SMALLINT,    -- 1 = lowest carbon in next 24h
    PRIMARY KEY (region_id, period_start_utc)
);
```

Landing page query becomes trivial: `SELECT * FROM marts.mart_best_slots_24h WHERE region_id = ? AND cheapest_rank <= 3 ORDER BY period_start_utc`. Window functions ran in dbt at materialisation time — never on the API path.

## Indexes

Currently:

- PK on every fact table (covers point-lookups)
- Secondary `(period_start_utc DESC)` on facts and marts (covers "last N hours")

Not adding yet:

- Index on `region_id` alone — leading PK column, already covered.
- Index on `intensity_index` — low cardinality, never the lone WHERE.

Premature indexing is real. We add more once we have actual slow queries.

## Continuous aggregates (deferred)

Timescale's killer feature: precomputed hourly/daily rollups that auto-refresh. Not in V1 — marts already cover the dashboard queries. Stretch goal for Phase 6 if the API gets slow under load.

## Migrations

Plain SQL files, applied in numeric order by a tiny Python script. **Not Alembic.**

```
gridpulse/storage/migrations/
├── 001_extensions_and_schemas.sql
├── 002_ref_dno_region.sql
├── 003_seed_dno_region.sql
├── 004_raw_carbon_intensity.sql
├── 005_raw_generation_mix.sql
├── 006_raw_agile_price.sql
└── README.md
```

Why plain SQL: we're not using SQLAlchemy as the ORM, so Alembic's autogen is moot. Plain SQL is honest about what's happening, and TimescaleDB's `create_hypertable()` plays nicer with hand-written DDL than ORM autogen. Learning project: you should see every line.

The applier script (`gridpulse/storage/migrate.py`) maintains a `_migrations` table of applied versions. Idempotent — running twice does nothing the second time.

## Sizing sanity check

| Table | Rows / day | 90d total | ~bytes/row | 90d size |
|---|---|---|---|---|
| `raw.carbon_intensity` | 48 × 15 = 720 | ~65k | ~50 | ~3 MB |
| `raw.generation_mix` | 48 | ~4.3k | ~70 | ~0.3 MB |
| `raw.agile_price` | 48 × 14 = 672 | ~60k | ~50 | ~3 MB |
| Marts (similar) | similar | ~130k | ~70 | ~9 MB |

**Hot-store footprint: well under 50 MB.** A CX32 (8 GB RAM) holds this entirely in memory. Postgres tuning trivial: defaults plus `shared_buffers = 1GB`.
