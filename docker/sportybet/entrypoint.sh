#!/bin/bash
set -e
COUNTRY="${SPORTYBET_COUNTRY:-ng}"
echo "[entrypoint] Starting Sportybet scraper (market: ${COUNTRY^^})..."
exec python /app/sportybet_scraper.py -o /app/db --country "$COUNTRY" "$@"
