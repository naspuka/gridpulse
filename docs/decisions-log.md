# Decisions log

Append-only one-liners for non-trivial decisions. Each entry: date, decision, why. **Don't relitigate — supersede with a new entry.**

This file mirrors the "Decisions log" section in [CLAUDE.md](../CLAUDE.md). When the two diverge, this file is the source of truth and CLAUDE.md is updated to match.

---

## 2026-04 — Initial design lock-in

- **Iceberg over Delta.** Both fine. Iceberg has broader 2026 momentum (Snowflake, Databricks, AWS, Google all backing). PyIceberg is mature.
- **Postgres + Iceberg dual tier (not just one).** Postgres alone serves fine but doesn't show off lakehouse skills. Iceberg alone has slow user-facing queries on a small VM. Splitting tells a real architectural story.
- **Dagster over Airflow / Prefect.** Asset-based mental model is cleaner for a data platform. Lineage UI looks great in interviews. OSS is free.
- **dbt-core (not Cloud).** Free, self-hosted, runs as a Dagster asset.
- **HTMX + Jinja over React/Next.js.** Data-engineering CV piece, not a frontend one. HTMX is defensible in 2026; frees ~90% of effort for pipelines.
- **Hetzner over AWS/GCP.** Cost. CX32 ~£7/mo runs the whole stack; AWS equivalents 5–10× more once egress is counted.
- **Cloudflare R2 over S3.** Zero egress + 10 GB free tier. Killer for a lakehouse with repeated history reads.
- **No Kafka in V1.** Sources update every 5–30 min; scheduled Dagster is functionally indistinguishable.
- **Public GitHub repo from day one.** Commit history is part of the CV story.

## 2026-04 — Refinements during pre-build design

- **SQL catalog (Postgres-backed) for Iceberg.** Zero new infra; same `pg_dump` covers it; transactional safety on catalog updates.
- **Daily partitioning via `DayTransform()` for Iceberg tables.** Sweet spot of granularity vs file count. Each archival run writes exactly one new partition.
- **Partition-overwrite (not append) for archival.** Idempotent by construction; late-arriving data handled by re-running yesterday.
- **30-day snapshot retention** in Iceberg. Lengthen later if longer time-travel becomes useful.
- **Backfill bypasses Postgres** — direct API → Iceberg for 2018+ Carbon Intensity. Avoids writing 2M rows to Postgres only to delete them.
- **Plain-SQL migrations + tiny Python applier**, not Alembic. We're not using SQLAlchemy as ORM, so autogen is moot; TimescaleDB DDL plays nicer with hand-written SQL.
- **`region_id = 0` sentinel for NATIONAL** rather than nullable FKs. Uniform joins, no `IS NULL` branches.
- **Wide format in `raw.generation_mix`; pivot to long in dbt staging.** Source-shaped staging vs analyst-shaped marts — textbook dbt example.
- **Two-layer pydantic per source** (`RawXxxResponse` + `XxxRow`); `to_rows()` is the conversion. All UTC normalisation lives there.
- **`extra="forbid"` on raw pydantic models.** Loud > silent for a learning project.
- **Don't reuse contract models for API responses.** Separate `gridpulse/api/schemas.py`. Decouples wire-format changes from API consumers.
- **No auth in V1 API.** All public data; Cloudflare + 30 req/min rate limit is the abuse defence.
- **In-process TTL cache, no Redis.** Single FastAPI process; sufficient. Add Redis only if multi-worker stampedes appear.
- **14-day cap on JSON range queries.** Larger windows go through DuckDB-on-Iceberg notebooks (V1) or future lakehouse-backed endpoints (V2).
- **Chart.js over Plotly.** Lighter, faster first paint, enough features.
- **One Dockerfile, multi-stage**, two image targets (`app`, `dagster`). Single source of truth.
- **Migrations as a one-shot Compose service**, manually triggered after deploy. Auto-running destructive migrations on prod is the wrong default.
- **Build images in CI, not on the VM.** CX32 has only 2 vCPU; CI build keeps the box free for serving.
- **Dagster on `dagster.gridpulse.uk` with Caddy basic auth**, not path-prefixed. Path-prefixed Dagster has historically been buggy.
- **Apex + www proxied through Cloudflare**; `dagster.` unproxied (Caddy needs ACME HTTP-01 direct, and admin traffic shouldn't go via the edge).
- **Local Terraform state** (gitignored, R2-backup script). Solo dev, single box; remote state is yak-shaving at this scale.
- **No staging environment in V1.** Smoke-tested deploys + easy rollback over staging at this stage.
- **Plain `.env` for secrets in V1.** Doppler is a 1-evening swap if it ever becomes useful.

## Format for future entries

```
## YYYY-MM-DD — <topic>

- **<decision>.** <why, in one or two lines>.
```
