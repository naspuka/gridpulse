#!/usr/bin/env bash
# Configure R2 object lifecycle for the gridpulse-lake bucket.
#
# Why a script (not Terraform)? Cloudflare's Terraform provider v4.x doesn't
# yet ship a `cloudflare_r2_bucket_lifecycle` resource — the lifecycle API
# is REST-only at the moment. This script is the bridge. Run once after
# `terraform apply`, then re-run only if the rules below change.
#
# Rules:
#   - backups/postgres/   → delete objects 30 days after upload
#   - lake/               → keep forever (Iceberg manages snapshot expiry
#                           through its own asset; we don't want R2 to
#                           independently delete Parquet files referenced
#                           by a live snapshot)
#
# Requires env vars:
#   CLOUDFLARE_API_TOKEN     — same token used by Terraform (R2 read+write)
#   CLOUDFLARE_ACCOUNT_ID
#   R2_BUCKET                — gridpulse-lake

set -euo pipefail

: "${CLOUDFLARE_API_TOKEN:?must be set}"
: "${CLOUDFLARE_ACCOUNT_ID:?must be set}"
: "${R2_BUCKET:?must be set}"

URL="https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/r2/buckets/${R2_BUCKET}/lifecycle"

curl --fail --show-error --silent \
    -X PUT "$URL" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data @- <<'JSON'
{
  "rules": [
    {
      "id": "expire-postgres-backups-30d",
      "enabled": true,
      "conditions": { "prefix": "backups/postgres/" },
      "deleteObjectsTransition": {
        "condition": { "type": "Age", "maxAge": 2592000 }
      }
    }
  ]
}
JSON

echo
echo "✓ lifecycle rules applied to ${R2_BUCKET}"
