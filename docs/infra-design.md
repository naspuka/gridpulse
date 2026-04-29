# Infrastructure design

Local dev, cloud infra, secrets, CI/CD. Engineered so dev and prod are as similar as possible — "works on my machine" is what we're protecting against.

## Runtime topology

Single Hetzner CX32, Ubuntu 24.04 LTS, Docker. **No Python or Node on the host** — host is just Docker + ssh + ufw. Reproducible from `terraform apply` + a `docker compose up` in minutes.

See [architecture.md](./architecture.md) for the container-level diagram.

## Docker Compose

One `docker-compose.yml` for the runtime spec; small `docker-compose.prod.yml` overlay for prod-only tweaks.

### Services

| Service | Image | Notes |
|---|---|---|
| `postgres` | `timescale/timescaledb:2.15.0-pg16` | Bound to `127.0.0.1:5432` even in prod. Volume: `pgdata`. |
| `app` | custom (`app` target) | FastAPI, port 8000, expose only. |
| `dagster-webserver` | custom (`dagster` target) | Dagster UI :3000, expose only. Behind Caddy basic auth. |
| `dagster-daemon` | custom (`dagster` target) | Schedules + sensors. |
| `caddy` | `caddy:2-alpine` | Only container with public ports (80, 443). |
| `migrate` | custom (`app` target), one-shot | Runs `python -m gridpulse.storage.migrate` and exits. |
| `grafana-agent` | `grafana/agent:latest` | Ships logs + Postgres metrics to Grafana Cloud. |

### Why these shapes

- **One Dockerfile, multi-stage.** `base` → `app` and `dagster` targets share a Python 3.12 + uv + `gridpulse` package base. Two final images, one source of truth.
- **Two Dagster containers** (web + daemon) sharing `DAGSTER_HOME` via named volume. Standard topology.
- **`expose:` for internal services, `ports:` only for `caddy`.** Internal services aren't reachable from the public internet — the key boundary.
- **Postgres bound to `127.0.0.1:5432`.** SSH-tunnel from your laptop for ad-hoc psql; never internet-reachable.
- **`pgdata` is a named volume**, not a bind mount. Survives `docker compose down` (not `down -v`). Backups via `pg_dump` → R2, not by copying volumes.
- **Migrations as a one-shot service**, not auto-run on container start. `docker compose run --rm migrate` after deploy. **One manual gate** — destructive migrations auto-running on prod is exactly the wrong default.
- **`restart: unless-stopped`** on long-running services. Survives reboots; doesn't loop on permanent failures.

## Caddyfile

Only TLS / auth surface in the system.

```caddyfile
gridpulse.uk, www.gridpulse.uk {
    encode gzip zstd
    reverse_proxy app:8000
    header /static/* Cache-Control "public, max-age=86400, immutable"
}

dagster.gridpulse.uk {
    basicauth {
        admin {env.DAGSTER_BASIC_AUTH_HASH}
    }
    reverse_proxy dagster-webserver:3000
}
```

Subdomain (not path-prefix) for Dagster: Dagster's UI assumes it owns the URL root; path-prefixed deployments have historically been buggy.

`dagster.gridpulse.uk` is **not Cloudflare-proxied** — Caddy needs to complete the ACME HTTP-01 challenge directly, and we don't want admin traffic going through Cloudflare's edge. Apex + www are proxied (cache, DDoS, WAF).

## Terraform

Three providers: **hcloud** (Hetzner), **cloudflare** (DNS + R2). Manual `terraform apply` from a laptop, not CI.

```
terraform/
├── main.tf                 # provider blocks, version pins
├── variables.tf
├── terraform.tfvars.example
├── hetzner.tf              # ssh key, firewall, server
├── cloudflare.tf           # zone, A records, R2 bucket, R2 token
├── cloud-init.yml          # the only thing that runs on the host
└── outputs.tf
```

### Hetzner

- SSH key resource
- CX32 in `nbg1` (Nuremberg) or `fsn1` (Falkenstein)
- Firewall: 22 from admin CIDR; 80/443 world; outbound unrestricted
- `cloud-init.yml` installs Docker, ufw, fail2ban, unattended-upgrades. Nothing app-specific.

### Cloudflare

- A records: `@` and `www` (proxied), `dagster` (unproxied)
- R2 bucket `gridpulse-lake` (location `WEUR`)
- R2 API token, scoped to the bucket only

### State

Local state file, **gitignored**, manually backed up to R2 with a tiny script. Solo dev, single box: remote state is yak-shaving for ~zero benefit at this scale. Move to remote when multi-developer.

## Secrets

| Environment | Mechanism | Why |
|---|---|---|
| Local dev | `.env` (gitignored) + `.env.example` (committed) | Standard pattern |
| GitHub Actions | Repository encrypted secrets | Native; injected as workflow env |
| Production (Hetzner) | `/etc/gridpulse/.env`, root-owned, `chmod 600`, loaded via Compose `env_file:` | Survives container restarts; not in image |

Deploy flow: CI builds images, pushes to GHCR, SSHes to box, `docker compose pull && up`. The prod `.env` is **not touched by CI** — set once by hand on first provision, rotated by hand. Standard "secrets are infrastructure, not artefacts" pattern.

### `.env` contents

```bash
POSTGRES_PASSWORD=

# Cloudflare R2
R2_ENDPOINT=https://<account>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=gridpulse-lake

# Iceberg catalog
ICEBERG_CATALOG_URI=postgresql://gridpulse:<pw>@postgres:5432/gridpulse

# External APIs
NESO_API_TOKEN=
# Carbon Intensity & Octopus need no auth

# Observability
SENTRY_DSN=
HEALTHCHECKS_BASE_URL=https://hc-ping.com/<uuid>
GRAFANA_CLOUD_API_KEY=

# Caddy
DAGSTER_BASIC_AUTH_HASH=             # bcrypt; `caddy hash-password`
```

### `.gitignore` essentials

```
.env
*.tfvars
!*.tfvars.example
.terraform/
terraform.tfstate*
.venv/
__pycache__/
.dagster_home/
*.duckdb
.DS_Store
```

## CI/CD

Two workflows. Public repo → free.

### `ci.yml` — every push, every PR

- **`python` job:** Postgres service container, `uv sync`, ruff lint+format, mypy, `python -m gridpulse.storage.migrate`, `pytest`, `dbt build` (deps + run + test).
- **`smoke` job:** boots Compose, hits `/healthz`, uploads logs on failure.

`dbt build` in CI runs models against ephemeral Postgres + tests them. Schema regressions caught pre-merge.

### `deploy.yml` — push to `main` only

- **`build-and-push`:** docker buildx → GHCR, both `app` and `dagster` images, tagged with git SHA + `latest`.
- **`deploy`:** SSH-agent, rsync compose files + Caddyfile to `/opt/gridpulse/` on the box, `docker compose pull && up -d --remove-orphans`, prune images.
- **Smoke prod:** `curl https://gridpulse.uk/healthz` after deploy.

### Why this shape

- CI runs everywhere; deploy only on `main`. Same code path proves itself in CI before shipping.
- **Images built in CI, not on the VM.** CX32 has 2 vCPU; building on it would compete with running services.
- **Tag with git SHA**, not just `latest`. Rollback = `GIT_SHA=<old> docker compose up -d`.
- **`rsync` compose files**, not `git pull`. Box doesn't need to know it's a git repo.
- Post-deploy smoke against the **public URL** catches Caddy/Cloudflare misconfigs that wouldn't surface inside the box.

### Not in V1

- **No staging environment.** Single box, smoke-tested deploys, easy rollback. Trade-off acknowledged.
- **No automatic Terraform applies.** Manual + reviewed.
- **No automatic migrations on deploy.** Manual `docker compose run --rm migrate` after deploy. One gate.

## Backups

```bash
# scripts/pg_dump_to_r2.sh — runs nightly via Dagster asset (not host cron)
set -euo pipefail
DATE=$(date -u +%Y-%m-%d)
docker exec postgres pg_dump -U gridpulse -Fc gridpulse \
  | rclone rcat r2:gridpulse-backups/postgres/$DATE.dump
```

Triggered as a **Dagster asset** so it shares observability — success → healthchecks ping; failure → Sentry.

Retention: 30 daily + 12 monthly via R2 lifecycle rules in Terraform.

**Restore drill** mandatory before launch (Phase 6). Restore latest backup to a fresh container, verify counts. Document in `docs/runbooks/restore.md`. Most projects skip this; doing it is a CV signal.

## Observability — three systems, three jobs

| System | Job |
|---|---|
| **healthchecks.io** | Cron heartbeats per Dagster asset. Misses → email. *"Cron didn't run"* detector. |
| **Sentry** | Uncaught exceptions in app + ingestion + Dagster. Real-time. *"Something exploded"* detector. |
| **Grafana Cloud** | Postgres-source dashboards: row counts, last-ingest timestamps, error rates. *"Trends"* surface. |

Wired via `grafana-agent` Compose service, scraping Postgres + container logs.

The detail that matters most: healthchecks pings happen inside a Dagster `@with_heartbeat` decorator, so adding a new ingestion asset auto-registers a heartbeat. No per-asset boilerplate.

## Resource sizing on CX32

| Component | RAM | Reasoning |
|---|---|---|
| Postgres + Timescale | ~2 GB | `shared_buffers=1GB`, OS buffers, query workspace |
| Dagster webserver | ~400 MB | Default footprint |
| Dagster daemon | ~400 MB | Plus per-run overhead |
| FastAPI (uvicorn 2 workers) | ~300 MB | |
| Caddy | ~50 MB | |
| Grafana Agent | ~150 MB | |
| OS + headroom | ~3 GB | OS, Docker daemon, log buffers |

~4 GB used, ~4 GB free. Comfortable. CX21 (4 GB) would be tight; CLAUDE.md's call to use CX32 is right.

Disk: 80 GB easily covers Postgres (<100 MB), Docker images (~3 GB), logs, local Iceberg metadata cache. Backups go to R2.

## Local dev workflow

`git clone && cp .env.example .env && docker compose up` should work first try. That's the README's onboarding test.

Day-to-day, two terminals:

```bash
# Terminal 1: long-running services
docker compose up postgres dagster-webserver dagster-daemon

# Terminal 2: hot-reload Python in a venv
source .venv/bin/activate
uvicorn gridpulse.api.main:app --reload --port 8000
# OR
pytest -xvs tests/unit/...
```

Postgres + Dagster live in containers; Python code runs in a venv against them. Edit → save → reload. Containers don't rebuild during a coding session.

A `Makefile` codifies the common commands:

```makefile
up:        ; docker compose up -d
down:      ; docker compose down
test:      ; uv run pytest -v
fmt:       ; uv run ruff format . && uv run ruff check --fix .
migrate:   ; uv run python -m gridpulse.storage.migrate
psql:      ; docker compose exec postgres psql -U gridpulse
logs:      ; docker compose logs -f --tail=100
deploy-check: ; docker compose -f docker-compose.yml -f docker-compose.prod.yml config
```

## Deliberately not doing

- Kubernetes (a 2-vCPU box doesn't need it)
- Autoscaling (workload bounded by API cadences)
- Service mesh (three services on one Docker network)
- Self-hosted log aggregation (Grafana Cloud Loki free tier is enough)
- Staging / canary / blue-green (CI/CD discipline > infra topology at this scale)
