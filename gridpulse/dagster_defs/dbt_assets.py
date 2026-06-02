"""Wire dbt build as a single Dagster asset.

We deliberately keep this as a **single Dagster asset** rather than the
dagster-dbt integration's per-model asset graph. Reasons:
- Our V1 model count is small (5 models) — the dependency graph is hand-
  managed and easy to read. Per-model assets would 5× the UI noise without
  giving us 5× the value.
- dbt's own DAG already orders the run. Letting dbt drive it is honest.
- Keeps the project's only direct dependency on dbt at the orchestration
  layer — no `from dagster_dbt import ...` sprawl in app code.

The asset depends on all three raw-table ingestion assets so that
`dbt build` only runs after raw data is fresh.

Note: this module does NOT use `from __future__ import annotations` — same
Dagster gotcha as assets.py, the validator does an `is`-check on the
`context` annotation.
"""

import os
import subprocess
from pathlib import Path

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from gridpulse.lib.heartbeat import with_heartbeat

# Project root inside the container — set by docker-compose.prod.yml.
# Falls back to a sensible repo-relative path for local dev.
_DBT_PROJECT_DIR = Path(os.environ.get("DBT_PROJECT_DIR", "/app/dbt"))
_DBT_PROFILES_DIR = Path(os.environ.get("DBT_PROFILES_DIR", "/app/dbt"))


def _run_dbt(context: AssetExecutionContext, *args: str) -> str:
    """Run a dbt subcommand; capture stdout for the Dagster UI."""
    cmd = [
        "dbt",
        *args,
        "--project-dir",
        str(_DBT_PROJECT_DIR),
        "--profiles-dir",
        str(_DBT_PROFILES_DIR),
    ]
    context.log.info("running: %s", " ".join(cmd))
    result = subprocess.run(  # noqa: S603 — controlled args
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    context.log.info("dbt stdout (tail):\n%s", "\n".join(result.stdout.splitlines()[-50:]))
    if result.returncode != 0:
        context.log.error("dbt stderr:\n%s", result.stderr)
        raise RuntimeError(f"dbt {args[0] if args else '<noop>'} exited {result.returncode}")
    return result.stdout


@asset(
    description=(
        "Runs `dbt build` against Postgres — compiles models, runs them, "
        "then runs dbt tests. Single-asset wrapper; dbt drives the model DAG."
    ),
    group_name="transforms",
    compute_kind="dbt",
    deps=[
        "carbon_intensity_national",
        "carbon_intensity_regional",
        "generation_mix",
        "agile_price",
    ],
)
@with_heartbeat("dbt_build")
def dbt_build(context: AssetExecutionContext) -> MaterializeResult:
    # `dbt deps` is idempotent and cheap; safer than asking ops to remember to run it.
    _run_dbt(context, "deps")
    out = _run_dbt(context, "build")

    # Pull a rough run summary out of dbt's stdout for the Dagster UI.
    pass_count = sum(1 for line in out.splitlines() if " PASS" in line)
    error_count = sum(1 for line in out.splitlines() if " ERROR" in line)
    return MaterializeResult(
        metadata={
            "project_dir": MetadataValue.path(str(_DBT_PROJECT_DIR)),
            "pass_steps": MetadataValue.int(pass_count),
            "error_steps": MetadataValue.int(error_count),
        }
    )
