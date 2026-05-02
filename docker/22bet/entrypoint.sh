#!/bin/bash
set -e
echo "[entrypoint] Starting 22Bet scraper..."
exec python /app/bet22_scraper.py -o /app/db "$@"
