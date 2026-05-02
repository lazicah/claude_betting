#!/bin/bash
set -e
echo "[entrypoint] Starting Betking scraper..."
exec python /app/betking_scraper.py -o /app/db "$@"
