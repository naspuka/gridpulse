"""HTML + HTMX routes. Templates live in `gridpulse/api/templates/`.

Convention (docs/api-design.md):
- Full pages (`/`, `/region/<slug>`) return server-rendered HTML.
- Partials (`/partials/...`) return small HTML fragments — driven by HTMX
  for the "every 60 s" auto-refresh.
- Slugs in URLs are kebab-case; canonical codes only inside the API layer.

Each route is uncapped for rate limiting — humans don't hit them at
machine cadence, and slowapi noise on landing pages is bad UX.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from gridpulse.api import queries
from gridpulse.api.main import templates

router = APIRouter(tags=["html"])

# Default landing region: NATIONAL for the carbon/generation cards, London
# for Agile (national has no Agile price). Tweakable per request via the
# region picker once Phase 5C-2 wires HTMX.
_DEFAULT_AGILE_REGION_SLUG = "london"


def _ctx(request: Request, **extra) -> dict:
    """Common template context — every page gets the regions list for the picker."""
    return {
        "request": request,
        "regions": queries.list_regions(),
        "now_utc": datetime.now(UTC),
        **extra,
    }


# ---------------------------------------------------------------------------
# Landing page (NATIONAL view)
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def landing(request: Request) -> HTMLResponse:
    # National carbon, national generation mix, default-region Agile + best slots.
    national = queries.get_region_by_canonical_code("NATIONAL")
    default_region = queries.get_region_by_slug(_DEFAULT_AGILE_REGION_SLUG)
    return templates.TemplateResponse(
        request,
        name="landing.html",
        context=_ctx(
            request,
            region=national,
            agile_region=default_region,
        ),
    )


# ---------------------------------------------------------------------------
# Regional page
# ---------------------------------------------------------------------------


@router.get("/region/{slug}", response_class=HTMLResponse)
def region_page(request: Request, slug: str) -> HTMLResponse:
    region = queries.get_region_by_slug(slug)
    if region is None:
        raise HTTPException(status_code=404, detail=f"unknown region: {slug}")
    return templates.TemplateResponse(
        request,
        name="region.html",
        context=_ctx(
            request,
            region=region,
            agile_region=region
            if region.region_id != 0
            else queries.get_region_by_slug(_DEFAULT_AGILE_REGION_SLUG),
        ),
    )


# ---------------------------------------------------------------------------
# Partials (HTMX-target endpoints) — each returns one card-sized HTML fragment.
# ---------------------------------------------------------------------------


@router.get("/partials/current-conditions/{slug}", response_class=HTMLResponse)
def partial_current_conditions(request: Request, slug: str) -> HTMLResponse:
    region = queries.get_region_by_slug(slug)
    if region is None:
        raise HTTPException(status_code=404)
    current = queries.get_current_carbon_intensity(region.region_id)
    return templates.TemplateResponse(
        request,
        name="partials/current_conditions.html",
        context={"request": request, "region": region, "current": current},
    )


@router.get("/partials/best-slots/{slug}", response_class=HTMLResponse)
def partial_best_slots(request: Request, slug: str) -> HTMLResponse:
    region = queries.get_region_by_slug(slug)
    if region is None or region.region_id == 0:
        raise HTTPException(status_code=400)
    computed_at, slots = queries.get_best_slots(region.region_id)
    return templates.TemplateResponse(
        request,
        name="partials/best_slots.html",
        context={
            "request": request,
            "region": region,
            "computed_at": computed_at,
            "slots": slots,
        },
    )


@router.get("/partials/generation-donut", response_class=HTMLResponse)
def partial_generation_donut(request: Request) -> HTMLResponse:
    cached = queries.get_current_generation_mix()
    period = cached[0] if cached else None
    fuels = cached[1] if cached else []
    return templates.TemplateResponse(
        request,
        name="partials/generation_donut.html",
        context={"request": request, "period": period, "fuels": fuels},
    )


@router.get("/partials/carbon-trend/{slug}", response_class=HTMLResponse)
def partial_carbon_trend(request: Request, slug: str) -> HTMLResponse:
    region = queries.get_region_by_slug(slug)
    if region is None:
        raise HTTPException(status_code=404)
    to = datetime.now(UTC)
    from_ = to - timedelta(hours=24)
    points = queries.get_carbon_intensity_range(region.region_id, from_, to)
    return templates.TemplateResponse(
        request,
        name="partials/carbon_trend.html",
        context={"request": request, "region": region, "points": points},
    )


# ---------------------------------------------------------------------------
# Status page
# ---------------------------------------------------------------------------


@router.get("/status", response_class=HTMLResponse)
def status_page(request: Request) -> HTMLResponse:
    last_ingests = queries.get_last_ingests()
    return templates.TemplateResponse(
        request,
        name="status.html",
        context=_ctx(
            request,
            db_ok=queries.db_ok(),
            last_ingests=last_ingests,
        ),
    )
