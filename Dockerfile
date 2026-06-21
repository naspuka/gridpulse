# syntax=docker/dockerfile:1.7
#
# Multi-stage build. Two target images:
#   --target app      → FastAPI on uvicorn
#   --target dagster  → Dagster webserver/daemon (compose chooses the command)
#
# Both share the `base` stage which installs Python + uv + the gridpulse
# package. Heavy deps (Dagster, dbt, PyIceberg) live only in the `dagster`
# stage so the `app` image stays slim.

# ---------------------------------------------------------------------------
# base — Python 3.12 + uv + core deps + gridpulse package (no editable install)
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS base

# Pin uv via the official distroless image (no curl/sh install dance).
COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# OS deps:
#   - libpq5    runtime: psycopg connects to Postgres
#   - ca-certs  runtime: HTTPS calls to source APIs
#   - tini      reaps zombie children; clean signal handling
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer 1 — deps only. Cached aggressively; rebuilds only on lockfile changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Layer 2 — package code. Rebuilds on every source change.
COPY gridpulse ./gridpulse
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev

# ---------------------------------------------------------------------------
# app — FastAPI image
# ---------------------------------------------------------------------------
FROM base AS app

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "gridpulse.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ---------------------------------------------------------------------------
# dagster — webserver OR daemon (command chosen in compose)
# ---------------------------------------------------------------------------
FROM base AS dagster

# postgresql-client gives us `pg_dump` for the nightly backup asset.
# Pinned to v16 to match the server (mismatched majors emit a warning and,
# on a wide-enough gap, refuse to dump). Debian bookworm ships v15 by
# default — pull v16 from PGDG.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && apt-get purge -y curl gnupg \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Heavy deps: Dagster, dbt, PyIceberg, DuckDB, PyArrow.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev --group ingestion

# dbt project lives at /app/dbt; the Dagster asset shells out to it.
# Rename the env-var-driven profiles.yml.example → profiles.yml inside the
# image so dbt finds it. profiles.yml itself is gitignored (so dev can drop
# a personal one locally) but the .example is committed and complete.
COPY dbt ./dbt
RUN cp /app/dbt/profiles.yml.example /app/dbt/profiles.yml

# scripts/ — one-off CLIs (init_iceberg_tables, backfill_carbon_intensity,
# query_lake). Run via `docker exec ... python -m scripts.<name>`.
COPY scripts ./scripts

ENV DAGSTER_HOME=/opt/dagster_home \
    DBT_PROJECT_DIR=/app/dbt \
    DBT_PROFILES_DIR=/app/dbt
RUN mkdir -p /opt/dagster_home

EXPOSE 3000
ENTRYPOINT ["/usr/bin/tini", "--"]
# CMD intentionally left empty — compose sets it for web vs daemon.
