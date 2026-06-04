"""Single source of read SQL. Used by both JSON and HTML routes.

Convention (from docs/api-design.md): no SQL outside this file. If a route
needs data it doesn't yet have, you add a query here and call it. That way:
- Changing a column name is one search-and-replace, not a hunt.
- The query layer is unit-testable in isolation (pure SQL, no FastAPI).
- HTML partials and JSON endpoints stay in lock-step automatically.

All queries return SCHEMA objects (gridpulse.api.schemas.*) — never raw dicts
crossing the route boundary. The conversion happens here so route handlers
stay short.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from psycopg.rows import dict_row

from gridpulse.api.schemas import (
    AgilePricePoint,
    BestSlot,
    CarbonIntensityPoint,
    GenerationMixFuel,
    LastIngest,
    Region,
)
from gridpulse.storage.postgres import get_pool

# Per docs/api-design.md, range queries are capped at 14 days. Bigger windows
# go through DuckDB-on-Iceberg notebooks, not the live API.
MAX_RANGE_DAYS = 14


# ---------------------------------------------------------------------------
# Region dimension
# ---------------------------------------------------------------------------


def list_regions() -> list[Region]:
    """Every region in ref.dno_region, ordered by region_id (NATIONAL first)."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT region_id, canonical_code, slug, name, octopus_code
            FROM ref.dno_region
            ORDER BY region_id
            """
        )
        return [Region(**row) for row in cur.fetchall()]


def get_region_by_slug(slug: str) -> Region | None:
    """Slugs come from URLs (kebab-case). Returns None for unknown."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT region_id, canonical_code, slug, name, octopus_code
            FROM ref.dno_region
            WHERE slug = %s
            """,
            (slug,),
        )
        row = cur.fetchone()
        return Region(**row) if row else None


def get_region_by_canonical_code(code: str) -> Region | None:
    """Canonical codes come from API query params (UPPERCASE)."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT region_id, canonical_code, slug, name, octopus_code
            FROM ref.dno_region
            WHERE canonical_code = %s
            """,
            (code.upper(),),
        )
        row = cur.fetchone()
        return Region(**row) if row else None


# ---------------------------------------------------------------------------
# Carbon intensity
# ---------------------------------------------------------------------------


def get_current_carbon_intensity(region_id: int) -> CarbonIntensityPoint | None:
    """Latest half-hour we have for the region. Reads from the mart."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT region_id, period_start_utc, period_end_utc,
                   forecast_gco2_per_kwh, actual_gco2_per_kwh, intensity_index
            FROM marts.mart_half_hourly
            WHERE region_id = %s
              AND intensity_index IS NOT NULL
            ORDER BY period_start_utc DESC
            LIMIT 1
            """,
            (region_id,),
        )
        row = cur.fetchone()
        return CarbonIntensityPoint(**row) if row else None


def get_carbon_intensity_range(
    region_id: int,
    from_utc: datetime,
    to_utc: datetime,
) -> list[CarbonIntensityPoint]:
    """Half-hours in [from_utc, to_utc). Capped at MAX_RANGE_DAYS."""
    if to_utc - from_utc > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError(f"range must be <= {MAX_RANGE_DAYS} days")
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT region_id, period_start_utc, period_end_utc,
                   forecast_gco2_per_kwh, actual_gco2_per_kwh, intensity_index
            FROM marts.mart_half_hourly
            WHERE region_id = %s
              AND period_start_utc >= %s
              AND period_start_utc <  %s
              AND intensity_index IS NOT NULL
            ORDER BY period_start_utc
            """,
            (region_id, from_utc, to_utc),
        )
        return [CarbonIntensityPoint(**row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Agile price
# ---------------------------------------------------------------------------


def get_current_agile_price(region_id: int) -> AgilePricePoint | None:
    """Current half-hour Agile price for one DNO region."""
    if region_id == 0:
        return None  # NATIONAL has no Agile price.
    now = datetime.now(UTC)
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT region_id, period_start_utc, period_end_utc,
                   price_pence_per_kwh_inc_vat, price_pence_per_kwh_exc_vat
            FROM raw.agile_price
            WHERE region_id = %s
              AND period_start_utc <= %s
              AND period_end_utc   >  %s
            ORDER BY period_start_utc DESC
            LIMIT 1
            """,
            (region_id, now, now),
        )
        row = cur.fetchone()
        return AgilePricePoint(**row) if row else None


def get_agile_price_range(
    region_id: int,
    from_utc: datetime,
    to_utc: datetime,
) -> list[AgilePricePoint]:
    if to_utc - from_utc > timedelta(days=MAX_RANGE_DAYS):
        raise ValueError(f"range must be <= {MAX_RANGE_DAYS} days")
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT region_id, period_start_utc, period_end_utc,
                   price_pence_per_kwh_inc_vat, price_pence_per_kwh_exc_vat
            FROM raw.agile_price
            WHERE region_id = %s
              AND period_start_utc >= %s
              AND period_start_utc <  %s
            ORDER BY period_start_utc
            """,
            (region_id, from_utc, to_utc),
        )
        return [AgilePricePoint(**row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Generation mix (national-only mart)
# ---------------------------------------------------------------------------


def get_current_generation_mix() -> tuple[datetime, list[GenerationMixFuel]] | None:
    """Latest half-hour of generation mix; returns (period_start, fuels) or None."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH latest AS (
                SELECT max(period_start_utc) AS p FROM marts.mart_generation_mix_long
            )
            SELECT period_start_utc, fuel, mw, is_renewable, share_of_generation_pct
            FROM marts.mart_generation_mix_long, latest
            WHERE period_start_utc = latest.p
            ORDER BY mw DESC
            """
        )
        rows = cur.fetchall()
        if not rows:
            return None
        ts = rows[0]["period_start_utc"]
        fuels = [
            GenerationMixFuel(
                fuel=r["fuel"],
                mw=r["mw"],
                is_renewable=r["is_renewable"],
                share_of_generation_pct=r["share_of_generation_pct"],
            )
            for r in rows
        ]
        return ts, fuels


# ---------------------------------------------------------------------------
# Best slots (24-hour outlook)
# ---------------------------------------------------------------------------


def get_best_slots(region_id: int) -> tuple[datetime | None, list[BestSlot]]:
    """All ranked half-hours for the region in mart_best_slots_24h.

    Returns (computed_at_utc, slots). computed_at_utc is the materialise
    timestamp the mart wrote — null if the mart is empty (early in the V1
    lifecycle, before the dbt schedule has run with real data).
    """
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT computed_at_utc, period_start_utc, period_end_utc,
                   price_pence_per_kwh_inc_vat, forecast_gco2_per_kwh,
                   cheapest_rank, greenest_rank
            FROM marts.mart_best_slots_24h
            WHERE region_id = %s
            ORDER BY period_start_utc
            """,
            (region_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return None, []
        computed_at = rows[0]["computed_at_utc"]
        slots = [
            BestSlot(
                period_start_utc=r["period_start_utc"],
                period_end_utc=r["period_end_utc"],
                price_pence_per_kwh_inc_vat=r["price_pence_per_kwh_inc_vat"],
                forecast_gco2_per_kwh=r["forecast_gco2_per_kwh"],
                cheapest_rank=r["cheapest_rank"],
                greenest_rank=r["greenest_rank"],
            )
            for r in rows
        ]
        return computed_at, slots


# ---------------------------------------------------------------------------
# Status — last-ingest per source (for /status page + StatusResponse)
# ---------------------------------------------------------------------------


def get_last_ingests() -> list[LastIngest]:
    """One row per source. Used by both the /status JSON and the HTML page."""
    rows: list[LastIngest] = []
    pairs = [
        ("carbon_intensity", "raw.carbon_intensity"),
        ("generation_mix", "raw.generation_mix"),
        ("agile_price", "raw.agile_price"),
    ]
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        for source, table in pairs:
            cur.execute(
                f"""
                SELECT
                    max(period_start_utc) AS last_period_utc,
                    max(ingested_at_utc)  AS last_ingest_utc,
                    count(*)              AS row_count
                FROM {table}
                """
            )
            row = cur.fetchone()
            rows.append(
                LastIngest(
                    source=source,
                    last_period_utc=row["last_period_utc"] if row else None,
                    last_ingest_utc=row["last_ingest_utc"] if row else None,
                    row_count=int(row["row_count"]) if row else 0,
                )
            )
    return rows


def db_ok() -> bool:
    try:
        with get_pool().connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
        return bool(row == (1,))
    except Exception:  # noqa: BLE001 — fail-closed
        return False
