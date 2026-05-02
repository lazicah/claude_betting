#!/bin/bash
set -e
echo "[entrypoint] Starting 888Starz scraper..."
exec python /app/starz888_scraper.py -o /app/db "$@"
