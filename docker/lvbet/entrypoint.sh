#!/bin/bash
set -e
echo "[entrypoint] Starting LVBet scraper..."
exec python /app/lvbet_scraper.py -o /app/db "$@"
