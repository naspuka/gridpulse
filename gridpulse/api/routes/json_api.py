"""JSON API routes — mounted under /api/v1.

All read-only. Auto-documented at /docs via FastAPI's response_model hooks.
Per docs/api-design.md:
- Range queries cap at 14 days; bigger → 400.
- Canonical codes (UPPERCASE) in ?region= params; slugs only in HTML URLs.
- 30/min per-IP rate limit (mounted at the route group level).

Mart vs raw split:
- mart_half_hourly is the source of truth for carbon intensity (per region).
- raw.agile_price feeds the price endpoints (we don't refresh the mart fast
  enough yet to use it).
- mart_generation_mix_long is national-only.
- mart_best_slots_24h answers /best-slots in one PK lookup.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request

from gridpulse.api import queries
from gridpulse.api.cache import cache_current, cache_range
from gridpulse.api.main import limiter
from gridpulse.api.schemas import (
    AgilePriceCurrentResponse,
    AgilePriceRangeResponse,
    BestSlotsResponse,
    CarbonIntensityCurrentResponse,
    CarbonIntensityRangeResponse,
    GenerationMixCurrentResponse,
    GenerationMixFuel,
    RegionsResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["v1"])

# Per-IP rate limit. slowapi exposes this as a decorator on each route.
_RATE = "30/minute"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_region(code: str):  # type: ignore[no-untyped-def]
    """`?region=LONDON` → Region, or 400 if unknown."""
    region = queries.get_region_by_canonical_code(code)
    if region is None:
        raise HTTPException(status_code=400, detail=f"unknown region code: {code}")
    return region


def _parse_window(from_: datetime, to: datetime) -> tuple[datetime, datetime]:
    """Validate [from, to) — must be ordered, tz-aware UTC, ≤14d."""
    if from_.tzinfo is None or to.tzinfo is None:
        raise HTTPException(status_code=400, detail="from/to must be tz-aware ISO 8601")
    if to <= from_:
        raise HTTPException(status_code=400, detail="to must be > from")
    if to - from_ > timedelta(days=queries.MAX_RANGE_DAYS):
        raise HTTPException(
            status_code=400,
            detail=f"window must be ≤ {queries.MAX_RANGE_DAYS} days",
        )
    return from_, to


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------


@cache_current
def _list_regions_cached() -> RegionsResponse:
    return RegionsResponse(regions=queries.list_regions())


@router.get(
    "/regions",
    response_model=RegionsResponse,
    summary="List DNO regions",
    description="Every region including the NATIONAL sentinel. Cached for 30 seconds.",
)
@limiter.limit(_RATE)
def list_regions_endpoint(request: Request) -> RegionsResponse:  # noqa: ARG001
    return _list_regions_cached()


# ---------------------------------------------------------------------------
# Carbon intensity
# ---------------------------------------------------------------------------


@router.get(
    "/carbon-intensity/current",
    response_model=CarbonIntensityCurrentResponse,
    summary="Most recent half-hour of carbon intensity for one region",
)
@limiter.limit(_RATE)
def carbon_intensity_current(
    request: Request,  # noqa: ARG001
    region: str = Query(
        default="NATIONAL", description="Canonical region code, e.g. NATIONAL or LONDON."
    ),
) -> CarbonIntensityCurrentResponse:
    region_obj = _resolve_region(region)
    current = _carbon_current_cached(region_obj.region_id)
    if current is None:
        raise HTTPException(status_code=404, detail="no carbon intensity data for this region yet")
    return CarbonIntensityCurrentResponse(region=region_obj, current=current)


@cache_current
def _carbon_current_cached(region_id: int):  # type: ignore[no-untyped-def]
    return queries.get_current_carbon_intensity(region_id)


@router.get(
    "/carbon-intensity/range",
    response_model=CarbonIntensityRangeResponse,
    summary="Carbon intensity half-hours over an inclusive-from / exclusive-to UTC window (≤14 d)",
)
@limiter.limit(_RATE)
def carbon_intensity_range(
    request: Request,  # noqa: ARG001
    region: str = Query(default="NATIONAL"),
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
) -> CarbonIntensityRangeResponse:
    region_obj = _resolve_region(region)
    from_, to = _parse_window(from_, to)
    points = _carbon_range_cached(region_obj.region_id, from_, to)
    return CarbonIntensityRangeResponse(region=region_obj, points=points)


@cache_range
def _carbon_range_cached(region_id: int, from_: datetime, to: datetime):  # type: ignore[no-untyped-def]
    return queries.get_carbon_intensity_range(region_id, from_, to)


# ---------------------------------------------------------------------------
# Agile price
# ---------------------------------------------------------------------------


@router.get(
    "/agile-price/current",
    response_model=AgilePriceCurrentResponse,
    summary="Current half-hour Agile unit rate for one DNO region",
)
@limiter.limit(_RATE)
def agile_price_current(
    request: Request,  # noqa: ARG001
    region: str = Query(description="Canonical DNO code (not NATIONAL — Agile is per-DNO)."),
) -> AgilePriceCurrentResponse:
    region_obj = _resolve_region(region)
    if region_obj.region_id == 0:
        raise HTTPException(
            status_code=400, detail="Agile pricing is per-DNO; pick a region other than NATIONAL"
        )
    current = _agile_current_cached(region_obj.region_id)
    return AgilePriceCurrentResponse(region=region_obj, current=current)


@cache_current
def _agile_current_cached(region_id: int):  # type: ignore[no-untyped-def]
    return queries.get_current_agile_price(region_id)


@router.get(
    "/agile-price/range",
    response_model=AgilePriceRangeResponse,
    summary="Agile half-hourly prices over a window (≤14 d)",
)
@limiter.limit(_RATE)
def agile_price_range(
    request: Request,  # noqa: ARG001
    region: str = Query(),
    from_: datetime = Query(alias="from"),
    to: datetime = Query(),
) -> AgilePriceRangeResponse:
    region_obj = _resolve_region(region)
    if region_obj.region_id == 0:
        raise HTTPException(status_code=400, detail="Agile pricing is per-DNO")
    from_, to = _parse_window(from_, to)
    points = _agile_range_cached(region_obj.region_id, from_, to)
    return AgilePriceRangeResponse(region=region_obj, points=points)


@cache_range
def _agile_range_cached(region_id: int, from_: datetime, to: datetime):  # type: ignore[no-untyped-def]
    return queries.get_agile_price_range(region_id, from_, to)


# ---------------------------------------------------------------------------
# Generation mix
# ---------------------------------------------------------------------------


@router.get(
    "/generation-mix/current",
    response_model=GenerationMixCurrentResponse,
    summary="Latest national generation mix by fuel (long format)",
)
@limiter.limit(_RATE)
def generation_mix_current(request: Request) -> GenerationMixCurrentResponse:  # noqa: ARG001
    cached = _gen_mix_current_cached()
    if cached is None:
        raise HTTPException(status_code=404, detail="no generation mix data yet")
    ts, fuels = cached
    return GenerationMixCurrentResponse(period_start_utc=ts, fuels=fuels)


@cache_current
def _gen_mix_current_cached() -> tuple[datetime, list[GenerationMixFuel]] | None:
    return queries.get_current_generation_mix()


# ---------------------------------------------------------------------------
# Best slots — the killer endpoint for the landing page
# ---------------------------------------------------------------------------


@router.get(
    "/best-slots",
    response_model=BestSlotsResponse,
    summary="Forward-looking 24h slots ranked by price and forecast carbon",
)
@limiter.limit(_RATE)
def best_slots(
    request: Request,  # noqa: ARG001
    region: str = Query(
        description="Canonical DNO code (not NATIONAL — Agile pricing is per-DNO)."
    ),
) -> BestSlotsResponse:
    region_obj = _resolve_region(region)
    if region_obj.region_id == 0:
        raise HTTPException(status_code=400, detail="best_slots needs a DNO region (not NATIONAL)")
    computed_at, slots = _best_slots_cached(region_obj.region_id)
    if computed_at is None:
        # Cleanly degrade — dbt may not have produced this mart yet on a
        # fresh box. Caller gets an empty list rather than a 500.
        return BestSlotsResponse(
            region=region_obj,
            computed_at_utc=datetime.now(UTC),
            slots=[],
        )
    return BestSlotsResponse(region=region_obj, computed_at_utc=computed_at, slots=slots)


@cache_current
def _best_slots_cached(region_id: int):  # type: ignore[no-untyped-def]
    return queries.get_best_slots(region_id)
