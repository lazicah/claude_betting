"""
Sportybet Live Soccer Odds Scraper
=====================================
Fetches live soccer match data (scores + odds) from the Sportybet API.

Sportybet is a major African sports betting platform operating in Nigeria,
Kenya, Ghana, Uganda, Tanzania, Zambia, and other markets. No VPN required.

The API uses Betradar sport/market IDs:
    - Sport ID : sr:sport:1 (Soccer)
    - Market 1 : 1X2 (id="1", outcomes 1/X/2)
    - Market 18: Total Goals Over/Under (specifier "total=2.5")

API endpoint (Nigerian market):
    https://www.sportybet.com/api/ng/factsCenter/liveOrPrematchCategory
    ?sportId=sr:sport:1&_t=<timestamp_ms>

Other market country codes: ke (Kenya), gh (Ghana), tz (Tanzania), ug (Uganda)

Each live match gets its own CSV file:
    {team1}_vs_{team2}_{tournament}_spy_{date}.csv

Usage:
    python v2_sportybet/sportybet_scraper.py
    python v2_sportybet/sportybet_scraper.py --interval 5
    python v2_sportybet/sportybet_scraper.py -o my_data_dir
    python v2_sportybet/sportybet_scraper.py --country ke   (Kenya market)
"""

import argparse
import csv
import datetime
import logging
import os
import re
import sys
import time
from typing import Dict, List

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
sys.path.insert(0, os.path.join(_here, "..", "v2_coincasino"))
from sync_clock import sleep_until_next_tick  # noqa: E402

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SPORTYBET_API_BASE = "https://www.sportybet.com/api"
DEFAULT_COUNTRY = "ng"       # Nigeria market; alternatives: ke, gh, tz, ug

SOCCER_SPORT_ID = "sr:sport:1"  # Betradar soccer sport ID
BOOKMAKER_TAG = "spy"

DEFAULT_POLL_INTERVAL = 5.0

# Betradar UOF market IDs (same as STS / LVBet)
MARKET_1X2_ID = "1"
MARKET_TOTAL_ID = "18"

# Match status from matchStatus string
STATUS_MAP = {
    "half-time": "HT",
    "halftime": "HT",
    "full-time": "FT",
    "fulltime": "FT",
    "ended": "FT",
    "extra time - halftime": "ETHT",
    "extra time halftime": "ETHT",
    "1st extra": "ET1",
    "2nd extra": "ET2",
    "penalties": "PEN",
    "abandoned": "ABN",
    "interrupted": "INT",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.sportybet.com",
    "Referer": "https://www.sportybet.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sportybet")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_filename(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', s).strip()


def _csv_path(output_dir: str, team1: str, team2: str,
              tournament: str, date: datetime.date) -> str:
    fname = (
        f"{_safe_filename(team1)}_vs_{_safe_filename(team2)}_"
        f"{_safe_filename(tournament)}_"
        f"{BOOKMAKER_TAG}_{date}.csv"
    )
    day_dir = os.path.join(output_dir, str(date))
    os.makedirs(day_dir, exist_ok=True)
    return os.path.join(day_dir, fname)


CSV_COLUMNS = [
    "timestamp", "match_time", "match_status",
    "home_score", "away_score",
    "odd_1", "odd_X", "odd_2",
    "total_line", "odd_over", "odd_under",
]


def _write_header_if_needed(path: str) -> None:
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(CSV_COLUMNS)


def _append_row(path: str, row: list) -> None:
    with open(path, "a", newline="") as f:
        csv.writer(f).writerow(row)


def _format_odd(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (ValueError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _played_seconds_to_time(played_seconds) -> str:
    """Convert seconds played to a minute string (e.g. 1920 → '32')."""
    if played_seconds is None:
        return ""
    try:
        minutes = int(played_seconds) // 60
        return str(minutes)
    except (ValueError, TypeError):
        return ""


def _parse_match_status(status_str: str) -> str:
    """Convert a Sportybet matchStatus string to our status code."""
    if not status_str:
        return ""
    return STATUS_MAP.get(status_str.lower().strip(), "")


def _extract_line_from_specifier(specifier: str) -> str:
    """Extract line from specifier like 'total=2.5' → '2.5'."""
    m = re.search(r"total=([\d.]+)", specifier)
    return m.group(1) if m else ""


def _extract_odds_from_markets(markets: list) -> tuple[str, str, str, str, str, str]:
    """Parse 1X2 and total goals odds from a Sportybet markets array."""
    odd_1 = odd_x = odd_2 = ""
    total_line = odd_over = odd_under = ""

    for market in markets or []:
        market_id = str(market.get("id", ""))
        specifier = market.get("specifier", "") or ""
        outcomes = market.get("outcomes", []) or []

        if market_id == MARKET_1X2_ID:
            for oc in outcomes:
                if not oc.get("isActive", 1):
                    continue
                desc = str(oc.get("desc", "")).strip()
                odds_val = oc.get("odds")
                if desc == "1":
                    odd_1 = _format_odd(odds_val)
                elif desc == "X":
                    odd_x = _format_odd(odds_val)
                elif desc == "2":
                    odd_2 = _format_odd(odds_val)

        elif market_id == MARKET_TOTAL_ID:
            if not total_line and specifier:
                total_line = _extract_line_from_specifier(specifier)
            for oc in outcomes:
                if not oc.get("isActive", 1):
                    continue
                desc = str(oc.get("desc", "")).strip().lower()
                odds_val = oc.get("odds")
                if "over" in desc:
                    odd_over = _format_odd(odds_val)
                elif "under" in desc:
                    odd_under = _format_odd(odds_val)

    return odd_1, odd_x, odd_2, total_line, odd_over, odd_under


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class SportybetClient:
    """Thin wrapper around the Sportybet facts-center API."""

    def __init__(self, country: str = DEFAULT_COUNTRY):
        self.country = country
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_live_soccer(self) -> dict:
        """Fetch all live soccer events for the configured country market."""
        url = (
            f"{SPORTYBET_API_BASE}/{self.country}"
            "/factsCenter/liveOrPrematchCategory"
        )
        params = {
            "sportId": SOCCER_SPORT_ID,
            "_t": int(time.time() * 1000),  # cache-busting timestamp
        }
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

def parse_sportybet_response(data: dict) -> List[dict]:
    """Parse Sportybet API response into standard event dicts."""
    results: List[dict] = []

    sports = (
        (data.get("data") or {}).get("sports", [])
        or data.get("sports", [])
    )

    for sport in sports:
        if str(sport.get("id", "")) != SOCCER_SPORT_ID:
            continue
        for tournament in sport.get("tournaments", []) or []:
            tourn_name = tournament.get("name", "")
            category = tournament.get("category") or {}
            category_name = category.get("name", "")
            display_name = (
                f"{category_name} - {tourn_name}" if category_name else tourn_name
            )
            for event in tournament.get("events", []) or []:
                ev = _parse_event(event, display_name)
                if ev:
                    results.append(ev)

    return results


def _parse_event(event: dict, tournament: str) -> dict | None:
    """Parse a single Sportybet event into our standard format."""
    team1 = event.get("homeTeamName", "")
    team2 = event.get("awayTeamName", "")
    if not team1 or not team2:
        return None

    home_score = str(event.get("homeScore", ""))
    away_score = str(event.get("awayScore", ""))

    played_seconds = event.get("playedSeconds")
    match_time = _played_seconds_to_time(played_seconds)

    match_status_str = event.get("matchStatus", "")
    match_status = _parse_match_status(match_status_str)

    markets = event.get("markets", []) or []
    odd_1, odd_x, odd_2, total_line, odd_over, odd_under = \
        _extract_odds_from_markets(markets)

    scheduled_str = event.get("scheduledTime") or event.get("startTime")
    scheduled_dt = None
    if scheduled_str:
        try:
            scheduled_dt = datetime.datetime.fromisoformat(
                str(scheduled_str).replace("Z", "+00:00")
            )
        except ValueError:
            pass
        if scheduled_dt is None:
            try:
                ts = int(scheduled_str)
                scheduled_dt = datetime.datetime.fromtimestamp(
                    ts / 1000 if ts > 1_000_000_000_000 else ts
                )
            except (ValueError, TypeError, OSError):
                pass

    return {
        "event_id": str(event.get("eventId", event.get("id", ""))),
        "team1": team1,
        "team2": team2,
        "tournament": tournament,
        "home_score": home_score,
        "away_score": away_score,
        "match_time": match_time,
        "match_status": match_status,
        "odd_1": odd_1,
        "odd_X": odd_x,
        "odd_2": odd_2,
        "total_line": total_line,
        "odd_over": odd_over,
        "odd_under": odd_under,
        "scheduled": scheduled_dt,
    }


# ---------------------------------------------------------------------------
# Writer - one CSV per match
# ---------------------------------------------------------------------------

class MatchCSVWriter:
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self._paths: Dict[str, str] = {}

    def write(self, ev: dict) -> None:
        eid = ev["event_id"]
        if eid not in self._paths:
            date = (ev["scheduled"].date()
                    if ev.get("scheduled") else datetime.date.today())
            path = _csv_path(
                self.output_dir, ev["team1"], ev["team2"],
                ev["tournament"], date,
            )
            self._paths[eid] = path
            _write_header_if_needed(path)
        now = datetime.datetime.now().isoformat(timespec="milliseconds")
        row = [
            now, ev["match_time"], ev["match_status"],
            ev["home_score"], ev["away_score"],
            ev["odd_1"], ev["odd_X"], ev["odd_2"],
            ev["total_line"], ev["odd_over"], ev["odd_under"],
        ]
        _append_row(self._paths[eid], row)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(
    output_dir: str = "match_database/sportybet",
    interval: float = DEFAULT_POLL_INTERVAL,
    country: str = DEFAULT_COUNTRY,
) -> None:
    client = SportybetClient(country=country)
    writer = MatchCSVWriter(output_dir)

    log.info("Sportybet live SOCCER odds scraper started (market: %s)", country.upper())
    log.info("  output dir : %s", os.path.abspath(output_dir))
    log.info("  interval   : %.1fs", interval)
    log.info("Press Ctrl+C to stop.\n")

    cycle = 0
    while True:
        t0 = time.monotonic()
        cycle += 1
        try:
            data = client.fetch_live_soccer()
            events = parse_sportybet_response(data)
            for ev in events:
                writer.write(ev)
            n_total = len(events)
            n_with_odds = sum(1 for e in events if e["odd_1"])
            elapsed = time.monotonic() - t0
            log.info(
                "cycle %4d  |  %3d soccer matches  |  %3d with odds  |  %.2fs",
                cycle, n_total, n_with_odds, elapsed,
            )
        except requests.RequestException as exc:
            log.warning("Network error: %s", exc)
        except Exception:
            log.exception("Unexpected error in cycle %d", cycle)
        sleep_until_next_tick(interval)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sportybet live soccer odds scraper (Betradar API)"
    )
    parser.add_argument("-o", "--output-dir", default="match_database/sportybet")
    parser.add_argument("-i", "--interval", type=float, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument(
        "--country",
        default=DEFAULT_COUNTRY,
        choices=["ng", "ke", "gh", "tz", "ug", "zm"],
        help="Country market code (default: ng = Nigeria)",
    )
    args = parser.parse_args()
    try:
        run(output_dir=args.output_dir, interval=args.interval, country=args.country)
    except KeyboardInterrupt:
        log.info("\nStopped by user.")


if __name__ == "__main__":
    main()
