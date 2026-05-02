"""
Betking Live Soccer Odds Scraper
===================================
Fetches live soccer match data (scores + odds) from the Betking API.

Betking (betking.com) is a Nigerian sports betting platform. No VPN required.

API endpoint (live soccer):
    https://sports.betking.com/api/Odds/GetOddsForInPlayBySportID
    ?SportId=1&PageNumber=1&NumberOfItemsPerPage=200

Where SportId=1 is soccer/football.

NOTE: If the above endpoint returns 404 or empty data, inspect your browser's
network tab on https://betking.com/sports while browsing live football to
discover the current API endpoint structure. The platform may have been
updated since this scraper was written.

Alternative endpoint to try:
    https://www.betking.com/api/v1/sports/live?sport_id=1&page=1

Each live match gets its own CSV file:
    {team1}_vs_{team2}_{tournament}_bkg_{date}.csv

Usage:
    python v2_betking/betking_scraper.py
    python v2_betking/betking_scraper.py --interval 5
    python v2_betking/betking_scraper.py -o my_data_dir
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
# Primary API endpoint — may require update if Betking changes their platform
BETKING_API_URL = (
    "https://sports.betking.com/api/Odds/GetOddsForInPlayBySportID"
    "?SportId=1&PageNumber=1&NumberOfItemsPerPage=200"
)
BOOKMAKER_TAG = "bkg"

DEFAULT_POLL_INTERVAL = 5.0

# Betking market names (may vary — update if needed)
MARKET_1X2_NAMES = {"1x2", "match result", "winner", "full time result"}
MARKET_TOTAL_NAMES = {"total goals", "over/under", "total"}

# Status string mappings
STATUS_MAP = {
    "ht": "HT",
    "half time": "HT",
    "half-time": "HT",
    "half_time": "HT",
    "2nd half": "",
    "1st half": "",
    "ft": "FT",
    "full time": "FT",
    "full-time": "FT",
    "aet": "AET",
    "after extra time": "AET",
    "penalties": "PEN",
    "pen": "PEN",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.betking.com",
    "Referer": "https://www.betking.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("betking")

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

def _parse_score(score_str) -> tuple[str, str]:
    """Parse a score string like '1:0', '1-0', or a dict into (home, away)."""
    if score_str is None:
        return "", ""
    if isinstance(score_str, dict):
        home = score_str.get("home", score_str.get("homeScore", ""))
        away = score_str.get("away", score_str.get("awayScore", ""))
        return str(home) if home != "" else "", str(away) if away != "" else ""
    raw = str(score_str).strip()
    for sep in (":", "-"):
        if sep in raw:
            parts = raw.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return "", ""


def _parse_match_time_status(event: dict) -> tuple[str, str]:
    """Return (match_time, match_status) from a Betking event dict."""
    # Try various time fields
    minute = (
        event.get("minute")
        or event.get("matchTime")
        or event.get("elapsed")
        or event.get("time")
    )
    status_raw = (
        event.get("statusName")
        or event.get("matchStatus")
        or event.get("status", "")
    )
    status_key = str(status_raw).lower().strip()
    status = STATUS_MAP.get(status_key, "")

    # If the time field itself contains a status keyword
    if minute is None:
        if status_key in STATUS_MAP:
            return "", status
        return "", ""

    time_str = str(minute).strip()
    if time_str.lower() in STATUS_MAP:
        return time_str, STATUS_MAP[time_str.lower()]
    return time_str, status


def _extract_odds(event: dict) -> tuple[str, str, str, str, str, str]:
    """Extract 1X2 and total goals odds from a Betking event."""
    odd_1 = odd_x = odd_2 = ""
    total_line = odd_over = odd_under = ""

    # Betking may embed markets in 'markets', 'odds', 'bets', or 'selections'
    markets = (
        event.get("markets")
        or event.get("odds")
        or event.get("bets")
        or event.get("selections")
        or []
    )
    if not isinstance(markets, list):
        return odd_1, odd_x, odd_2, total_line, odd_over, odd_under

    for market in markets:
        if not isinstance(market, dict):
            continue

        market_name = (
            market.get("marketName")
            or market.get("name")
            or market.get("type", "")
        ).lower().strip()

        outcomes = (
            market.get("outcomes")
            or market.get("selections")
            or market.get("picks")
            or []
        )

        if market_name in MARKET_1X2_NAMES:
            for oc in outcomes:
                label = (
                    oc.get("label")
                    or oc.get("name")
                    or oc.get("type", "")
                ).upper().strip()
                price = oc.get("odds") or oc.get("price") or oc.get("value")
                if label in ("1", "HOME", "W1"):
                    odd_1 = _format_odd(price)
                elif label in ("X", "DRAW", "D"):
                    odd_x = _format_odd(price)
                elif label in ("2", "AWAY", "W2"):
                    odd_2 = _format_odd(price)

        elif any(kw in market_name for kw in MARKET_TOTAL_NAMES):
            line = market.get("line") or market.get("handicap") or market.get("points")
            if line is not None and not total_line:
                total_line = str(line)
            for oc in outcomes:
                label = (
                    oc.get("label")
                    or oc.get("name")
                    or oc.get("type", "")
                ).lower().strip()
                price = oc.get("odds") or oc.get("price") or oc.get("value")
                if "over" in label:
                    odd_over = _format_odd(price)
                elif "under" in label:
                    odd_under = _format_odd(price)

    return odd_1, odd_x, odd_2, total_line, odd_over, odd_under


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class BetkingClient:
    """Thin wrapper around the Betking in-play API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_live_soccer(self) -> dict:
        resp = self.session.get(BETKING_API_URL, timeout=15)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

def parse_betking_response(data) -> List[dict]:
    """Parse Betking API response into standard event dicts.

    Handles both list and dict top-level structures.
    """
    results: List[dict] = []

    # Top-level can be a list, a dict with 'events'/'data', or other shapes
    if isinstance(data, list):
        raw_events = data
    elif isinstance(data, dict):
        raw_events = (
            data.get("events")
            or data.get("data")
            or data.get("matches")
            or data.get("result")
            or []
        )
        # If data is wrapped another level deep
        if isinstance(raw_events, dict):
            raw_events = (
                raw_events.get("events")
                or raw_events.get("matches")
                or list(raw_events.values())
                or []
            )
    else:
        return results

    # Flatten nested competition → events structures
    events_flat: List[dict] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        if "homeTeam" in item or "home" in item or "team1" in item:
            events_flat.append(item)
        else:
            # Might be a competition/league container
            for key in ("events", "matches", "games"):
                nested = item.get(key)
                if isinstance(nested, list):
                    events_flat.extend(nested)
                    break

    for event in events_flat:
        ev = _parse_event(event)
        if ev:
            results.append(ev)

    return results


def _parse_event(event: dict) -> dict | None:
    """Parse a single Betking event into our standard format."""
    # Team names (multiple possible field names)
    team1 = (
        event.get("homeTeam")
        or event.get("home")
        or (event.get("teams", {}) or {}).get("home", {}).get("name")
        or event.get("team1")
        or event.get("homeName", "")
    )
    team2 = (
        event.get("awayTeam")
        or event.get("away")
        or (event.get("teams", {}) or {}).get("away", {}).get("name")
        or event.get("team2")
        or event.get("awayName", "")
    )
    if isinstance(team1, dict):
        team1 = team1.get("name", "")
    if isinstance(team2, dict):
        team2 = team2.get("name", "")
    team1, team2 = str(team1).strip(), str(team2).strip()
    if not team1 or not team2:
        return None

    tournament = (
        event.get("leagueName")
        or event.get("competition")
        or event.get("league")
        or event.get("tournament", "")
    )
    if isinstance(tournament, dict):
        tournament = tournament.get("name", "")

    score = event.get("score") or event.get("result") or event.get("currentScore")
    home_score, away_score = _parse_score(score)

    match_time, match_status = _parse_match_time_status(event)
    odd_1, odd_x, odd_2, total_line, odd_over, odd_under = _extract_odds(event)

    start = (
        event.get("startTime")
        or event.get("startDate")
        or event.get("date")
        or event.get("kickOff")
    )
    scheduled_dt = None
    if start:
        try:
            scheduled_dt = datetime.datetime.fromisoformat(
                str(start).replace("Z", "+00:00")
            )
        except ValueError:
            pass

    return {
        "event_id": str(event.get("id") or event.get("eventId") or ""),
        "team1": team1,
        "team2": team2,
        "tournament": str(tournament),
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
    output_dir: str = "match_database/betking",
    interval: float = DEFAULT_POLL_INTERVAL,
) -> None:
    client = BetkingClient()
    writer = MatchCSVWriter(output_dir)

    log.info("Betking live SOCCER odds scraper started")
    log.info("  output dir : %s", os.path.abspath(output_dir))
    log.info("  interval   : %.1fs", interval)
    log.info("Press Ctrl+C to stop.\n")

    cycle = 0
    while True:
        t0 = time.monotonic()
        cycle += 1
        try:
            data = client.fetch_live_soccer()
            events = parse_betking_response(data)
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
        description="Betking live soccer odds scraper"
    )
    parser.add_argument("-o", "--output-dir", default="match_database/betking")
    parser.add_argument("-i", "--interval", type=float, default=DEFAULT_POLL_INTERVAL)
    args = parser.parse_args()
    try:
        run(output_dir=args.output_dir, interval=args.interval)
    except KeyboardInterrupt:
        log.info("\nStopped by user.")


if __name__ == "__main__":
    main()
