-- 002 — Canonical DNO region dimension table.
--
-- One row per UK DNO (14) plus a sentinel "NATIONAL" row (region_id = 0) so
-- every fact table can foreign-key on region_id uniformly. Each row holds
-- the source-specific codes used by the three V1 APIs:
--   * carbon_intensity_id — integer id from the CI API /regional response
--   * octopus_code        — single-letter DNO code from Octopus Agile URLs
--
-- Canonical short codes (canonical_code) are our internal identifier; we
-- adopted CI's regional shortnames where they're stable. URL slugs are
-- precomputed (lowercase, kebab) for the FastAPI regional pages.

CREATE TABLE ref.dno_region (
    region_id           SMALLINT     PRIMARY KEY,
    canonical_code      VARCHAR(24)  NOT NULL UNIQUE,
    slug                VARCHAR(40)  NOT NULL UNIQUE,
    name                TEXT         NOT NULL,
    -- NULL for the NATIONAL sentinel (no DNO codes apply).
    carbon_intensity_id SMALLINT     UNIQUE,
    octopus_code        CHAR(1)      UNIQUE,
    notes               TEXT
);

COMMENT ON TABLE  ref.dno_region              IS 'Canonical UK DNO regions + national sentinel; cross-references source-specific codes.';
COMMENT ON COLUMN ref.dno_region.region_id    IS '0 = NATIONAL sentinel; 1..14 = DNO regions.';
COMMENT ON COLUMN ref.dno_region.canonical_code IS 'Internal short code, e.g. NATIONAL, LON, SE.';
COMMENT ON COLUMN ref.dno_region.slug         IS 'URL-friendly form, e.g. national, london, south-east.';
