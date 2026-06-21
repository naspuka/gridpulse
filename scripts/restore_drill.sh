#!/usr/bin/env bash
# Automated restore drill — verifies the most recent R2 backup actually
# restores into a clean Postgres and contains the expected tables/rows.
#
# Runs entirely in a throwaway Docker container; nothing on prod is touched.
# Designed for CI (a weekly cron) AND manual rehearsal.
#
# Requires env (typically sourced from /etc/gridpulse/.env on the box):
#   R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
#
# Exit code:
#   0   restore worked, sanity-checks pass — runbook is healthy
#   1   no recent backup found
#   2   backup downloaded but psql failed to load
#   3   restored DB missing expected tables or row counts below floor

set -euo pipefail

: "${R2_ENDPOINT:?must be set}"
: "${R2_ACCESS_KEY_ID:?must be set}"
: "${R2_SECRET_ACCESS_KEY:?must be set}"
: "${R2_BUCKET:?must be set}"

WORK="$(mktemp -d)"
trap 'docker rm -f gridpulse-drill-pg >/dev/null 2>&1 || true; rm -rf "${WORK}"' EXIT

echo "==> finding most recent backup in s3://${R2_BUCKET}/backups/postgres/"

# Use the AWS CLI in a throwaway container so we don't require it on the host.
LATEST_KEY=$(docker run --rm \
    -e AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID}" \
    -e AWS_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY}" \
    -e AWS_DEFAULT_REGION=auto \
    amazon/aws-cli:2.17.0 \
    s3api list-objects-v2 \
        --bucket "${R2_BUCKET}" \
        --prefix "backups/postgres/" \
        --endpoint-url "${R2_ENDPOINT}" \
        --query 'Contents | sort_by(@, &LastModified)[-1].Key' \
        --output text 2>/dev/null || true)

if [[ -z "${LATEST_KEY}" || "${LATEST_KEY}" == "None" ]]; then
    echo "::error:: no backups found under backups/postgres/ — has the asset run yet?"
    exit 1
fi

echo "    latest: ${LATEST_KEY}"

echo "==> downloading"
docker run --rm \
    -v "${WORK}:/out" \
    -e AWS_ACCESS_KEY_ID="${R2_ACCESS_KEY_ID}" \
    -e AWS_SECRET_ACCESS_KEY="${R2_SECRET_ACCESS_KEY}" \
    -e AWS_DEFAULT_REGION=auto \
    amazon/aws-cli:2.17.0 \
    s3 cp "s3://${R2_BUCKET}/${LATEST_KEY}" /out/dump.sql.gz \
        --endpoint-url "${R2_ENDPOINT}" > /dev/null

SIZE=$(stat -f%z "${WORK}/dump.sql.gz" 2>/dev/null || stat -c%s "${WORK}/dump.sql.gz")
echo "    ${SIZE} bytes"

if [[ "${SIZE}" -lt 1000000 ]]; then
    echo "::error:: backup suspiciously small (< 1MB)"
    exit 2
fi

echo "==> spinning up scratch postgres + restoring"
docker run -d --name gridpulse-drill-pg \
    -e POSTGRES_USER=drill -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=drill \
    -v "${WORK}:/dump:ro" \
    postgres:16-alpine > /dev/null

# Wait for it to accept connections
for i in $(seq 1 30); do
    if docker exec gridpulse-drill-pg pg_isready -U drill > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! docker exec gridpulse-drill-pg pg_isready -U drill > /dev/null 2>&1; then
    echo "::error:: scratch postgres failed to come up"
    exit 2
fi

if ! docker exec gridpulse-drill-pg sh -c \
        "gunzip -c /dump/dump.sql.gz | psql -U drill -d drill -v ON_ERROR_STOP=1" \
        > "${WORK}/psql.log" 2>&1; then
    echo "::error:: psql restore failed — see log:"
    tail -30 "${WORK}/psql.log"
    exit 2
fi

echo "==> sanity-checking restored data"

# Three expected raw tables, each with at least *some* rows. Floor is low
# enough to pass on a freshly-deployed system; tighten once you have ≥ 1 week.
FLOORS=(
    "raw.carbon_intensity:100"
    "raw.generation_mix:10"
    "raw.agile_price:100"
)

FAIL=0
for entry in "${FLOORS[@]}"; do
    table="${entry%%:*}"
    floor="${entry##*:}"
    count=$(docker exec gridpulse-drill-pg \
        psql -U drill -d drill -tAc "SELECT COUNT(*) FROM ${table};" 2>/dev/null || echo 0)
    if [[ "${count}" -ge "${floor}" ]]; then
        echo "    ✓ ${table}: ${count} rows (floor ${floor})"
    else
        echo "    ✗ ${table}: ${count} rows (floor ${floor}) — TOO LOW"
        FAIL=1
    fi
done

if [[ "${FAIL}" -eq 1 ]]; then
    exit 3
fi

echo
echo "✓ restore drill PASSED — backup ${LATEST_KEY} is restorable."
