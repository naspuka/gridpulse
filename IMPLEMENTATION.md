# GridPulse — Implementation Plan

Living checklist of work to ship V1. Each phase has a **goal**, a **task list**, and a **definition of done (DoD)** — don't move to the next phase until DoD is green.

Phases roughly map to weekends (Phase 1–6) plus a Phase 0 for design artifacts already produced in conversation.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 0 — Design lock-in

**Goal:** Capture every design decision in this repo so future-me (and Claude) can pick up cold.

- [x] 0.1  Commit `CLAUDE.md` (already authored) at repo root
- [x] 0.2  Commit project brief as `docs/PROJECT_BRIEF.md`
- [x] 0.3  Write `docs/architecture.md` — the 5-layer diagram + process topology
- [x] 0.4  Write `docs/data-contracts.md` — pydantic model conventions, raw vs row split
- [x] 0.5  Write `docs/database-design.md` — schemas, tables, indexes, hypertable + retention policy, upsert SQL
- [x] 0.6  Write `docs/lakehouse-design.md` — Iceberg catalog, partition spec, overwrite semantics, snapshot policy
- [x] 0.7  Write `docs/api-design.md` — endpoint inventory, HTML/JSON split, caching, rate limiting
- [x] 0.8  Write `docs/infra-design.md` — Compose graph, Caddy/Cloudflare, Terraform, secrets, CI/CD
- [x] 0.9  Write `docs/decisions-log.md` — append-only one-liners; mirror the section in CLAUDE.md
- [x] 0.10 Initial commit + push to public GitHub repo

**DoD:** Repo cloneable; a stranger can read the docs and explain the architecture.

---

## Phase 1 — Foundations (Weekend 1)

**Goal:** Push to `main` → something visible happens. The runway built.

### 1A. Repo scaffolding
- [x] 1.1  `pyproject.toml` with `uv`, Python 3.12, deps grouped (`ingestion`, `api`, `dev`)
- [x] 1.2  `.gitignore`, `.env.example`, `Makefile` (or `justfile`)
- [x] 1.3  Package skeleton: `gridpulse/{contracts,ingestion,storage,dagster_defs,api,lib}/__init__.py`
- [x] 1.4  `tests/{unit,integration,fixtures}/` with one trivial passing test
- [x] 1.5  `ruff` + `mypy` config; pre-commit hook
- [x] 1.6  README skeleton (architecture diagram placeholder, "live demo coming soon")

### 1B. Local Docker Compose stack
- [x] 1.7  Multi-stage `Dockerfile` (`base` → `app` and `dagster` targets)
- [x] 1.8  `docker-compose.yml` — postgres, app, dagster-webserver, dagster-daemon, caddy
- [x] 1.9  `Caddyfile` (local: HTTP only; prod overlay handles TLS)
- [x] 1.10 `gridpulse/storage/migrate.py` migrator + `001_extensions_and_schemas.sql`
- [x] 1.11 Stub FastAPI app with `/healthz` returning `{"status":"ok"}`
- [x] 1.12 Stub Dagster `Definitions()` (one no-op asset) so daemon boots clean

### 1C. Cloud infra via Terraform
- [x] 1.13 `terraform/` skeleton with hcloud + cloudflare providers pinned
- [x] 1.14 SSH key resource; CAX21 server in `nbg1` (CX32 retired in 2026)
- [x] 1.15 Hetzner firewall (22 from admin CIDR; 80/443 world)
- [x] 1.16 `cloud-init.yml.tpl` — minimal (ubuntu user via templatefile) + `post-deploy.sh` for Docker/ufw/fail2ban
- [x] 1.17 Cloudflare A records: apex (proxied), www (proxied), `dagster.` (unproxied)
- [x] 1.18 R2 bucket `gridpulse-lake` (S3 keys created manually via dashboard)
- [x] 1.19 `terraform apply` → box reachable on its IP, post-deploy.sh installs the stack

### 1D. CI/CD
- [x] 1.20 `.github/workflows/ci.yml` — lint, type-check, pytest, compose smoke test
- [x] 1.21 `.github/workflows/deploy.yml` — build → GHCR → SSH → compose up
- [x] 1.22 GitHub repo secrets: `DEPLOY_HOST`, `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`
- [x] 1.23 Hand-create `/etc/gridpulse/.env` on the box (chmod 640, root:ubuntu)
- [x] 1.24 First green deploy — `https://gridpulse.uk/healthz` returns 200

**DoD:** Push to `main` → CI green → auto-deploy → `curl https://gridpulse.uk/healthz` returns `{"status":"ok"}`. Caddy auto-issued the cert. `dagster.gridpulse.uk` prompts basic auth.

---

## Phase 2 — First ingestion end-to-end (Weekend 2)

**Goal:** Cron-driven Carbon Intensity pipeline runs autonomously; we know within minutes if it breaks.

- [x] 2.1  `gridpulse/contracts/carbon_intensity.py` — `RawResponse` + `Row` models
- [x] 2.2  `tests/fixtures/carbon_intensity_*.json` — captured real responses
- [x] 2.3  Unit tests: fixtures parse cleanly through pydantic models
- [x] 2.4  `gridpulse/ingestion/http.py` — shared `httpx` client + tenacity retry policy
- [x] 2.5  `gridpulse/ingestion/carbon_intensity.py` — fetch → validate → return `list[Row]`
- [x] 2.6  Migration `002_ref_dno_region.sql` + `003_seed_dno_region.sql`
- [x] 2.7  Migration `004_raw_carbon_intensity.sql` (hypertable, retention, PK upsert)
- [x] 2.8  `gridpulse/storage/postgres.py` — connection pool + upsert helper
- [x] 2.9  Dagster asset `carbon_intensity_national` — schedule every 30 min
- [x] 2.10 Dagster asset `carbon_intensity_regional` — single asset (not per-region), every 30 min
- [ ] 2.11 Healthchecks.io project + per-asset heartbeat URLs
- [ ] 2.12 `@with_heartbeat` decorator on Dagster ops
- [ ] 2.13 Sentry SDK init in app + Dagster code
- [ ] 2.14 Integration test: throwaway Postgres + asset run → row count > 0
- [ ] 2.15 Deploy; verify two consecutive successful schedules in Dagster UI

**DoD:** Asset has run successfully ≥ 4 times in a row without intervention. `raw.carbon_intensity` has fresh data. Healthchecks.io shows green; Sentry has zero errors.

---

## Phase 3 — Broaden ingestion + dbt (Weekend 3)

**Goal:** All three V1 sources flowing in; dbt produces clean tested marts.

### 3A. NESO + Octopus ingestion
- [ ] 3.1  `gridpulse/contracts/neso.py` (with UK-local → UTC conversion in `to_rows()`)
- [ ] 3.2  `gridpulse/contracts/octopus.py`
- [ ] 3.3  Ingestion modules + tests + fixtures for both sources
- [ ] 3.4  Migrations `005_raw_generation_mix.sql`, `006_raw_agile_price.sql`
- [ ] 3.5  Dagster assets: `generation_mix` (every 5 min), `agile_price` (daily 16:30 UK, 14 regions)
- [ ] 3.6  DST/synthetic-period test: parse a 50-period day correctly

### 3B. dbt-core
- [ ] 3.7  `dbt/dbt_project.yml`, `profiles.yml.example`, `packages.yml` (dbt_utils)
- [ ] 3.8  Sources YAML pointing at `raw.*`
- [ ] 3.9  Staging models: `stg_carbon_intensity`, `stg_generation_mix` (wide→long), `stg_agile_price`
- [ ] 3.10 Mart models: `mart_half_hourly`, `mart_generation_mix_long`, `mart_best_slots_24h`
- [ ] 3.11 `schema.yml` — not-null, unique, accepted-values tests on every mart
- [ ] 3.12 Wire `dbt build` as a Dagster asset downstream of all ingestion assets
- [ ] 3.13 CI runs `dbt build` against ephemeral Postgres

**DoD:** All three sources fresh in `raw.*`. `dbt build` passes locally and in CI. `marts.mart_best_slots_24h` returns sensible rows for at least 3 regions.

---

## Phase 4 — Iceberg lakehouse (Weekend 4)

**Goal:** Cold storage live; can articulate why both layers exist.

- [ ] 4.1  `gridpulse/storage/iceberg.py` — SQL catalog (Postgres-backed) + R2 config
- [ ] 4.2  Schema definitions for 3 Iceberg tables matching `raw.*` shapes
- [ ] 4.3  Partition spec: `DayTransform(period_start_utc)` on all three
- [ ] 4.4  One-shot `init_iceberg_tables.py` script — creates tables in catalog
- [ ] 4.5  Dagster asset `archive_to_iceberg` — daily 02:00 UTC, partition-overwrite yesterday
- [ ] 4.6  `expire_snapshots` weekly Dagster asset (>30 days)
- [ ] 4.7  Backfill asset: Carbon Intensity 2018→ direct to Iceberg (skips Postgres)
- [ ] 4.8  DuckDB-on-Iceberg quick-query script `scripts/query_lake.py`
- [ ] 4.9  Verify time travel: query an older snapshot id
- [ ] 4.10 Document the dual-storage interview soundbite in `docs/decisions-log.md`

**DoD:** Iceberg holds ≥ 1 day of fresh data + multi-year backfill of Carbon Intensity. DuckDB queries return correct results in under 2 seconds. Re-running yesterday's archival is idempotent (snapshot count grows by 1, row count unchanged).

---

## Phase 5 — Serving layer (Weekend 5)

**Goal:** Visible, usable site.

### 5A. FastAPI scaffolding
- [ ] 5.1  `gridpulse/api/main.py` — app factory, middleware (Sentry, rate limit, cache headers)
- [ ] 5.2  `gridpulse/api/queries.py` — single source of read SQL (used by HTML and JSON)
- [ ] 5.3  `gridpulse/api/schemas.py` — pydantic response models
- [ ] 5.4  In-process TTL cache wrapper (30 s for "current" queries)
- [ ] 5.5  `slowapi` rate limiter, 30/min on `/api/v1/*`

### 5B. JSON API
- [ ] 5.6  `/api/v1/regions`
- [ ] 5.7  `/api/v1/carbon-intensity/{current,range}`
- [ ] 5.8  `/api/v1/agile-price/{current,range}`
- [ ] 5.9  `/api/v1/generation-mix/current`
- [ ] 5.10 `/api/v1/best-slots`
- [ ] 5.11 OpenAPI page reachable at `/docs`; sample curls in README

### 5C. HTML / HTMX
- [ ] 5.12 `templates/base.html` (header, footer with attribution, Tailwind/HTMX/Chart.js CDN)
- [ ] 5.13 `templates/landing.html` + partials: current_conditions, best_slots, generation_donut, carbon_trend
- [ ] 5.14 `templates/region.html` + slug routing + 404 for unknown slugs
- [ ] 5.15 HTMX polling on each card (`hx-trigger="every 60s"`)
- [ ] 5.16 Region picker (HTMX swap, `hx-push-url="true"`)
- [ ] 5.17 `/status` page — last-ingest per source, Postgres reachability

### 5D. Polish
- [ ] 5.18 `templates/404.html`, `templates/500.html`
- [ ] 5.19 Mobile-pass: layout doesn't break under 600 px
- [ ] 5.20 Browser smoke: page loads under 500 ms TTI on a cold cache

**DoD:** `gridpulse.uk` shows live data on landing + ≥ 3 regional pages. JSON API reachable, documented, rate-limited. Status page accurate.

---

## Phase 6 — Polish, observability, ship (Weekend 6)

**Goal:** Live, monitored, documented, public.

### 6A. Observability
- [ ] 6.1  Grafana Cloud account; Grafana Agent service in Compose
- [ ] 6.2  Dashboard: last successful ingest per source, ingest latency, row counts, error rate
- [ ] 6.3  Container logs → Loki (free tier)
- [ ] 6.4  Alert rule: any source > 2× expected interval since last ingest
- [ ] 6.5  Sentry release tracking (tag releases with git SHA)

### 6B. Backups + disaster drill
- [ ] 6.6  `pg_dump` Dagster asset, nightly → R2
- [ ] 6.7  R2 lifecycle: 30 daily + 12 monthly
- [ ] 6.8  **Restore drill** — restore latest backup to a fresh container, verify counts
- [ ] 6.9  Document drill in `docs/runbooks/restore.md`

### 6C. README + launch
- [ ] 6.10 Architecture diagram (Excalidraw or Mermaid) embedded in README
- [ ] 6.11 Decisions log (curated subset, linked from README)
- [ ] 6.12 Screenshots of landing + regional + status + Dagster UI
- [ ] 6.13 "Run locally in 60 seconds" section
- [ ] 6.14 Live link, attribution footer, license (MIT or Apache-2.0)
- [ ] 6.15 Show HN + r/dataengineering posts drafted

### 6D. Final hardening
- [ ] 6.16 Re-read every API's ToS; confirm attributions are correct
- [ ] 6.17 Verify Octopus April 2026 levy claim against current docs (CLAUDE.md flagged)
- [ ] 6.18 Load-test: 100 RPS to `/api/v1/best-slots` for 60 s; p99 < 500 ms

**DoD:** Live on the public internet, monitored, backed up, documented. Restore drill passed. Posted publicly.

---

## Cross-cutting work (rolling, not phase-specific)

- [ ] X.1  `docs/decisions-log.md` updated whenever a non-trivial decision is made
- [ ] X.2  `tests/fixtures/` refreshed any time an API response shape changes
- [ ] X.3  Dependencies bumped via Renovate/Dependabot once basic stack is stable
- [ ] X.4  CLAUDE.md kept in sync with reality (especially conventions section)

---

## V2 backlog (deliberately out of V1 — do not pull in)

- Elexon BMRS (balancing market, constraint payments)
- Met Office weather correlation
- Price forecasting (Prophet / lightgbm)
- Battery arbitrage backtester
- Public-facing API beyond V1 basics
- Smart meter integration
- Carbon-aware scheduling agent
- Push notifications / price alerts (justifies a single Redpanda topic — the streaming demo)
- Staging environment, blue/green deploys
- Continuous compaction job for Iceberg

---

## How to use this file

1. We work through phases in order. **Don't start Phase N+1 until Phase N's DoD is green.**
2. Before each task: re-read the relevant `docs/*.md` so we're not relitigating decisions.
3. After each non-trivial decision: append a one-liner to `docs/decisions-log.md`.
4. Tick checkboxes in this file as we complete tasks. Commits referencing task IDs are encouraged (`feat(2.5): carbon intensity ingestion module`).
