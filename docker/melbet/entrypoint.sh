#!/bin/bash
set -e
echo "[entrypoint] Starting Melbet scraper..."
exec python /app/melbet_scraper.py -o /app/db "$@"
