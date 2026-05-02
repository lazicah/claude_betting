"""
Afropari Live Soccer Odds Scraper
====================================
Fetches live soccer match data (scores + odds) from the Afropari API.

Afropari (afropari.com) is an African sports betting platform. No VPN required.

API endpoint (live soccer):
    https://www.afropari.com/api/sport/live?sport=soccer
    or
    https://api.afropari.com/live/sport/1   (sport 1 = soccer)

NOTE: Afropari's exact API structure may differ from what's implemented here.
If requests fail, inspect your browser's network tab on https://afropari.com
while browsing the live soccer section, then update AFROPARI_API_URL and the
parsing logic to match the actual response format.

This scraper uses a flexible, defensive parser that handles several common
response shapes found in modern African sportsbook APIs.

Each live match gets its own CSV file:
    {team1}_vs_{team2}_{tournament}_afp_{date}.csv

Usage:
    python v2_afropari/afropari_scraper.py
    python v2_afropari/afropari_scraper.py --interval 5
    python v2_afropari/afropari_scraper.py -o my_data_dir
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
# Primary API URL — update if Afropari changes their API
AFROPARI_API_URL = "https://www.afropari.com/api/sport/live"
AFROPARI_API_PARAMS: dict = {"sport": "soccer"}

BOOKMAKER_TAG = "afp"

DEFAULT_POLL_INTERVAL = 5.0

# Match status keywords
STATUS_MAP = {
    "ht": "HT",
    "half time": "HT",
    "half-time": "HT",
    "halftime": "HT",
    "ft": "FT",
    "full time": "FT",
    "full-time": "FT",
    "fulltime": "FT",
    "ended": "FT",
    "finished": "FT",
    "extra time": "ET1",
    "et": "ET1",
    "penalties": "PEN",
    "pen": "PEN",
}

# Outcome label → field mapping
HOME_LABELS = {"1", "home", "w1", "home win"}
DRAW_LABELS = {"x", "draw", "tie"}
AWAY_LABELS = {"2", "away", "w2", "away win"}
OVER_LABELS = {"over"}
UNDER_LABELS = {"under"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.afropari.com",
    "Referer": "https://www.afropari.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("afropari")

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

def _parse_score(score_val) -> tuple[str, str]:
    """Return (home_score, away_score) from various score field shapes."""
    if score_val is None:
        return "", ""
    if isinstance(score_val, dict):
        home = score_val.get("home", score_val.get("homeScore",
               score_val.get("h", "")))
        away = score_val.get("away", score_val.get("awayScore",
               score_val.get("a", "")))
        return str(home) if home != "" else "", str(away) if away != "" else ""
    raw = str(score_val).strip()
    for sep in (":", "-"):
        if sep in raw:
            parts = raw.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return "", ""


def _parse_time_status(event: dict) -> tuple[str, str]:
    """Return (match_time, match_status) from an Afropari event dict."""
    # Try various time fields
    minute = (
        event.get("minute")
        or event.get("matchTime")
        or event.get("time")
        or event.get("elapsed")
        or event.get("clock")
    )
    status_raw = str(
        event.get("status")
        or event.get("matchStatus")
        or event.get("period")
        or ""
    ).lower().strip()

    status = STATUS_MAP.get(status_raw, "")

    if minute is None:
        return "", status

    time_str = str(minute).strip()
    if time_str.lower() in STATUS_MAP:
        return time_str, STATUS_MAP[time_str.lower()]
    return time_str, status


def _extract_odds(event: dict) -> tuple[str, str, str, str, str, str]:
    """Extract 1X2 and over/under odds from various field shapes."""
    odd_1 = odd_x = odd_2 = ""
    total_line = odd_over = odd_under = ""

    markets = (
        event.get("markets")
        or event.get("odds")
        or event.get("selections")
        or event.get("bets")
        or []
    )
    if not isinstance(markets, list):
        return odd_1, odd_x, odd_2, total_line, odd_over, odd_under

    for market in markets:
        if not isinstance(market, dict):
            continue

        market_name = (
            market.get("name") or market.get("type") or market.get("marketName", "")
        ).lower()

        outcomes = (
            market.get("outcomes")
            or market.get("selections")
            or market.get("picks")
            or []
        )

        is_1x2 = any(k in market_name for k in ("1x2", "match result", "winner", "full time"))
        is_total = any(k in market_name for k in ("over", "under", "total"))

        for oc in outcomes:
            label = (
                oc.get("label") or oc.get("name") or oc.get("type", "")
            ).lower().strip()
            price = oc.get("price") or oc.get("odds") or oc.get("value")
            line = oc.get("line") or oc.get("handicap") or market.get("line")

            if is_1x2 or label in HOME_LABELS | DRAW_LABELS | AWAY_LABELS:
                if label in HOME_LABELS:
                    odd_1 = _format_odd(price)
                elif label in DRAW_LABELS:
                    odd_x = _format_odd(price)
                elif label in AWAY_LABELS:
                    odd_2 = _format_odd(price)

            if is_total or label in OVER_LABELS | UNDER_LABELS:
                if label in OVER_LABELS:
                    odd_over = _format_odd(price)
                    if line is not None and not total_line:
                        total_line = str(line)
                elif label in UNDER_LABELS:
                    odd_under = _format_odd(price)
                    if line is not None and not total_line:
                        total_line = str(line)

    return odd_1, odd_x, odd_2, total_line, odd_over, odd_under


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class AfropariClient:
    """Thin wrapper around the Afropari live sports API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_live_soccer(self) -> dict:
        resp = self.session.get(
            AFROPARI_API_URL, params=AFROPARI_API_PARAMS, timeout=15
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

def parse_afropari_response(data) -> List[dict]:
    """Parse Afropari API response into standard event dicts.

    Handles various common response shapes flexibly.
    """
    results: List[dict] = []

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
        if isinstance(raw_events, dict):
            raw_events = list(raw_events.values())
    else:
        return results

    # Flatten nested league/competition → events structures
    events_flat: List[dict] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        # Detect if item is a competition container or a direct event
        has_team_fields = any(
            k in item for k in ("homeTeam", "home", "team1", "homeName")
        )
        if has_team_fields:
            events_flat.append(item)
        else:
            for key in ("events", "matches", "games", "data"):
                nested = item.get(key)
                if isinstance(nested, list):
                    for ev in nested:
                        if isinstance(ev, dict):
                            events_flat.append(ev)
                    break

    for event in events_flat:
        ev = _parse_event(event)
        if ev:
            results.append(ev)

    return results


def _parse_event(event: dict) -> dict | None:
    """Parse a single Afropari event into our standard format."""
    team1 = (
        event.get("homeTeam")
        or event.get("home")
        or event.get("team1")
        or event.get("homeName", "")
    )
    team2 = (
        event.get("awayTeam")
        or event.get("away")
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
        event.get("tournament")
        or event.get("league")
        or event.get("competition")
        or event.get("leagueName", "")
    )
    if isinstance(tournament, dict):
        tournament = tournament.get("name", "")

    score = event.get("score") or event.get("result") or event.get("currentScore")
    home_score, away_score = _parse_score(score)

    match_time, match_status = _parse_time_status(event)
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
    output_dir: str = "match_database/afropari",
    interval: float = DEFAULT_POLL_INTERVAL,
) -> None:
    client = AfropariClient()
    writer = MatchCSVWriter(output_dir)

    log.info("Afropari live SOCCER odds scraper started")
    log.info("  output dir : %s", os.path.abspath(output_dir))
    log.info("  interval   : %.1fs", interval)
    log.info("Press Ctrl+C to stop.\n")

    cycle = 0
    while True:
        t0 = time.monotonic()
        cycle += 1
        try:
            data = client.fetch_live_soccer()
            events = parse_afropari_response(data)
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
        description="Afropari live soccer odds scraper"
    )
    parser.add_argument("-o", "--output-dir", default="match_database/afropari")
    parser.add_argument("-i", "--interval", type=float, default=DEFAULT_POLL_INTERVAL)
    args = parser.parse_args()
    try:
        run(output_dir=args.output_dir, interval=args.interval)
    except KeyboardInterrupt:
        log.info("\nStopped by user.")


if __name__ == "__main__":
    main()
