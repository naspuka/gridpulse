# GridPulse

A real-time UK energy intelligence platform. Ingests live grid generation, carbon intensity, and electricity prices, joins them, and serves both a personal "when should I run my dishwasher" recommendation and deeper grid analytics.

Built as a portfolio project to demonstrate modern data engineering practices end-to-end: ingestion, orchestration, hot/cold storage tiering, transformations, observability, IaC, and CI/CD.

---

## Status

V1 in progress. Target: live deployment at gridpulse.uk in ~6 weekends. See **Build phases** below.

---

## Stack (locked — do not bikeshed)

| Layer | Choice |
|---|---|
| Ingestion | Python — `httpx`, `tenacity` (retries), `pydantic` (schema validation) |
| Orchestration | Dagster OSS |
| Hot serving store | Postgres 16 + TimescaleDB (last 90 days) |
| Cold lakehouse | Apache Iceberg on Cloudflare R2, via PyIceberg (full history) |
| Transformations | dbt-core. Postgres adapter for hot, DuckDB-on-Iceberg adapter for cold |
| Lakehouse query engine | DuckDB (embedded) |
| API | FastAPI |
| UI | HTMX + Jinja2 templates served by FastAPI. Tailwind + DaisyUI via CDN. Chart.js for viz |
| IaC | Terraform (Hetzner + Cloudflare providers) |
| Containers | Docker Compose |
| CI/CD | GitHub Actions (public repo — free) |
| Monitoring | Grafana Cloud free tier + healthchecks.io + Sentry |
| Hosting | Hetzner CX32 (~£7/mo) + Cloudflare R2 (free tier) + domain (~£1/mo amortised) |
| Secrets | `.env` + systemd environment files (or Doppler free tier) |

**Total target cost: ~£8/month all-in.**

---

## Architecture

Five layers, top to bottom:

1. **External APIs** — Carbon Intensity API (NESO/Oxford/EDF), NESO Data Portal (generation mix), Octopus Energy (Agile prices, 14 regions). Elexon BMRS deferred to V2.
2. **Ingestion + orchestration** — Dagster assets, scheduled. Pydantic-validated. Idempotent. Retries with backoff. Heartbeats to healthchecks.io.
3. **Storage (dual tier)** —
   - **Hot:** Postgres + TimescaleDB hypertables. Last 90 days. Powers the live UI.
   - **Cold:** Iceberg tables on R2, partitioned by date. Full history including backfills. Queried via DuckDB.
   - Nightly Dagster job archives Postgres → Iceberg.
4. **Transformations** — dbt-core. Staging models per source → mart tables. `dbt test` for not-null, uniqueness, referential integrity.
5. **Serving** — FastAPI with Jinja2 + HTMX. Public JSON API at `/api/v1/...` (auto-documented via OpenAPI).

**Why dual storage?** Hot Postgres for sub-second user queries; Iceberg for cheap, infinite-scale historical analytics and ML training data. Same data, two access patterns. This is the senior-level architectural answer in interviews — preserve it in any refactor.

---

## V1 scope

**In:**
- Carbon Intensity API ingestion (national + regional, every 30 mins)
- NESO generation mix ingestion (every 5 mins)
- Octopus Agile ingestion (all 14 regions, daily after 4pm UK time)
- Postgres hot store (90d) + Iceberg cold store (full history with backfill from 2018)
- dbt models: cleaned facts, hourly aggregates, "cheapest/greenest half-hours next 24h"
- Landing page: live generation donut, current carbon intensity, current Agile price, "best slot tonight" recommendation
- Regional page: pick DNO region, see localised data
- Status page + Grafana pipeline-health dashboard
- README with architecture diagram, decisions log, screenshots, live link

**Out (V2+):**
- Elexon BMRS / balancing market / constraint payments
- Met Office weather correlation
- Price forecasting (ML)
- Battery arbitrage backtester
- "Bloomberg terminal" deep analytics view
- Public-facing API beyond V1 basics
- Smart meter integration

**Push back hard on adding to V1.** A live, basic, shipped V1 beats a half-built grand vision every time.

---

## Conventions

These exist to prevent foot-guns. Don't deviate without thinking through the consequence.

**Time zones.** UTC everywhere internally. Convert only at display layer. UK energy APIs mix UTC, local time, and "settlement period N" (where N can be 46 or 50 on DST days). All ingestion code normalises to UTC immediately on receipt.

**Data contracts.** Every external API response goes through a `pydantic` model. Schema drift should fail loudly, not silently corrupt data. New models live in `gridpulse/contracts/`.

**Idempotency.** Every Dagster asset must be safely re-runnable. No duplicates, no gaps. Use natural keys (e.g. `(region, settlement_period_start_utc)`) with upserts, not append-only inserts.

**Rate limits & ToS.** Respect every API's limits. Cache aggressively. Exponential backoff on retries. Read each API's terms before adding it — some prohibit redistribution, some require attribution.

**Attribution (required, not optional).**
- Carbon Intensity API: CC-BY 4.0 attribution.
- Elexon BMRS (when added in V2): "Contains BMRS data © Elexon Limited copyright and database right [year]" — verbatim.
- Octopus: check current dev API terms before launch.
- Footer of the live site carries all attributions.

**Secrets.** Never commit `.env`. Always commit `.env.example`. CI uses GitHub Actions secrets. Production uses systemd environment files or Doppler.

**Testing.** Not aiming for 100% coverage. Aiming for *meaningful* tests:
- pytest unit tests for ingestion parsing/validation logic
- pytest integration tests with a throwaway Postgres container for at least one end-to-end pipeline
- `dbt test` on every mart model (not-null, unique, accepted_values where relevant)
- One smoke test in CI that boots Docker Compose and hits `/healthz`

**Backups.** Nightly `pg_dump` to R2. Retain 30 days. Tested restore once before launch.

**Observability.**
- Every Dagster asset reports success/failure to healthchecks.io.
- Sentry catches uncaught exceptions in ingestion, API, and Dagster code.
- Grafana dashboard shows: last successful ingest per source, ingest latency, row counts, error rate.
- "Last successful ingest" timestamps are surfaced on a public `/status` page.

---

## Decisions log

The "why" behind non-obvious choices. Update this rather than relitigating.

- **Iceberg over Delta.** Both fine. Iceberg has broader 2026 momentum (Snowflake, Databricks, AWS, Google all backing). PyIceberg is mature. Pick one — chose Iceberg.
- **Postgres + Iceberg dual tier (not just one).** Postgres alone is fine for serving but doesn't show off lakehouse skills. Iceberg alone has slow user-facing queries on a small VM. Splitting them tells a real architectural story and matches how production systems are built.
- **Dagster over Airflow / Prefect.** Asset-based mental model is cleaner for a data platform. Lineage UI is genuinely useful and looks great in interviews. OSS version is free and self-hostable.
- **dbt-core (not Cloud).** Free, self-hosted, runs as a Dagster asset.
- **HTMX + Jinja over React/Next.js.** Project is a *data engineering* CV piece, not a frontend one. HTMX is defensible in 2026 (genuinely having a moment) and lets 90% of effort go into pipelines. V2 can swap in a richer frontend if useful.
- **Hetzner over AWS/GCP.** Cost. A CX32 at ~£7/mo runs the whole stack comfortably. AWS equivalents are 5-10x more once egress is counted. Have an interview-ready answer for "what would you do at scale" (managed Kafka via Redpanda Cloud, multi-AZ Postgres, Snowflake or Databricks for analytical layer).
- **Cloudflare R2 over S3.** R2 has zero egress charges and a 10GB free tier. Killer feature for a lakehouse where you'll repeatedly read history.
- **No Kafka in V1.** Energy data updates every 5–30 minutes. A scheduled Dagster job hitting the API on that cadence is functionally indistinguishable from streaming and infinitely cheaper. If we want to demonstrate streaming knowledge in V2, add a single Redpanda topic for one specific use case (e.g. price-alert events).
- **Public GitHub repo from day one.** Commit history is part of the CV story.

---

## Build phases

Six weekends. Resist compressing — each phase has a learning goal, not just an output.

1. **Foundations.** Hetzner VM via Terraform. Docker Compose with Postgres + TimescaleDB + Dagster. HTTPS via Caddy. Empty repo with `.gitignore`, `.env.example`, README skeleton, GitHub Actions linting.
2. **First ingestion end-to-end.** Carbon Intensity API only. One Dagster asset, pydantic-validated, writing to Timescale. healthchecks.io + Sentry wired up.
3. **Broaden ingestion + dbt.** Add NESO and Octopus. dbt staging models per source → `mart_half_hourly` joined on settlement period. `dbt test` on everything.
4. **Iceberg lakehouse.** R2 bucket via Terraform. PyIceberg setup. Nightly Postgres → Iceberg archival. Backfill Carbon Intensity history from 2018. DuckDB queries over Iceberg working.
5. **Serving layer.** FastAPI + Jinja + HTMX. Tailwind/DaisyUI/Chart.js via CDN. Landing page + regional page + `/api/v1/...` JSON endpoints.
6. **Polish + ship.** Grafana pipeline-health dashboard. Status page. Nightly pg_dump backups. Killer README. Submit to Show HN + r/dataengineering.

---

## Risks / watch-outs

- **Dagster RAM footprint.** Webserver + daemon ~600MB-1GB. On a 4GB VM with Postgres, tune `shared_buffers` carefully. CX32 (8GB) is the safer pick.
- **Iceberg fiddliness.** Schema evolution, partition specs, snapshot management, compaction — all real work. Budget 2–3 weekends to feel solid with PyIceberg.
- **Cold-start dashboards.** If FastAPI hits Postgres directly after idle, first query is slow. Add basic in-memory caching on the API layer for hot queries.
- **DST and settlement periods.** UK clocks change in March/October. DST days have 46 or 50 settlement periods, not 48. Test ingestion on those exact dates with synthetic data.
- **API discontinuities in source data.** Octopus Agile had a structural pricing change on 1 April 2026 (~3.5p/kWh reduction across regions). **Confirmed June 2026** via Octopus's own blog (energy-price-cap-apr-2026) — driven by the Nov 2025 Budget removing ECO + shifting 75% of Renewables Obligation costs onto general taxation through 2029. ~£126/yr off a typical bill. Historical pricing comparisons that straddle 1 Apr 2026 must surface this discontinuity — `mart_half_hourly` and `mart_best_slots_24h` should add a `price_regime` column (`pre_apr_2026_levy` / `post_apr_2026_levy`) so consumers of the mart can split or normalise as needed.
- **Hetzner / R2 pricing drift.** Confirm CX32 spec, region, and current £/mo before provisioning. R2 free-tier limits stable as of last check, but verify.
- **Scope creep.** The single biggest killer. Ship V1 before adding anything.

---

## "What would you do with budget?" (interview prep)

Be ready to articulate the scaled-up version:
- Managed streaming (Redpanda Cloud or Confluent) for true sub-minute latency.
- Multi-AZ managed Postgres (RDS / Aurora / Cloud SQL).
- Snowflake or Databricks SQL for the analytical layer instead of self-hosted DuckDB-on-Iceberg.
- Proper data catalogue (Unity Catalog or Datahub).
- Kubernetes for orchestration runners, with autoscaling.
- Dedicated observability (Datadog) instead of Grafana free tier.
- Domain-specific CDN / edge caching for the public API.

The point in interviews isn't that GridPulse needs any of this — it's that you understand *why* you didn't build it and *when* you would.

---

## Working with Claude Code in this repo

- This file is the source of truth for *what* and *why*. Read it before suggesting architectural changes.
- For *how*: prefer reading the actual code. Don't infer.
- When in doubt about scope, default to "out of V1." Push back on scope creep.
- When making non-trivial decisions, append a one-liner to the **Decisions log** above with the rationale.
- Conventions section is binding. Flag deviations explicitly rather than silently working around them.
