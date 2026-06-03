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

## 2026-06 — Phase 2 prod cutover lessons

- **`/opt/gridpulse/.env` is a symlink to `/etc/gridpulse/.env`** on the box. Compose's `${VAR}` interpolation reads from `.env` in the project directory; `env_file:` populates container environments at start. They are *separate mechanisms*. The symlink lets the same file feed both — without it, `POSTGRES_PASSWORD` would fall back to the literal `"changeme"` default in Compose interpolation, breaking the app even though the container's runtime env was correct.
- **`docker-compose.yml`'s `environment:` block does NOT include secrets** (SENTRY_DSN, HEALTHCHECKS_PING_KEY, R2_*, ICEBERG_CATALOG_URI). Compose's merge rule is `environment` > `env_file` — listing a secret here with a default like `${SENTRY_DSN:-}` silently wipes the prod `env_file` value. Only values needed at compose-parse time (POSTGRES_PASSWORD for the DATABASE_URL interpolation, GIT_SHA, ENVIRONMENT) remain in `environment:`.
- **Postgres prod password = `password` (explicitly weak).** User chose this against Claude's recommendation; documented here per CLAUDE.md "flag deviations explicitly". Rotate before going public on Show HN or in any interview demo. Postgres is bound to 127.0.0.1 so not internet-reachable, but a weak password is one SSH compromise away from a real problem and a bad signal in screenshots.
- **Migrations don't run on deploy.** Phase 1D's deploy.yml ships images but doesn't apply migrations — by design, per docs/infra-design.md ("one manual gate"). Currently run by `docker exec gridpulse-app python -m gridpulse.storage.migrate` post-deploy. Future: add a Make target `make migrate-prod IP=...` and document in runbooks.
- **`HEALTHCHECKS_PING_KEY` not `HEALTHCHECKS_BASE_URL`.** `.env.example` was updated in Phase 2B but the existing prod `/etc/gridpulse/.env` still had the old name; ops carried it across by hand. Future template renames need a migration step or runbook entry.

## 2026-06 — Phase 3 (NESO + Octopus + dbt)

- **NESO DATETIME is UTC, not UK-local.** The dataset's own metadata says so, and the BeforeValidator pins it. DST is therefore a display-layer concern only — every UTC day has exactly 48 half-hours. The CLAUDE.md "46/50 settlement periods" risk vanishes in UTC. Test invariant locked in `tests/unit/test_dst_invariants.py`.
- **NESO generation_mix schedule: every 30 min, not every 5 min.** NESO refreshes hourly-ish; 5-min polling would waste 11/12 requests. CLAUDE.md said "every 5 mins" — superseded.
- **Regional Agile asset: single materialisation, not partitioned per region.** One Octopus call fetches all 14 regions (via 14 sequential tariff URLs); partitioning would 14× the cron-driven API hits for the same payload. Sequential within one asset run keeps the load polite.
- **April 2026 Octopus levy claim NOT visible in the data.** Verified by querying AGILE-24-10-01 prices straddling 2026-04-01 — normal day-to-day variation, no 3.5p/kWh step. CLAUDE.md flagged this for re-verification; verified false. No `is_post_2026_levy_reform` column in marts.
- **Octopus current product is `AGILE-24-10-01`.** `AGILE-FLEX-22-11-25` (CLAUDE.md's reference) was retired in late 2024 and now serves historical only. Tariff URL pattern: `E-1R-AGILE-24-10-01-{LETTER}`.
- **Carbon Intensity API has 18 regions, not 14.** 14 DNOs + 4 rollups (England/Scotland/Wales/GB). `to_rows()` on regional response drops the rollups; we use `/intensity` (which carries `actual`) for the national value instead.
- **dbt `generate_schema_name` overridden.** Default dbt prepends `target.schema` to `+schema:`, so `+schema: staging` becomes `marts_staging`. Standard macro override at `dbt/macros/generate_schema_name.sql` makes `+schema:` the literal schema name so we land in `staging.*` and `marts.*` exactly where the migrations expect.
- **dbt 1.11: generic-test arguments must be under `arguments:`.** Top-level keys (e.g. `accepted_values.values:`) emit a deprecation warning but still work; nested under `arguments:` is the future-proof form. Migrated all `_sources.yml`, `_staging.yml`, `_marts.yml`.
- **Dropped `dbt_utils.equal_rowcount` sanity test.** The macro returns `None` (not `0`) for the failures count when both tables are empty, which trips dbt's JSON schema validation BEFORE `severity: warn` can fire. Re-add as a singular test guarded on row counts in V2 if we want the 11-fuel pivot sanity check back.
- **Sentry caught a real prod failure.** `DagsterInvalidDefinitionError: Op/Graph definition names must be unique within a repository` (asset and job both named `dbt_build`). Renamed job to `transform`. First real-world fire of the Phase 2 observability stack — worked as designed.
- **Single Dagster asset for dbt, not `dagster-dbt` per-model graph.** 5 models doesn't justify the UI noise. The dbt asset shells out to `dbt deps && dbt build` and dbt drives the model DAG. Re-evaluate at >20 models.

## 2026-06 — Phase 4 (Iceberg lakehouse)

- **Dual-storage interview soundbite — for real.** *"Postgres + TimescaleDB on a £7/month box for the last 90 days of half-hourly data — sub-second user queries. Iceberg tables on Cloudflare R2 for the full history — same schema, queried with PyIceberg or DuckDB. A Dagster asset partition-overwrites yesterday's rows from Postgres to Iceberg every night at 02:00 UTC. The catalog lives in the same Postgres so it's covered by the same backups. R2's zero-egress pricing is the unlock that makes the lakehouse affordable on this budget."* Now backed by working code in prod (`f00c87e` → `ba557e0` chain).
- **`TimestamptzType` not `TimestampType` for Iceberg timestamp columns.** Postgres TIMESTAMPTZ returns tz-aware Python datetimes; Arrow infers `timestamp[us, tz=UTC]`; Iceberg `TimestampType` (no tz) refuses it. `TimestamptzType` matches the actual data semantically (all our values are UTC-bearing) and resolves the impedance mismatch.
- **Build Arrow schema from Iceberg schema at write time.** `pa.Table.from_pylist(rows)` infers int64 for Python ints (Iceberg expects int32 for `IntegerType`) and marks every column nullable (Iceberg expects required=True for NOT NULL). The fix is `schema=schema_to_pyarrow(table.schema())` on every write call — single source of truth, no drift.
- **`init_catalog_tables` must be the literal string `"true"`.** PyIceberg's `strtobool` calls `.lower()` on the value, so passing a Python bool throws AttributeError at SqlCatalog construction time. Subtle, but caught early on the first prod boot.
- **DuckDB Iceberg extension limitation: `Unimplemented type for cast (DATE -> INTEGER)`.** Reading our manifest avro files via `iceberg_scan(...)` errors out on the DayTransform partition metadata. Documented in `scripts/query_lake.py` — the script still works for tables WITHOUT day-partitioning, and PyIceberg's native `table.scan().to_arrow()` is the working ad-hoc tool for now. Watch DuckDB 1.2+ for the fix.
- **Partition overwrite, not append, for nightly archival.** Idempotent by construction: re-running the same date rewrites the partition rather than duplicating. Late-arriving rows handled by the 2-day rolling window. No PKs in Iceberg, so this discipline is what keeps the lake consistent.
- **Backfill bypasses Postgres entirely.** 2018-onwards Carbon Intensity is ~2M rows; Postgres only retains 90 days. Funnelling all of history through Postgres just to delete most of it is wasteful and risks blowing the hypertable cache. The `scripts/backfill_carbon_intensity.py` script appends directly to Iceberg.
- **Three jobs, three job names that don't collide with assets.** Same Phase 3C gotcha applies — `archive_to_iceberg` (asset) needs a different job name (`archive`); `expire_snapshots` (asset) gets `snapshot_gc`.

## Format for future entries

```
## YYYY-MM-DD — <topic>

- **<decision>.** <why, in one or two lines>.
```
