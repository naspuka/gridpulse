# Runbook: Restore Postgres from R2 backup

**Audience:** you, on a bad day. Assume the hot Postgres is unrecoverable —
either a `DROP TABLE` accident, a corrupt volume, or a bad migration that
rolled forward through the safety nets.

**RTO target:** under 30 minutes from "decide to restore" to "site green".
**RPO:** up to 24 hours (backups run nightly at 03:30 UTC).

---

## 0. Decide whether to restore

Before touching anything, confirm:

- The site is actually broken — `curl -sf https://gridpulse.uk/healthz` fails
  and the Caddy logs show app→db errors, not app→app errors.
- The data loss is *real* and *not re-derivable in minutes*. The ingest
  assets in Dagster can repopulate the last 90 days of `raw.*` tables from
  the source APIs in roughly 10 minutes. If only `raw.*` is gone, **prefer
  re-ingesting** to restoring — fresher data, simpler operation.
- You need backup-tier recovery only if `marts.*`, Iceberg catalog tables,
  or Dagster's own metadata schema are also gone.

If yes to all three, proceed.

---

## 1. Find the most recent good backup

Backups live in R2 under `s3://${R2_BUCKET}/backups/postgres/<YYYY>/<MM>/<YYYY-MM-DD>.sql.gz`.

```bash
# From your laptop, with rclone or the AWS CLI configured for R2:
aws s3 ls "s3://${R2_BUCKET}/backups/postgres/$(date -u +%Y/%m)/" \
    --endpoint-url "${R2_ENDPOINT}"
```

Pick the latest entry. If today's backup is also bad (e.g. the corruption
was already in last night's dump), step back day by day.

---

## 2. Stop the app + Dagster

On the box:

```bash
cd /opt/gridpulse
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    stop app dagster-webserver dagster-daemon
```

**Leave Postgres + Caddy up.** Caddy will serve a 502 — that's the user
signal that something is happening. Postgres stays so we can connect with
`psql` for the restore.

---

## 3. Download the backup

```bash
DATE="2026-06-09"            # the date you picked in step 1
KEY="backups/postgres/${DATE:0:4}/${DATE:5:2}/${DATE}.sql.gz"

aws s3 cp "s3://${R2_BUCKET}/${KEY}" /tmp/restore.sql.gz \
    --endpoint-url "${R2_ENDPOINT}"

# Sanity-check: should be > 1 MB and decompress without error
ls -lh /tmp/restore.sql.gz
gunzip -t /tmp/restore.sql.gz && echo "gzip OK"
```

---

## 4. Restore into a side database (NOT prod yet)

We restore into a temp DB first. That way a bad backup doesn't take prod
down further, and we get to sanity-check the restored data before pointing
the app at it.

```bash
docker compose exec postgres psql -U gridpulse -d postgres \
    -c "DROP DATABASE IF EXISTS gridpulse_restore;"
docker compose exec postgres psql -U gridpulse -d postgres \
    -c "CREATE DATABASE gridpulse_restore;"

# Pipe the gzipped dump straight into psql — no decompressed file on disk.
gunzip -c /tmp/restore.sql.gz | \
    docker compose exec -T postgres psql -U gridpulse -d gridpulse_restore
```

Smoke-check row counts:

```bash
docker compose exec postgres psql -U gridpulse -d gridpulse_restore -c "
    SELECT 'carbon_intensity' AS t, COUNT(*) FROM raw.carbon_intensity
    UNION ALL SELECT 'generation_mix', COUNT(*) FROM raw.generation_mix
    UNION ALL SELECT 'agile_price', COUNT(*) FROM raw.agile_price;
"
```

Rough expectations on a 90-day hot store:
- `carbon_intensity` ≈ 90 days × 48 SP × 14 regions ≈ 60k rows
- `generation_mix` ≈ 90 days × 48 SP ≈ 4.3k rows
- `agile_price` ≈ 90 days × 48 SP × 14 regions ≈ 60k rows

If counts are *wildly* off, go back to step 1 and pick an older backup.

---

## 5. Swap restored DB into prod

```bash
# Rename live → broken, restored → live. Atomic-ish; takes < 1s.
docker compose exec postgres psql -U gridpulse -d postgres <<'SQL'
ALTER DATABASE gridpulse RENAME TO gridpulse_broken;
ALTER DATABASE gridpulse_restore RENAME TO gridpulse;
SQL
```

If anyone has a connection open to either DB, the RENAME blocks. Kill them:

```bash
docker compose exec postgres psql -U gridpulse -d postgres -c "
    SELECT pg_terminate_backend(pid) FROM pg_stat_activity
    WHERE datname IN ('gridpulse','gridpulse_restore');
"
```

---

## 6. Bring app + Dagster back up

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    up -d app dagster-webserver dagster-daemon

# Wait for /healthz to go green
for i in {1..20}; do
    curl -sf https://gridpulse.uk/healthz && break
    sleep 5
done
```

Then in the Dagster UI:
1. Trigger `carbon_intensity_ingest`, `generation_mix_ingest`,
   `agile_price_ingest` once to fill the gap between the backup time and now.
2. Trigger `transform` (dbt) so the marts catch up.

---

## 7. Verify the site

- `https://gridpulse.uk/` — landing page renders, "last update" within ~5 min.
- `https://gridpulse.uk/status` — all four "last ingest" rows green.
- Sentry inbox — no new errors in the 10 min after restart.

---

## 8. Clean up

```bash
# Drop the broken DB once you're confident the restore is good (give it 24h)
docker compose exec postgres psql -U gridpulse -d postgres \
    -c "DROP DATABASE gridpulse_broken;"

rm -f /tmp/restore.sql.gz
```

Post-incident: open a GitHub issue titled "post-mortem: restore on YYYY-MM-DD".
Capture root cause, what made the dump pick easy/hard, and any tooling gaps
you hit during the drill — those become the next runbook revision.

---

## Drill schedule

This runbook should be **rehearsed once before V1 launch** (task 6.8) and
then once every quarter. A backup you've never restored is not a backup.
