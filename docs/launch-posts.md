# Launch posts — drafts

Two posts, two audiences. Both link to the live site + the GitHub repo;
neither buries the lede. Read them out loud before posting.

---

## Show HN

**Title** (≤ 80 chars):

> Show HN: GridPulse — live UK grid carbon intensity + Agile prices on £8/mo

**Body:**

> Hi HN — I built [GridPulse](https://gridpulse.uk) as a portfolio data-engineering project: it ingests the UK's Carbon Intensity API, NESO's generation mix, and Octopus Energy's Agile tariff for all 14 DNO regions every few minutes, joins them in Postgres + dbt, archives the history into an Iceberg lakehouse on Cloudflare R2, and serves a live "when is electricity greenest/cheapest tonight?" page.
>
> Stack worth calling out: Dagster OSS for orchestration, Postgres+TimescaleDB as the hot store, PyIceberg+R2 for cold storage, DuckDB for ad-hoc lakehouse queries, FastAPI+HTMX+PicoCSS for the UI (no React — kept the JS surface tiny). Everything runs on one Hetzner ARM VM (CAX21, ~£7/mo); R2 stays inside the 10GB free tier; total ~£8/mo all-in.
>
> The interesting bits:
> - **Dual-tier storage** — Postgres for sub-second user queries, Iceberg for cheap infinite history. Nightly Dagster job archives day-grained partitions; weekly job expires old snapshots so R2 storage doesn't grow forever.
> - **DST-correct settlement periods** — UK clocks change in March/Oct, giving 46 or 50 half-hour settlement periods on those exact days. Synthetic-period unit tests cover both.
> - **Real backups** — pg_dump → R2, lifecycle rule expires after 30 days, runbook tested end-to-end before launch.
>
> Repo: <https://github.com/naspuka/gridpulse> · Decisions log: <https://github.com/naspuka/gridpulse/blob/main/docs/decisions-log.md>
>
> Happy to answer questions about any of the choices — the Iceberg-vs-Delta call, the no-Kafka decision, why HTMX over React, or the cost engineering. Feedback welcome.

**Post-submit checklist:**
- [ ] Stay on the thread for the first 2-3 hours to reply.
- [ ] Don't argue; clarify.
- [ ] If `/healthz` flatlines under HN load, add a Cloudflare cache rule for the landing page.

---

## r/dataengineering

**Title:**

> Portfolio project: real-time UK energy platform on £8/month — Dagster + Postgres + Iceberg/R2 + dbt + FastAPI

**Body:**

> Hey r/dataengineering — sharing a portfolio project I've been building over the past six weekends, in case it's useful as a reference for what a modern, small, end-to-end pipeline looks like in 2026.
>
> Live demo: <https://gridpulse.uk>
> Repo: <https://github.com/naspuka/gridpulse>
>
> **What it does:** ingests three UK energy data sources (Carbon Intensity API, NESO generation mix, Octopus Agile prices for all 14 DNOs), joins them, and shows live "best half-hour slot tonight" recommendations plus the live grid mix.
>
> **The stack I want feedback on:**
> - **Orchestration:** Dagster OSS — asset-based mental model, free, self-hosted.
> - **Storage:** dual-tier. Postgres+TimescaleDB hot (90 days, sub-second queries). Iceberg on Cloudflare R2 cold (full history, queried with DuckDB-on-Iceberg).
> - **Transformations:** dbt-core, run as a Dagster asset. Staging models per source → marts joined on settlement period.
> - **Serving:** FastAPI + Jinja2 + HTMX. No React; the entire frontend is server-rendered partials swapped on a 60s timer. Chart.js for viz.
> - **Infra:** Terraform (Hetzner + Cloudflare providers), Docker Compose, GitHub Actions for CI/CD, Caddy for TLS. One ARM Hetzner VM (~£7/mo); R2 free tier (£0); total ~£8/mo.
> - **Observability:** Grafana Cloud free tier (Grafana Agent + node + postgres exporters + Loki for container stdout), healthchecks.io for asset heartbeats, Sentry for unhandled exceptions.
>
> **Things I'd love opinions on:**
> 1. Iceberg vs Delta — I picked Iceberg for 2026 momentum + PyIceberg maturity. Anyone running PyIceberg in anger want to share scars?
> 2. dbt-core inside Dagster (vs dbt-cloud or standalone) — I like it but the wiring is a bit fiddly. Better patterns?
> 3. HTMX for the UI — defensible on a data-engineering CV, or am I just being contrarian?
>
> The repo has a decisions log explaining every non-obvious choice, an architecture diagram, and a "run locally in 60s" Make target if you want to poke at it. Roast it.

**Post-submit checklist:**
- [ ] Tag with appropriate flair.
- [ ] First reply: thank the mods for letting portfolio posts through.
- [ ] Engage with the Kafka / streaming pushback that *will* come; the no-Kafka rationale is in the decisions log.
