# GridPulse

> Real-time UK energy intelligence platform — live grid data, electricity prices, and "when should I run the dishwasher tonight" recommendations. Built as a portfolio project to demonstrate end-to-end modern data engineering.

🚧 **Status:** under active build. Live demo at [gridpulse.uk](https://gridpulse.uk) coming soon.

---

## What it does

Ingests live UK grid generation, carbon intensity, and Octopus Agile electricity prices from public APIs every few minutes, joins them, and serves two front doors from one platform:

- **Consumer view** — when is energy cheapest tonight? Greenest? What's the best half-hour slot to charge an EV?
- **Analyst view** — live generation mix, regional carbon intensity, year-over-year trends.

## Stack at a glance

| Layer | Choice |
|---|---|
| Ingestion | Python · `httpx` · `tenacity` · `pydantic` |
| Orchestration | Dagster OSS |
| Hot store | Postgres 16 + TimescaleDB (90 days) |
| Cold lakehouse | Apache Iceberg on Cloudflare R2 |
| Transformations | dbt-core |
| Query engine (lakehouse) | DuckDB |
| API | FastAPI |
| UI | HTMX + Jinja2 + Tailwind + Chart.js |
| Infra | Hetzner CX32 · Docker Compose · Terraform · GitHub Actions |
| Monitoring | Grafana Cloud · Sentry · healthchecks.io |

**Total cost: ~£8/month.** Yes, all-in.

## Architecture

_(diagram coming once Phase 1 is shipped — see [`docs/architecture.md`](./docs/architecture.md) for the full version)_

```
Sources → Ingestion (Dagster) → ┬→ Postgres (hot, 90d) → dbt → FastAPI → HTML/JSON
                                └→ Iceberg/R2 (cold, full history) → DuckDB
```

Why dual storage? Postgres serves sub-second user queries; Iceberg is the cheap, infinite-scale lakehouse for backtesting and ML. Same data, two access patterns. See [`docs/lakehouse-design.md`](./docs/lakehouse-design.md).

## Documentation

The `docs/` folder is the design source-of-truth. Read these before suggesting architectural changes:

- [`architecture.md`](./docs/architecture.md) — 5-layer diagram + process topology
- [`data-contracts.md`](./docs/data-contracts.md) — pydantic conventions per source
- [`database-design.md`](./docs/database-design.md) — Postgres schemas, hypertables, marts, upsert SQL
- [`lakehouse-design.md`](./docs/lakehouse-design.md) — Iceberg catalog, partitioning, snapshots
- [`api-design.md`](./docs/api-design.md) — HTML + JSON endpoints, caching, rate limits
- [`infra-design.md`](./docs/infra-design.md) — Compose, Caddy, Terraform, secrets, CI/CD
- [`decisions-log.md`](./docs/decisions-log.md) — append-only "why" log
- [`PROJECT_BRIEF.md`](./docs/PROJECT_BRIEF.md) — the original ideation doc

[`IMPLEMENTATION.md`](./IMPLEMENTATION.md) — the build plan, with checkboxes per phase.
[`CLAUDE.md`](./CLAUDE.md) — binding conventions for any contributor (human or AI).

## Run locally

```bash
git clone https://github.com/naspuka/gridpulse.git
cd gridpulse
cp .env.example .env             # edit secrets
make install                     # uv venv + deps
make up                          # docker compose
make migrate                     # apply DB schema
# Open http://localhost  (Caddy)
# Open http://dagster.localhost  (admin / set in .env)
```

`make help` lists everything.

## Attributions

- Carbon intensity data from the [Carbon Intensity API](https://carbonintensity.org.uk), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Generation mix data from [NESO](https://www.neso.energy).
- Tariff data from [Octopus Energy](https://octopus.energy).

## License

MIT — see [LICENSE](./LICENSE).
