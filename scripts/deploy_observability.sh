#!/usr/bin/env bash
# Run on the Hetzner box AFTER the 5 GRAFANA_* env vars are in
# /etc/gridpulse/.env. Brings up the observability sidecars and imports
# the dashboard + alert rules into Grafana Cloud.
#
# Required env (already in /etc/gridpulse/.env after Compose loads it):
#   GRAFANA_PROMETHEUS_URL
#   GRAFANA_PROMETHEUS_USERNAME
#   GRAFANA_LOKI_URL
#   GRAFANA_LOKI_USERNAME
#   GRAFANA_TOKEN
#   GRAFANA_STACK_URL          — e.g. https://gridpulse.grafana.net (for dashboard import)

set -euo pipefail
cd /opt/gridpulse

echo "==> pulling latest agent + exporter images"
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull \
    grafana-agent postgres-exporter node-exporter

echo "==> starting sidecars"
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d \
    grafana-agent postgres-exporter node-exporter

echo "==> waiting 30s for first metrics scrape …"
sleep 30

echo "==> agent log tail (last 20 lines):"
docker compose logs --tail 20 grafana-agent

# --- Dashboard + alert import (best-effort) ---
# These calls hit Grafana Cloud's HTTP API. They no-op if the creds aren't
# scoped for it; you can always import the JSON files by hand in the UI.
if [[ -n "${GRAFANA_STACK_URL:-}" ]]; then
    echo "==> importing dashboard"
    curl --fail --silent --show-error \
        -X POST "${GRAFANA_STACK_URL}/api/dashboards/db" \
        -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
        -H "Content-Type: application/json" \
        --data "{\"dashboard\": $(cat observability/dashboard.json), \"overwrite\": true}" \
        || echo "(dashboard import failed — import via UI: Dashboards → New → Import)"

    echo "==> importing alert rules"
    curl --fail --silent --show-error \
        -X POST "${GRAFANA_STACK_URL}/api/v1/provisioning/alert-rules" \
        -H "Authorization: Bearer ${GRAFANA_TOKEN}" \
        -H "Content-Type: application/json" \
        --data @observability/alerts.json \
        || echo "(alert import failed — import via UI: Alerting → Alert rules)"
else
    echo "GRAFANA_STACK_URL not set — skipping dashboard/alert import."
    echo "Import manually: Grafana UI → Dashboards → Import → upload observability/dashboard.json"
    echo "                Grafana UI → Alerting → Alert rules → Import → upload observability/alerts.json"
fi

echo
echo "✓ done. Check metrics flow at ${GRAFANA_STACK_URL:-grafana.com}/explore"
