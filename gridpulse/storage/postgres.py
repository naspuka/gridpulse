"""Postgres connection pool + table-specific upsert helpers.

A single process-wide `ConnectionPool` keeps connection setup cost out of
the hot path. Assets and the FastAPI app share the same pool when they
import this module.

Upsert helpers live here too (not in `ingestion/`) because the SQL is a
storage-layer concern — the natural key, the ON CONFLICT semantics, and
the column list are all properties of the table, not the source.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from gridpulse.contracts.carbon_intensity import CarbonIntensityRow
from gridpulse.contracts.neso import NesoGenerationMixRow
from gridpulse.contracts.octopus import AgilePriceRow

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Process-wide singleton connection pool.

    Lazily opened so importing this module is cheap (matters for tests).
    Sized small: most workloads here are batches of <100 rows; we run
    ingestion serially. Bump max_size if we ever go multi-process per host.
    """
    global _pool
    if _pool is None:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError("DATABASE_URL not set")
        _pool = ConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=5,
            open=True,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def close_pool() -> None:
    """Close the pool. Mostly for tests; production lets the process exit handle it."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# raw.carbon_intensity upsert
# ---------------------------------------------------------------------------

_UPSERT_CARBON_INTENSITY_SQL = """
INSERT INTO raw.carbon_intensity (
    region_id, period_start_utc, period_end_utc,
    forecast_gco2_per_kwh, actual_gco2_per_kwh, intensity_index
) VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (region_id, period_start_utc) DO UPDATE SET
    period_end_utc        = EXCLUDED.period_end_utc,
    forecast_gco2_per_kwh = EXCLUDED.forecast_gco2_per_kwh,
    actual_gco2_per_kwh   = COALESCE(
        EXCLUDED.actual_gco2_per_kwh,
        raw.carbon_intensity.actual_gco2_per_kwh
    ),
    intensity_index       = EXCLUDED.intensity_index,
    ingested_at_utc       = now()
"""
# COALESCE on actual: once a half-hour realises and we see a non-NULL `actual`,
# we never want a later forecast-only fetch (which has actual=NULL) to wipe
# the realised value. So we prefer the incoming non-NULL; if incoming is NULL,
# keep what's already there.


# ---------------------------------------------------------------------------
# raw.generation_mix upsert
# ---------------------------------------------------------------------------

_UPSERT_GENERATION_MIX_SQL = """
INSERT INTO raw.generation_mix (
    period_start_utc, gas_mw, coal_mw, nuclear_mw, wind_mw, wind_embedded_mw,
    hydro_mw, imports_mw, biomass_mw, other_mw, solar_mw, storage_mw,
    total_generation_mw, neso_carbon_intensity_gco2_per_kwh
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (period_start_utc) DO UPDATE SET
    gas_mw                                = EXCLUDED.gas_mw,
    coal_mw                               = EXCLUDED.coal_mw,
    nuclear_mw                            = EXCLUDED.nuclear_mw,
    wind_mw                               = EXCLUDED.wind_mw,
    wind_embedded_mw                      = EXCLUDED.wind_embedded_mw,
    hydro_mw                              = EXCLUDED.hydro_mw,
    imports_mw                            = EXCLUDED.imports_mw,
    biomass_mw                            = EXCLUDED.biomass_mw,
    other_mw                              = EXCLUDED.other_mw,
    solar_mw                              = EXCLUDED.solar_mw,
    storage_mw                            = EXCLUDED.storage_mw,
    total_generation_mw                   = EXCLUDED.total_generation_mw,
    neso_carbon_intensity_gco2_per_kwh    = EXCLUDED.neso_carbon_intensity_gco2_per_kwh,
    ingested_at_utc                       = now()
"""


def upsert_generation_mix_rows(rows: Iterable[NesoGenerationMixRow]) -> int:
    """Idempotent upsert into raw.generation_mix. Returns the row count written."""
    row_list = list(rows)
    if not row_list:
        return 0
    payload = [
        (
            r.period_start_utc,
            r.gas_mw,
            r.coal_mw,
            r.nuclear_mw,
            r.wind_mw,
            r.wind_embedded_mw,
            r.hydro_mw,
            r.imports_mw,
            r.biomass_mw,
            r.other_mw,
            r.solar_mw,
            r.storage_mw,
            r.total_generation_mw,
            r.neso_carbon_intensity_gco2_per_kwh,
        )
        for r in row_list
    ]
    pool = get_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.executemany(_UPSERT_GENERATION_MIX_SQL, payload)
    log.info("upserted %d row(s) into raw.generation_mix", len(row_list))
    return len(row_list)


# ---------------------------------------------------------------------------
# raw.agile_price upsert
# ---------------------------------------------------------------------------

_UPSERT_AGILE_PRICE_SQL = """
INSERT INTO raw.agile_price (
    region_id, period_start_utc, period_end_utc,
    price_pence_per_kwh_inc_vat, price_pence_per_kwh_exc_vat
) VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (region_id, period_start_utc) DO UPDATE SET
    period_end_utc                = EXCLUDED.period_end_utc,
    price_pence_per_kwh_inc_vat   = EXCLUDED.price_pence_per_kwh_inc_vat,
    price_pence_per_kwh_exc_vat   = EXCLUDED.price_pence_per_kwh_exc_vat,
    ingested_at_utc               = now()
"""


def upsert_agile_price_rows(rows: Iterable[AgilePriceRow]) -> int:
    """Idempotent upsert into raw.agile_price. Returns the row count written."""
    row_list = list(rows)
    if not row_list:
        return 0
    payload = [
        (
            r.region_id,
            r.period_start_utc,
            r.period_end_utc,
            r.price_pence_per_kwh_inc_vat,
            r.price_pence_per_kwh_exc_vat,
        )
        for r in row_list
    ]
    pool = get_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.executemany(_UPSERT_AGILE_PRICE_SQL, payload)
    log.info("upserted %d row(s) into raw.agile_price", len(row_list))
    return len(row_list)


def upsert_carbon_intensity_rows(rows: Iterable[CarbonIntensityRow]) -> int:
    """Idempotent upsert into raw.carbon_intensity. Returns the row count written."""
    row_list = list(rows)
    if not row_list:
        return 0

    payload = [
        (
            r.region_id,
            r.period_start_utc,
            r.period_end_utc,
            r.forecast_gco2_per_kwh,
            r.actual_gco2_per_kwh,
            r.intensity_index,
        )
        for r in row_list
    ]

    pool = get_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.executemany(_UPSERT_CARBON_INTENSITY_SQL, payload)
    log.info("upserted %d row(s) into raw.carbon_intensity", len(row_list))
    return len(row_list)
