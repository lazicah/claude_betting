# 1xBet scraper — lightweight Python, no built-in VPN
# Note: 1xBet may be geo-restricted in some regions.
# Mount a WireGuard config at /etc/wireguard/wg0.conf and switch to
# the VPN-enabled entrypoint if you need a VPN.
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests

WORKDIR /app

COPY v2_1xbet/onexbet_scraper.py /app/onexbet_scraper.py
COPY v2_coincasino/sync_clock.py /app/sync_clock.py

COPY docker/1xbet/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /app/db

ENTRYPOINT ["/entrypoint.sh"]
