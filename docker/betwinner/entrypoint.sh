#!/bin/bash
set -e
echo "[entrypoint] Starting Betwinner scraper..."
exec python /app/betwinner_scraper.py -o /app/db "$@"
