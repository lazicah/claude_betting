#!/bin/bash
set -e
echo "[entrypoint] Starting Bet9ja scraper (Kambi API)..."
exec python /app/bet9ja_scraper.py -o /app/db "$@"
