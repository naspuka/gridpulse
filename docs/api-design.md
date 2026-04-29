# API + UI design

FastAPI serves two surfaces from one codebase: an HTML UI (HTMX-driven) and a JSON API. Both call the same query layer.

## Hard rules

- **API is read-only** against Postgres `marts.*`. No write endpoints, ever. Future writes are Dagster sensors, not HTTP handlers.
- **No authentication in V1.** All data is public. Rate limiting, not auth, is the abuse defence.
- **All response timestamps are UTC, ISO-8601 with `Z`.** No exceptions.
- **No cold-storage queries on the request path.** FastAPI never reads Iceberg directly.

## Two parallel route trees

```
HTML routes (Jinja fragments, for HTMX)
  /                                  → full landing page
  /region/<slug>                     → full regional page
  /partials/best-slots/<slug>        → just the "best slots" card
  /partials/generation-donut         → just the donut
  /partials/current-conditions/<slug>→ just the "now" stat block
  /status                            → status page
  /404, /500                         → error pages

JSON routes (data, OpenAPI-documented at /docs)
  /api/v1/regions
  /api/v1/carbon-intensity/current?region=LON
  /api/v1/carbon-intensity/range?region=LON&from=...&to=...
  /api/v1/agile-price/current?region=LON
  /api/v1/agile-price/range?region=LON&from=...&to=...
  /api/v1/generation-mix/current
  /api/v1/best-slots?region=LON&horizon_hours=24
  /healthz
```

HTML routes and JSON routes share **one** query layer (`gridpulse/api/queries.py`). Two presentation layers, one data layer. **Never duplicate SQL across HTML and JSON paths.**

## The HTMX dance

1. First request to `/` returns a fully-rendered HTML page. No spinners, no "loading…" — server runs the queries inline. **First paint is fast and complete.**
2. Each card has `hx-get="/partials/..." hx-trigger="every 60s"` for auto-refresh without a page reload.
3. Region picker uses `hx-get="/region/<slug>" hx-target="body" hx-push-url="true"` — URL changes server-side, no client state.

The whole point of HTMX: **server is the source of truth, partials are just smaller pages.** No hydration, no bundler, no client state to debug.

## URL conventions

- **Slugs for human URLs:** `/region/london` (lowercase, kebab-case, from `ref.dno_region.slug`)
- **Canonical codes for API params:** `?region=LON` (uppercase, from `ref.dno_region.canonical_code`)
- **`?region=NATIONAL`** for the national rollup
- Both map to internal `region_id` in the query layer
- Bad slug → 404; bad canonical code → 400

## Range query rules (JSON)

- Inclusive-from, exclusive-to (standard half-open interval)
- Cap at **14 days**. Bigger windows → 400 ("use the lakehouse"). We don't want the live API doing huge scans.
- No pagination in V1. Every endpoint returns one row or a bounded range.

## Errors

Standard FastAPI `HTTPException` → `{"detail": "..."}`. Status codes do the work. No custom error envelope.

## Response models

`gridpulse/api/schemas.py` — separate from the ingestion contracts in `gridpulse/contracts/`. **Don't reuse contract models for API responses.** Different jobs:

- Contracts validate *input* shape from external APIs
- Response models define *our* output shape and OpenAPI schema

Coupling them means a wire-format change at one source ripples into every API consumer. Ours stays decoupled.

```python
# gridpulse/api/schemas.py
class CarbonIntensityNow(BaseModel):
    region: str
    period_start_utc: datetime
    period_end_utc: datetime
    forecast_gco2_per_kwh: int
    actual_gco2_per_kwh: int | None
    index: str

class BestSlot(BaseModel):
    period_start_utc: datetime
    period_end_utc: datetime
    price_pence_per_kwh_inc_vat: float
    forecast_gco2_per_kwh: int | None
    cheapest_rank: int | None
    greenest_rank: int | None

class BestSlotsResponse(BaseModel):
    region: str
    computed_at_utc: datetime
    slots: list[BestSlot]
```

## Caching — three layers, three jobs

| Layer | Purpose | TTL |
|---|---|---|
| HTTP `Cache-Control` headers | Cloudflare edge caches for us | 60 s for "current"; 300 s for ranges |
| In-process TTL cache (`cachetools.TTLCache`) | Removes ~95% of repeat queries during traffic spikes | 30 s |
| Postgres marts | The actual data | refreshed by dbt after each ingestion |

**No Redis in V1.** Single FastAPI process, in-process cache is enough. If we ever multi-worker and find cache stampedes, *then* Redis. Not before.

The CLAUDE.md "cold-start dashboards" risk is exactly what the in-process cache fixes.

## Rate limiting

`slowapi`, keyed by client IP, **30 requests/minute** per IP on `/api/v1/*`. Cloudflare in front absorbs obvious abuse before it hits us. HTML routes uncapped (humans don't hit them at scale).

Rate-limited responses: `429` with `Retry-After`.

## Healthcheck

```python
@app.get("/healthz")
def healthz():
    db_ok = postgres.execute("SELECT 1").fetchone() is not None
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "fail",
        "version": os.getenv("GIT_SHA", "dev"),
    }
```

Used by:

- CI smoke test (`docker compose up && curl localhost/healthz`)
- Caddy upstream health checks
- External uptime monitoring

Not used by Dagster heartbeats — those are per-asset.

## Templates layout

```
gridpulse/api/templates/
├── base.html                       # <html>, header, footer with attribution
├── landing.html                    # extends base
├── region.html                     # extends base, region-bound
├── status.html
├── 404.html, 500.html
├── partials/
│   ├── current_conditions.html
│   ├── best_slots.html
│   ├── generation_donut.html
│   ├── carbon_trend_chart.html
│   └── _last_updated.html
└── _macros.html                    # format_pence, format_gco2, etc.
```

Convention: partials live in `partials/`, referenced both via `{% include %}` (full pages) and returned standalone (HTMX endpoints). One template, two callers — no duplication.

## Charts

Chart.js via CDN (~80 KB gzipped). Used for:

- Donut: generation mix
- Line: 24h carbon intensity trend
- (Maybe) bar: half-hourly prices

Initialised in a `<script>` block at the bottom of each partial, reading data from a `<script type="application/json">` block emitted server-side. HTMX swap re-runs the script — no SPA state to manage.

Why not Plotly: heavier, more features than we need, slower first paint.

## Footer (legally required + professionally signal-rich)

Per CLAUDE.md attribution rules, every page must include:

> *Carbon intensity data from the [Carbon Intensity API](https://carbonintensity.org.uk), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Generation mix from [NESO](https://www.neso.energy). Tariff data from [Octopus Energy](https://octopus.energy).*

Lives in `base.html`. **Non-negotiable** — both legally and as a "this person reads docs" signal.

## Performance budget

| Metric | Target | How |
|---|---|---|
| Landing page TTFB | < 100 ms | Marts small, in-process cache, no JS hydration |
| API endpoint p50 | < 20 ms | PK lookups against marts |
| API endpoint p99 | < 100 ms | Cold-cache fallback path |
| Page weight | < 200 KB | CDN deps, no bundler |
| Time to interactive | < 500 ms | Server-rendered |

Not formally benchmarked in V1; sane defaults. First lever if anything drifts: in-process cache.

## Deliberately not in V1

- Authentication / accounts (no users yet)
- Webhooks / push notifications (V2 streaming demo)
- CSV / Parquet downloads (lakehouse-backed, V2)
- Custom date pickers (range API exists; UI uses fixed "last 24h")
- Forecast charts (CI gives 96h forecast; we store but don't visualise yet)
- Multi-language (English only)
- Pixel-tuned mobile (Tailwind responsive classes get 90% there)

Listed so they don't sneak in mid-build.
