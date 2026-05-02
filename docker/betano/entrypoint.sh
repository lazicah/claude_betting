#!/bin/bash
set -e
DOMAIN="${BETANO_DOMAIN:-www.betano.com.br}"
echo "[entrypoint] Starting Betano scraper (domain: ${DOMAIN})..."
exec python /app/betano_scraper.py -o /app/db --domain "$DOMAIN" "$@"
