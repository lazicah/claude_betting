#!/bin/bash
set -e
echo "[entrypoint] Starting 1xBet scraper..."
exec python /app/onexbet_scraper.py -o /app/db "$@"
