#!/bin/sh
# Dashboard entrypoint — start the Dash app
set -e

echo "Starting Betting Dashboard on port 8050…"
exec python /app/dashboard/app.py \
    --host 0.0.0.0 \
    --port 8050 \
    --db /app/match_database
