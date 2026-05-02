# Betano scraper — lightweight Python, no built-in VPN
# Default domain: www.betano.com.br (Brazil)
# Override BETANO_DOMAIN env var for other markets:
#   www.betano.pt (Portugal), www.betano.gr (Greece), www.betano.ro (Romania)
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests

WORKDIR /app

COPY v2_betano/betano_scraper.py /app/betano_scraper.py
COPY v2_coincasino/sync_clock.py /app/sync_clock.py

COPY docker/betano/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /app/db

ENV BETANO_DOMAIN=www.betano.com.br

ENTRYPOINT ["/entrypoint.sh"]
