# Architecture

Five-layer design. Every layer earns its place by either solving a real problem at this scale or demonstrating a capability that would matter at a bigger scale.

```
┌─────────────────────────────────────────────────────────────────┐
│ SOURCES                                                         │
│ Carbon Intensity API · NESO Portal · Octopus Agile · BMRS (V2)  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ INGESTION + ORCHESTRATION                                       │
│ Dagster assets · httpx · tenacity · pydantic                    │
│ Idempotent · retried · observed                                 │
└────────────────┬───────────────────────────┬────────────────────┘
                 │                           │
┌────────────────▼─────────────┐   ┌─────────▼──────────────────┐
│ HOT STORE                    │   │ COLD LAKEHOUSE             │
│ Postgres 16 + TimescaleDB    │◀──│ Apache Iceberg on R2       │
│ Last 90 days                 │   │ Full history (2018+)       │
│ Sub-second queries           │   │ PyIceberg + Parquet        │
│ Hypertables, retention       │   │ Free egress, queryable     │
└────────────────┬─────────────┘   └─────────┬──────────────────┘
                 │                           │
┌────────────────▼───────────────────────────▼───────────────────┐
│ TRANSFORMATION                                                 │
│ dbt-core · staging → marts · tests · docs                      │
│ Postgres adapter (hot) · DuckDB-on-Iceberg adapter (cold, V2)  │
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│ SERVING                                                        │
│ FastAPI + Jinja2 + HTMX (server-rendered UI)                   │
│ Public JSON API (documented, rate-limited, cached)             │
│ Tailwind/DaisyUI via CDN · Chart.js for visuals                │
└────────────────────────────────────────────────────────────────┘

INFRA: Hetzner CX32 · Docker Compose · Terraform · GitHub Actions
       Grafana Cloud · Sentry · healthchecks.io · Cloudflare R2
```

---

## Process topology (what runs where)

Single Hetzner CX32 (2 vCPU, 8 GB RAM, Ubuntu 24.04). Everything in containers via Docker Compose. The host is just Docker + ssh + ufw — no Python, no Node.

```
                          Cloudflare (DNS, edge cache, WAF)
                                       │
                                       ▼
                          Hetzner CX32 — public IP
                          ufw allows :22 (admin CIDR), :80, :443
                          ┌──────────────────────────────────────┐
                          │ Docker Engine                        │
                          │ ┌─────────┐                          │
                          │ │ caddy   │  TLS, reverse proxy      │
                          │ └────┬────┘                          │
                          │      │                               │
                          │ ┌────▼─────────┐  ┌────────────────┐ │
                          │ │ fastapi      │  │ dagster-web    │ │
                          │ │ :8000        │  │ :3000          │ │
                          │ └────┬─────────┘  └───────┬────────┘ │
                          │      │ read-only          │          │
                          │      ▼                    │          │
                          │ ┌──────────────────┐ ┌────▼───────┐  │
                          │ │ postgres+        │ │dagster-    │  │
                          │ │ timescale :5432  │◀│daemon      │  │
                          │ └──────────────────┘ └────────────┘  │
                          └──────────────────────────────────────┘
                                       │
                                       ▼
                              Cloudflare R2 (Iceberg)
                              healthchecks.io · Sentry · Grafana Cloud
```

### Containers

| Container | Image | Role |
|---|---|---|
| `caddy` | `caddy:2-alpine` | Reverse proxy, TLS termination (Let's Encrypt). Only container with public ports. |
| `app` | custom (multi-stage `app` target) | FastAPI on uvicorn, port 8000. Read-only against Postgres. |
| `dagster-webserver` | custom (`dagster` target) | Dagster UI on port 3000. Behind Caddy basic auth at `dagster.gridpulse.uk`. |
| `dagster-daemon` | custom (`dagster` target) | Runs schedules and sensors. The actual ingestion happens here. |
| `postgres` | `timescale/timescaledb:2.15.0-pg16` | Hot store + Iceberg SQL catalog. Bound to `127.0.0.1:5432`. |
| `grafana-agent` | `grafana/agent:latest` | Ships logs and Postgres metrics to Grafana Cloud. |

---

## Data flow boundaries

### Retries — three concentric layers

| Layer | Tool | Behaviour |
|---|---|---|
| HTTP call | `tenacity` | 3× expo backoff per request |
| Asset run | Dagster | 1× retry on uncaught exception |
| Schedule | Dagster daemon | Next scheduled tick fires regardless |

This is intentional. Bottom layer absorbs flakiness; middle layer absorbs transient programming/logic blips; top layer guarantees we recover on the next cycle without manual intervention.

### Writes — single source of truth

- **Only Dagster assets write** to Postgres `raw.*`.
- **Only dbt writes** to `staging.*` and `marts.*`.
- **FastAPI is strictly read-only** against `marts.*`. No write endpoints, ever. If a future feature needs a write, it's a Dagster sensor + asset, not an HTTP handler.

### Archival — the dual-storage hand-off

Nightly Dagster asset reads yesterday's `raw.*` rows and partition-overwrites the matching date in Iceberg. Re-runs are safe (overwrite, not append). See [lakehouse-design.md](./lakehouse-design.md).

---

## Failure model

| Failure | Detection | Recovery |
|---|---|---|
| Source API 5xx | tenacity retries 3× | Usually transparent |
| Source API down >10 min | Dagster asset fails after retries → Sentry | Next schedule retries |
| Schema drift | pydantic ValidationError → Sentry | Manual: update contract + fixture, redeploy |
| Cron didn't fire (Dagster down) | healthchecks.io grace period expires → email | Restart container; investigate logs |
| Postgres down | FastAPI 503; Dagster asset failures; healthchecks misses | Restart; restore from R2 backup if data damaged |
| Iceberg archival fails | Sentry; serving unaffected | Re-run partition next day |
| Caddy/TLS broken | Public 502; UptimeRobot ping fails | Caddy autorestores certs; check logs |

The serving layer is decoupled from ingestion. If Carbon Intensity is down for a day, the dashboard shows yesterday's data with a "last updated" timestamp — not a 500.

---

## Why each component (the interview answers, condensed)

- **Dagster (OSS)** — asset model produces lineage graphs that look great in interviews; OSS is free; recruiters can't tell from code.
- **Postgres + TimescaleDB** — production-grade for time-series at this scale; many UK utilities use exactly this.
- **Iceberg on R2** — Iceberg has 2026 momentum (Snowflake, Databricks, AWS, Google all backing); R2's free 10 GB + zero egress is what makes a lakehouse affordable on £8/month.
- **dbt-core** — industry standard; tests + docs come for free; demonstrates staging→marts discipline.
- **FastAPI + HTMX + Jinja** — backend-focused, defensible in 2026; lets ~90% of effort go to pipelines.
- **Hetzner over AWS/GCP** — £4–7/month for a real VM; AWS equivalents 5–10× more once egress is counted.

The senior-level soundbite from CLAUDE.md:

> *"I split storage into a hot Postgres layer for serving and an Iceberg lakehouse for history — different access patterns, different optimisations. Postgres holds 90 days for sub-second queries. Iceberg holds the full history for backtesting and ML training. A nightly Dagster job archives Postgres → Iceberg. It's a hot/cold tiering pattern that mirrors what you'd find at any production data platform."*

---

## What's deliberately *not* in the architecture

| Excluded | Why |
|---|---|
| Kafka / Redpanda | Source data updates every 5–30 min; scheduled Dagster is functionally indistinguishable and infinitely cheaper |
| Spark | Workload is GBs, not TBs; DuckDB on Iceberg covers analytical queries |
| Kubernetes | One box; Compose is sufficient and reproducible |
| Redis | One FastAPI process; in-process TTL cache covers the hot queries |
| Airflow | Dagster's asset model is cleaner for a data platform |
| Multi-AZ / staging environment | Cost and complexity vs. realistic V1 risk |
| Service mesh | Three internal services on one Docker network |

Each of these is a legitimate "what would you do at scale" answer, not a missing feature.
