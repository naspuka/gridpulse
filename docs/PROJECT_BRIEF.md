# GridPulse — Project Brief

> A real-time UK energy intelligence platform, built as a CV-grade data engineering portfolio project.

**Status:** Ideation complete, architecture locked, ready to build
**Target:** Live V1 in ~6 weekends
**Budget:** ~£8/month all-in
**Stack philosophy:** Backend-heavy, lean infra, modern tooling, every component justifiable in an interview

---

## 1. Concept

GridPulse ingests live UK electricity grid data, electricity prices, and weather from public APIs, then serves two complementary front doors from one platform:

- A consumer-facing "what should I do tonight" view — when energy is cheapest, when it's greenest, what the best half-hour slot is for running the dishwasher or charging an EV.
- An analyst-facing grid intelligence view — generation mix, regional carbon intensity, year-over-year comparisons, and (in V2) balancing market and constraint payment data.

The pitch in one line: *"I got annoyed I couldn't tell when my Octopus rate was cheap, so I built a platform."*

### Why this project (vs. the usual portfolio ideas)

- **Real production-grade data sources.** Heterogeneous APIs, different schemas, different rate limits, different reliability characteristics — the kind of integration problem you'd actually face on the job.
- **True streaming + batch hybrid.** Genuinely justifies modern data stack tools without it feeling forced.
- **Live business case.** Heat pumps, EVs, batteries, dynamic tariffs, net zero — every UK utility is hiring data people right now. Project doubles as a domain-knowledge signal.
- **Not done to death.** GitHub has plenty of energy notebooks and static dashboards; a live, deployed, properly architected platform is rare.
- **Roadmap room.** V1 is a dashboard. V2 adds forecasting (ML angle). V3 adds carbon-aware scheduling recommendations or an agent layer.

---

## 2. Data sources

All free, all public, all production-grade as of April 2026.

| Source | What it gives | Cadence | Auth | Notes |
|---|---|---|---|---|
| **Carbon Intensity API** (NESO + Oxford + EDF) | National + regional carbon intensity, generation mix, 96-hour forecast | Every 30 min | None | Gold-standard free API. CC-BY 4.0 attribution required. |
| **NESO Data Portal** (formerly National Grid ESO) | Generation mix, demand, balancing costs, ancillary services, historical data back to 2009 | Every 5 min for live data | API token (free, since June 2024) | CKAN-backed, supports SQL queries via the API. |
| **Octopus Energy Developer API** | Half-hourly Agile prices for all 14 UK regions, published daily after 4pm | Daily refresh | None for tariff data | Public API. April 2026 levy reform created a 3.5p/kWh discontinuity — handle it explicitly. |
| **Elexon BMRS** (V2) | Balancing market data, constraint payments, settlement periods | Real-time | None | Required attribution: "Contains BMRS data © Elexon Limited copyright and database right 2026". |
| **Met Office** (V2) | Weather data for correlation analysis | Hourly | API key (free tier) | For wind/solar generation correlation. |

### Data gotchas to plan for

- **Time zones.** Every UK energy API uses different conventions — UTC, local, "settlement periods 1-50" on DST days. Store everything UTC internally, convert only at display.
- **April 2026 Agile pricing discontinuity.** The 3.5p/kWh levy reduction means historical prices are not directly comparable to current prices without normalisation.
- **Late-arriving data.** SMETS1 and SMETS2 meter readings can arrive hours or days late. Build for it.
- **Schema drift.** Use pydantic models for every API response; fail loudly when schemas change.
- **Rate limits.** Read every API's terms. Implement caching, exponential backoff, and respect.
- **Region code mismatches.** DNO regions don't align with standard UK regions. Carbon Intensity API uses 14 DNO regions; other sources may differ.

---

## 3. Architecture

Five-layer design, each layer earning its place and demonstrating something different to a recruiter.

```
┌─────────────────────────────────────────────────────────────────┐
│ SOURCES                                                         │
│ Carbon Intensity API · NESO Portal · Octopus Agile · BMRS (V2)  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ INGESTION                                                       │
│ Dagster assets · httpx · tenacity · pydantic                    │
│ Idempotent · retried · observed                                 │
└────────────────┬───────────────────────────┬────────────────────┘
                 │                           │
┌────────────────▼─────────────┐   ┌─────────▼──────────────────┐
│ HOT STORE                    │   │ COLD LAKEHOUSE             │
│ Postgres 16 + TimescaleDB    │◀──│ Apache Iceberg on R2       │
│ Last 90 days                 │   │ Full history (2009+)       │
│ Sub-second queries           │   │ PyIceberg + Parquet        │
│ Hypertables, cont. aggs      │   │ Free egress, queryable     │
└────────────────┬─────────────┘   └─────────┬──────────────────┘
                 │                           │
┌────────────────▼───────────────────────────▼───────────────────┐
│ TRANSFORMATION                                                 │
│ dbt-core · staging → marts · tests · docs                      │
│ Postgres adapter (hot) · DuckDB-on-Iceberg adapter (cold)      │
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│ SERVING                                                        │
│ FastAPI + Jinja2 + HTMX (server-rendered UI)                   │
│ Public JSON API (documented, rate-limited, cached)             │
│ Tailwind via CDN · Chart.js for visualisations                 │
└────────────────────────────────────────────────────────────────┘

INFRA: Hetzner CX32 · Docker Compose · Terraform · GitHub Actions
       Grafana Cloud · Sentry · healthchecks.io · Cloudflare R2
```

### Why each component

**Dagster (OSS) for orchestration.** Asset-based model produces the lineage graphs interview panels love. Open-source version runs as a process on the VM — Dagster Cloud costs money, OSS is free, recruiters can't tell the difference from your code.

**Postgres + TimescaleDB for the hot serving layer.** Genuinely production-grade for time-series at this scale. Lots of energy companies use exactly this. Hypertables and continuous aggregates handle the half-hourly volume comfortably.

**Iceberg on Cloudflare R2 for the cold lakehouse.** Iceberg has more momentum than Delta in 2026 (Snowflake, Databricks, AWS, Google all backing it). PyIceberg is the Python library. R2's free 10GB + zero-egress pricing is what makes this affordable — on AWS S3, lakehouse queries would rack up egress charges.

**dbt-core for transformations.** Industry standard. Tests + docs come for free. Demonstrates proper modelling discipline (staging → marts).

**FastAPI + HTMX + Jinja for serving.** Backend-focused, defensible, and HTMX is having a moment in 2026. Pairs with Tailwind via CDN (no build step) and Chart.js for visuals. Lets ~90% of effort go into pipelines and modelling, not React.

**Hetzner over AWS/GCP.** £4-7/month for a real VM that can actually run all this. AWS would be £80+ for equivalent. Recruiters don't care which cloud — they care about the architecture.

### The dual-storage story (interview gold)

> *"I used Postgres for low-latency serving and Iceberg for the analytical lakehouse — same data, optimised for two different access patterns. Postgres holds the last 90 days for the live dashboard with sub-second queries. Iceberg holds the full history back to 2009 for backtesting and ML training. A nightly Dagster job archives Postgres → Iceberg. It's a hot/cold tiering pattern that mirrors what you'd find at any production data platform."*

That's a senior-level architectural answer — exactly the kind of trade-off thinking that distinguishes mid from senior in interviews.

---

## 4. Tech stack — full inventory

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Standard for data engineering. |
| HTTP client | httpx + tenacity | Async-capable; tenacity for clean retry logic. |
| Schema validation | pydantic v2 | Loud failures on schema drift. |
| Orchestration | Dagster OSS | Asset model, lineage graphs, free. |
| Hot storage | Postgres 16 + TimescaleDB | Time-series at this scale, sub-second serving. |
| Cold storage | Apache Iceberg on Cloudflare R2 | Lakehouse format, free egress. |
| Iceberg client | PyIceberg | Mature in 2026. |
| Lakehouse query engine | DuckDB | Embedded, free, ridiculously fast. |
| Transformations | dbt-core | Industry standard, tests + docs. |
| API framework | FastAPI | Auto-generated OpenAPI docs. |
| Templating | Jinja2 | Server-rendered, simple. |
| UI behaviour | HTMX | Partial swaps, no build step, defensible. |
| CSS | Tailwind via CDN + DaisyUI | Zero build, professional look. |
| Charts | Chart.js (or Plotly) via CDN | Works inside HTMX-swapped fragments. |
| Hosting | Hetzner Cloud (CX32, 8GB RAM) | ~£7/month, plenty for the workload. |
| Object storage | Cloudflare R2 | Free 10GB tier, zero egress fees. |
| Containerisation | Docker Compose | Simple, declarative, recruiter-friendly. |
| IaC | Terraform | Hetzner + Cloudflare providers. |
| CI/CD | GitHub Actions | Free for public repos. |
| Monitoring | Grafana Cloud free tier | Dashboards + alerts. |
| Cron monitoring | healthchecks.io | Pings on success, alerts on miss. |
| Error tracking | Sentry free tier | Real-time error visibility. |
| Secrets | Doppler free tier or systemd env files | Never commit `.env`. |
| Reverse proxy / TLS | Caddy or Traefik | Auto-HTTPS via Let's Encrypt. |
| Domain | `gridpulse.uk` (target) | ~£12/year, owns the project identity. |

### Cost breakdown

| Item | Monthly |
|---|---|
| Hetzner CX32 (2 vCPU, 8GB RAM) | ~£7 |
| Cloudflare R2 (≤10GB) | £0 (free tier) |
| Domain (amortised) | ~£1 |
| Monitoring (Grafana, healthchecks, Sentry) | £0 (free tiers) |
| CI/CD (GitHub Actions, public repo) | £0 |
| **Total** | **~£8/month** |

---

## 5. V1 scope (the ruthless version)

**The goal: live, deployed, working — in ~6 weekends.**

### In scope for V1

- Ingest Carbon Intensity API (national + regional) every 30 mins
- Ingest Octopus Agile prices for all 14 regions, daily after 4pm
- Ingest NESO generation mix every 5 mins
- Store in Postgres (last 90 days) + Iceberg (full history, backfilled)
- dbt models: cleaned facts, hourly aggregates, "cheapest/greenest half-hours next 24h"
- One landing page: live generation donut, current price, current carbon, "best slot tonight" recommendation
- One regional page: pick your DNO region, see your local data
- Live deployed at `gridpulse.uk` with monitoring + status page
- Solid README with architecture diagram and decisions log

### Explicitly deferred to V2+

- Elexon BMRS (balancing market, constraint payments)
- Met Office weather correlation
- Price forecasting (Prophet or similar ML)
- Battery arbitrage backtester ("what if I had a 10kWh battery on Agile last year")
- Bloomberg-terminal-depth analytical view
- Public-facing GridPulse API for third parties
- Smart meter integration
- Carbon-aware scheduling agent

The discipline here matters. A live, basic, working platform beats a half-finished grand vision every single time.

---

## 6. Build plan — six weekends

### Weekend 1 — Foundations

Hetzner VM provisioned via Terraform. Docker Compose with Postgres + TimescaleDB + Dagster. Domain pointed at the box with HTTPS via Caddy. Empty Git repo with proper `.gitignore`, `.env.example`, README skeleton, GitHub Actions workflow that lints.

**Goal:** Push to main → something visible happens. Runway built.

### Weekend 2 — First ingestion end-to-end

Carbon Intensity API only. One Dagster asset that pulls national intensity every 30 mins, validates with pydantic, writes to a Timescale hypertable. Add healthchecks.io ping on success. Add Sentry for errors.

**Goal:** Cron-driven pipeline that runs autonomously; you'll know within minutes if it breaks. Get Dagster's mental model right here — the rest is repetition.

### Weekend 3 — Broaden ingestion + dbt

Add NESO generation mix and Octopus Agile for all 14 regions. Set up dbt-core with Postgres adapter. Build staging models (one per source), then a `mart_half_hourly` table joining them on settlement period. Add `dbt test` for not-null and uniqueness.

**Goal:** Clean, tested, joined data ready to query.

### Weekend 4 — Iceberg lakehouse

Cloudflare R2 bucket via Terraform. PyIceberg setup. Build the nightly archival job — Dagster asset that copies yesterday's Postgres data into Iceberg tables partitioned by date. Backfill historical Carbon Intensity data (2018+) directly into Iceberg. Set up DuckDB to query Iceberg locally. Add a second dbt project (or profile) for the lakehouse.

**Goal:** Both layers queryable; can articulate why each exists.

### Weekend 5 — Serving layer

FastAPI with Jinja2 templates, HTMX for interactivity, Tailwind + DaisyUI via CDN. Build the landing page: live generation donut (Chart.js), current carbon intensity, current Agile price for default region, "best half-hour to run your dishwasher tonight" recommendation. Add `/region/<dno>` page with localised data. Build basic JSON API at `/api/v1/...` documented with FastAPI's auto-generated OpenAPI page.

**Goal:** Visible, usable site. First impression matters.

### Weekend 6 — Polish, observability, ship

Grafana Cloud dashboard showing pipeline health (last successful ingest per source, error rate, latency). Status page (Better Stack free tier or simple page). Backups: nightly `pg_dump` to R2. Write the killer README with architecture diagram, decisions log, screenshots, live link. Submit to Hacker News "Show HN" and r/dataengineering for feedback.

**Goal:** Live, monitored, documented, public.

---

## 7. Things to watch out for

### Cost creep
Don't over-engineer. No Kafka cluster, no Spark, no Snowflake. The UK grid updates every 5-30 minutes — you don't need sub-second streaming. A scheduled Dagster job every 5 mins is functionally indistinguishable for this use case.

### The "always-on" tax
Anything 24/7 costs money. Anything scheduled is nearly free. Design so 90% is scheduled batch and only the truly time-sensitive 10% is streaming-or-equivalent.

### Rate limits and ToS
Read every API's terms. Build with caching, exponential backoff, and respect. Project getting suspended for hammering an endpoint is not a CV story.

### Data quality is the real job
This is where most engineering work happens — late-arriving data, schema drift, the April 2026 Agile discontinuity, missing half-hour periods, time zones, regional code mismatches. Plan for ~30% of effort being data quality and observability.

### Idempotency and recovery
Every job should produce the same result when re-run. No duplicates, no gaps. This is one of the top things interviewers probe for.

### Secrets and security
Environment variables, `.env.example` pattern, secrets manager. Never commit `.env`.

### Dagster memory footprint
Webserver + daemon together can chew ~600MB-1GB of RAM. The CX32 (8GB) makes life comfortable.

### Iceberg complexity
Materially more fiddly than `INSERT INTO postgres`. Schema evolution, partition specs, snapshot management, compaction. Budget extra time — maybe 2-3 weekends to feel solid.

### Don't over-engineer streaming
If you want to *demonstrate* streaming knowledge later, add a single Redpanda topic for one specific use case (e.g. price-alert events). Don't make everything streaming.

### Backups
`pg_dump` to R2 nightly. Free, easy, essential. Most portfolio projects skip this.

### Cold-start dashboards
If frontend hits Postgres directly and the VM has been idle, first query can be slow. Add basic in-memory caching in the API layer for hot queries.

### Legal / attribution
- Carbon Intensity API: CC-BY 4.0 attribution
- Elexon BMRS (V2): "Contains BMRS data © Elexon Limited copyright and database right 2026" verbatim
- Octopus: review terms for commercial use
- Add a footer with attributions — protects you and signals professionalism.

### The README is the project
Recruiters spend 90 seconds. Architecture diagram (Excalidraw or Mermaid), data flow, decisions log ("why Iceberg over Delta", "why HTMX over React"), screenshots, live demo link, setup instructions. Plan time for this — not as an afterthought. ~30% of the project's perceived value lives in the README.

### Testing is a CV signal
Most portfolio projects have zero tests. pytest with a handful of well-chosen unit and integration tests, plus `dbt test` on models, is a strong differentiator. Doesn't need to be 100% coverage.

### Have a story for "what would you do differently with budget?"
Be ready: *"With £500/month I'd add managed Kafka via Redpanda Cloud for true streaming, swap Hetzner for AWS multi-AZ, and use Snowflake for the analytical layer."* Showing you understand trade-offs is more impressive than just having built it.

### Scope creep and abandonment
The single biggest reason side projects fail. Hard MVP definition, ship V1 before adding anything.

---

## 8. CV / interview talking points

This project deliberately produces talking points across every layer of a senior data engineering interview.

| Area | What you can say |
|---|---|
| **System design** | "I split storage into a hot Postgres layer for serving and an Iceberg lakehouse for history — different access patterns, different optimisations." |
| **Streaming vs batch** | "I evaluated streaming and chose scheduled batch because the source data updates every 5-30 minutes — sub-second latency would be over-engineering." |
| **Data quality** | "Every API response is validated against pydantic schemas. Schema drift fails loudly. I have ~85% test coverage on ingestion logic and `dbt test` on every mart model." |
| **Idempotency** | "Every Dagster asset is idempotent — re-running yesterday's ingest produces the same result. I learned this the hard way after the Octopus 1 April 2026 levy change broke my upserts." |
| **Observability** | "Three layers: healthchecks.io for cron heartbeats, Sentry for errors, Grafana for pipeline metrics. I get an alert within minutes if anything stops." |
| **Cost engineering** | "Whole platform runs on £8/month. R2's zero-egress pricing was the unlock that made the lakehouse affordable." |
| **Trade-off thinking** | "I deliberately picked HTMX over React — this is a data project, and 90% of my time should be on pipelines, not frontend tooling." |
| **Domain knowledge** | "I can talk about DNO regions, settlement periods, balancing market mechanics, and why peak prices are what they are. UK energy is a sector hiring data engineers right now." |

---

## 9. Open decisions (to settle as you build)

- **Repo scaffolding** — start from a scaffolded baseline (Docker Compose, GitHub Actions, Terraform skeleton) for speed, or build from scratch for deeper learning. Both valid.
- **HTMX styling** — Tailwind + DaisyUI via CDN is the recommended path. Can be swapped later.
- **V2 priority order** — once V1 ships, decide whether forecasting (ML signal) or BMRS constraint payments (politically interesting, undercovered) goes first.

---

## 10. Quick reference — domain, repo, infra

- **Working name:** GridPulse (locked)
- **Target domain:** `gridpulse.uk`
- **Repo visibility:** public from day one (commit history is part of the CV story)
- **Hosting:** Hetzner Cloud, CX32, Helsinki or Falkenstein region
- **Object storage:** Cloudflare R2
- **Branch strategy:** `main` only, deploys to production on merge

---

## Appendix — first three things to do this weekend

1. **Register the domain.** `gridpulse.uk` via Namecheap or Porkbun. ~£12/year. Until you own it, the project doesn't feel real.
2. **Create the GitHub repo, public, with a promise-style README.** Architecture diagram, tech stack, "live demo coming soon". Forces you to articulate the why.
3. **Provision the Hetzner box.** CX32, Ubuntu 24.04, SSH key, install Docker. You've got somewhere to deploy to.

Then you're properly underway.

---

*Document compiled from the GridPulse ideation session. Last updated: April 2026.*
