# Betking scraper — lightweight Python, no VPN needed
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests

WORKDIR /app

COPY v2_betking/betking_scraper.py /app/betking_scraper.py
COPY v2_coincasino/sync_clock.py /app/sync_clock.py

COPY docker/betking/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /app/db

ENTRYPOINT ["/entrypoint.sh"]
