#!/usr/bin/env bash
# Load test the public /api/v1/best-slots endpoint.
#
# Target from CLAUDE.md: 100 RPS sustained, p99 < 500 ms.
#
# Uses `hey` (https://github.com/rakyll/hey) — single static binary, dead
# simple. If you don't have it: `brew install hey` or
# `go install github.com/rakyll/hey@latest`.
#
# Why this endpoint? It hits the cachetools-backed cache layer + Postgres
# only on misses, so it exercises the realistic warm-path the public JSON
# API serves. /api/v1/current-intensity is also cached but trivially small;
# best-slots is the most expensive read (mart_best_slots_24h scan).

set -euo pipefail

URL="${URL:-https://gridpulse.uk/api/v1/best-slots?region=london}"
DURATION="${DURATION:-30s}"      # how long to sustain
RPS="${RPS:-100}"                # target requests per second
CONCURRENCY="${CONCURRENCY:-20}" # parallel workers; ~2× RPS / latency_p50

echo "Hitting ${URL} at ${RPS} RPS for ${DURATION} (concurrency=${CONCURRENCY})"
echo

hey -z "${DURATION}" -q "${RPS}" -c "${CONCURRENCY}" "${URL}"

echo
echo "Pass criteria:"
echo "  - 0 non-2xx responses"
echo "  - p99 < 500 ms (see [Latency distribution] above)"
echo "  - Sustained RPS within 5% of target"
