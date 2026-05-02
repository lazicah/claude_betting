# 888Starz scraper — lightweight Python, no built-in VPN
# Note: 888Starz may be geo-restricted in some regions.
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests

WORKDIR /app

COPY v2_888starz/starz888_scraper.py /app/starz888_scraper.py
COPY v2_coincasino/sync_clock.py /app/sync_clock.py

COPY docker/888starz/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /app/db

ENTRYPOINT ["/entrypoint.sh"]
