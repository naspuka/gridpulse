"""Nightly Postgres backup → Cloudflare R2.

One asset, one schedule. Runs `pg_dump` against the hot Postgres, gzips the
output, streams it to R2 under `backups/postgres/<YYYY>/<MM>/<YYYY-MM-DD>.sql.gz`.

Retention is handled out-of-band by an R2 lifecycle policy (30 days for
dailies, 12 months for the 1st-of-month snapshot — configured separately).
Keeping retention *outside* Dagster means a Dagster outage can't accidentally
delete backups, and a misbehaving asset can't either.

Why pg_dump (not pg_basebackup or WAL archiving)?
- A 9GB hot store dumps to ~150MB gzipped. Trivial for the free R2 tier.
- Logical dump is portable across Postgres minor versions — important if we
  ever migrate the box and restore on a fresher Postgres.
- We accept the loss window of "up to 24 hours since last dump". The data is
  re-derivable from the source APIs anyway; backups guard against operator
  error (DROP TABLE, bad migration) not API loss.

This module does NOT use `from __future__ import annotations` — Dagster
resolves the `context: AssetExecutionContext` parameter annotation at
import time and chokes on stringified forms.
"""

import contextlib
import gzip
import os
import subprocess
from datetime import UTC, datetime
from typing import Any

import boto3
from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from gridpulse.lib.heartbeat import with_heartbeat

# Where backups live inside the R2 bucket. Same bucket as the Iceberg lake
# (free-tier friendly); different prefix so lifecycle rules don't collide.
BACKUP_PREFIX = "backups/postgres"


def _r2_client() -> Any:
    """boto3 S3 client pointed at Cloudflare R2.

    R2 is S3-compatible at the wire level; just override the endpoint.
    """
    endpoint = os.environ["R2_ENDPOINT"]
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",  # R2 ignores it, boto3 demands it
    )


def _dump_to_gzip(database_url: str, dest_path: str) -> int:
    """Stream `pg_dump <database_url>` → gzip → dest_path. Returns bytes written.

    We use the URL form (`pg_dump <conn-url>`) so we don't have to split out
    host/user/pass/db. pg_dump 16 understands postgresql:// natively.
    """
    # `-Z 0` because we gzip in Python — letting pg_dump compress would block
    # the streaming pipe model and give worse ratios.
    cmd = ["pg_dump", "--no-owner", "--no-privileges", "-Z", "0", database_url]
    written = 0
    with (
        gzip.open(dest_path, "wb", compresslevel=6) as gz,
        subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc,
    ):
        assert proc.stdout is not None
        while chunk := proc.stdout.read(65536):
            gz.write(chunk)
            written += len(chunk)
        proc.wait(timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump exited {proc.returncode}")
    return written


@asset(group_name="backups", compute_kind="postgres")
@with_heartbeat("backup_postgres")
def backup_postgres(context: AssetExecutionContext) -> MaterializeResult:
    """Dump the hot Postgres to R2, gzipped, keyed by UTC date.

    Idempotent: re-running on the same day overwrites today's backup. The
    monthly snapshot is just the 1st-of-month daily — R2 lifecycle keeps it
    longer than the rest.
    """
    database_url = os.environ["DATABASE_URL"]
    bucket = os.environ["R2_BUCKET"]

    today = datetime.now(UTC).date()
    key = f"{BACKUP_PREFIX}/{today.year:04d}/{today.month:02d}/{today.isoformat()}.sql.gz"

    # Use /tmp so we don't accidentally fill the persistent Dagster volume.
    # pg_dump → gzip pipeline ~150 MB on a 9 GB hot store; /tmp on the box
    # has plenty of headroom. Dagster step containers wipe /tmp on exit.
    local_path = f"/tmp/gridpulse-pg-{today.isoformat()}.sql.gz"

    context.log.info("pg_dump → %s", local_path)
    raw_bytes = _dump_to_gzip(database_url, local_path)
    compressed_bytes = os.path.getsize(local_path)

    # Sanity: a dump shouldn't be < 1 MB if Postgres has any data at all.
    # Catches the "pg_dump silently succeeded with 0 rows" failure mode.
    if compressed_bytes < 1_000_000:
        raise RuntimeError(
            f"Backup suspiciously small ({compressed_bytes} bytes) — refusing to upload"
        )

    context.log.info("uploading %s bytes → s3://%s/%s", compressed_bytes, bucket, key)
    r2 = _r2_client()
    r2.upload_file(local_path, bucket, key)

    # Best-effort cleanup; Dagster step container gets wiped anyway but no
    # reason to leave a 150 MB file sitting around on a long-running daemon.
    with contextlib.suppress(OSError):
        os.unlink(local_path)

    return MaterializeResult(
        metadata={
            "date": MetadataValue.text(today.isoformat()),
            "r2_key": MetadataValue.text(key),
            "raw_bytes": MetadataValue.int(raw_bytes),
            "compressed_bytes": MetadataValue.int(compressed_bytes),
            "compression_ratio": MetadataValue.float(
                round(raw_bytes / compressed_bytes, 2) if compressed_bytes else 0.0
            ),
        }
    )
