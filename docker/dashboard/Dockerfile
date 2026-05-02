# Betting Dashboard — Dash web UI
FROM python:3.12-slim

# Python deps
RUN pip install --no-cache-dir \
        dash==2.17.1 \
        plotly==5.24.1 \
        pandas \
        rapidfuzz

WORKDIR /app

# Copy dashboard code
COPY dashboard/ /app/dashboard/

# Data directory (mounted at runtime via volume)
RUN mkdir -p /app/match_database

# Copy entrypoint
COPY docker/dashboard/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8050

ENTRYPOINT ["/entrypoint.sh"]
