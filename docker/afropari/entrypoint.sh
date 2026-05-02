#!/bin/bash
set -e
echo "[entrypoint] Starting Afropari scraper..."
exec python /app/afropari_scraper.py -o /app/db "$@"
