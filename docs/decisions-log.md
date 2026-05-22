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

## 2026-05 — Implementation reality checks

- **Server type CAX21 (ARM) instead of CX32 (Intel).** Hetzner retired CX32 in some configurations by 2026. CAX21 is the closest equivalent — 4 vCPU / 8 GB / 80 GB at ~€6.49/mo (cheaper than CX32 was, with one more vCPU). Our Docker base images (`python:3.12-slim`, `timescale/timescaledb`, `caddy:2-alpine`) are all multi-arch so ARM is a no-op for application code.
- **R2 must be enabled manually in the Cloudflare dashboard** before Terraform can create buckets — one-time clickwrap acceptance even on the Free plan. Documented in `terraform/README.md`.
- **Dagster `@asset` decorator: omit the `context` type annotation in stubs.** The runtime validator does an identity check against its own context classes and rejects valid imports under some module-resolution paths. Real assets in Phase 2 will use the typed signature with confidence; throwaway stubs aren't worth the dance.
- **Split cloud-init: bootstrap-only, app setup in post-deploy.sh.** Cloud-init failed silently three times on Hetzner — YAML parse errors abort user-data processing with no surfaced error, `users: - default` is silently overridden by Hetzner's image (`90-hetznercloud.cfg` resets the user list to `[root]`), and runcmd ordering issues lock you out before SSH is reachable for debugging. Resolution: minimal cloud-init that creates the ubuntu user (explicit definition with `templatefile()` injecting the public key) + installs `ca-certificates`/`curl` only. Everything else (Docker, ufw, fail2ban, unattended-upgrades-reboot policy) moved to `terraform/post-deploy.sh`, run interactively from the laptop after the box is up. Idempotent. Failures are visible and re-runnable. CLAUDE.md's "infra-design.md" doc still describes the unified flow — that's the aspiration; the current setup is the pragmatic reality.

## 2026-05 — Phase 2 (Carbon Intensity ingestion)

- **Regional asset is a single materialisation, not partitioned per region.** The CI API's `/regional` endpoint returns all 14 DNO regions in one response; partitioning would mean making 14 identical API calls for the same payload (rude to the upstream + slower for us). The original plan in IMPLEMENTATION.md said "partitioned by region" — superseded.
- **API revealed 18 regions, not 14.** Carbon Intensity returns 14 DNOs plus 4 rollups (England, Scotland, Wales, GB). The `to_rows()` method on the regional contract filters out the rollups (region_ids 15-18) — we get national-level data with `actual` from `/intensity` instead, and the country rollups are redundant.
- **Regional rows always have `actual_gco2_per_kwh = NULL`.** The `/regional` endpoint does not expose realised values; only `forecast` + `index`. The COALESCE in our upsert ensures a later forecast-only fetch never wipes an existing realised value (for national rows).
- **Dagster asset modules must NOT `from __future__ import annotations`.** Dagster's `_validate_context_type_hint` does an identity (`is`) check against its own context classes; deferred string annotations break it. This is the same gotcha we hit with the Phase 1B stub — now documented so it doesn't bite a third time.
- **Schedule cron: `2,32 * * * *`** (i.e. 2 minutes past each half-hour). Gives the CI API time to publish the realised `actual` for the just-completed half-hour before we re-fetch it.
- **Five extra fixtures captured per source.** Real API JSON committed under `tests/fixtures/carbon_intensity/` so contract drift surfaces as a CI failure on the next ingest. Loud > silent.

## Format for future entries

```
## YYYY-MM-DD — <topic>

- **<decision>.** <why, in one or two lines>.
```
