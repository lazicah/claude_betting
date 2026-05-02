"""
Betano Live Soccer Odds Scraper
==================================
Fetches live soccer match data (scores + odds) from the Betano REST API.

Betano is operated by Kaizen Gaming and runs in multiple countries:
  Brazil  : https://www.betano.com.br
  Portugal: https://www.betano.pt
  Greece  : https://www.betano.gr
  Romania : https://www.betano.ro

The Brazilian market (default) is used as a reference.

API endpoint:
    https://www.betano.com.br/api/sport/1/live/?tz=0
    (sport id 1 = soccer/football)

Response structure:
    {
      "data": {
        "blocks": [
          {
            "id": <league_id>,
            "title": <league_name>,
            "events": [
              {
                "id": <event_id>,
                "homeTeam": {"name": "..."},
                "awayTeam": {"name": "..."},
                "result": {"homeScore": N, "awayScore": N},
                "time": <match_minute_or_status>,
                "selections": [...]   // odds
              }
            ]
          }
        ]
      }
    }

Each live match gets its own CSV file:
    {team1}_vs_{team2}_{tournament}_bta_{date}.csv

Usage:
    python v2_betano/betano_scraper.py
    python v2_betano/betano_scraper.py --interval 5
    python v2_betano/betano_scraper.py -o my_data_dir
    python v2_betano/betano_scraper.py --domain betano.pt   (Portugal)
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
DEFAULT_DOMAIN = "www.betano.com.br"   # Change to betano.pt / betano.gr etc.
BOOKMAKER_TAG = "bta"

SOCCER_SPORT_ID = "1"   # Betano uses numeric ID 1 for soccer/football

DEFAULT_POLL_INTERVAL = 5.0

# Betano selection (outcome) type keywords
OUTCOME_HOME_KEYWORDS = {"1", "home", "home win", "w1"}
OUTCOME_DRAW_KEYWORDS = {"x", "draw", "tie"}
OUTCOME_AWAY_KEYWORDS = {"2", "away", "away win", "w2"}
OUTCOME_OVER_KEYWORDS = {"over"}
OUTCOME_UNDER_KEYWORDS = {"under"}

# Status strings → our codes
STATUS_MAP = {
    "ht": "HT",
    "half time": "HT",
    "half-time": "HT",
    "ft": "FT",
    "full time": "FT",
    "full-time": "FT",
    "et": "ET1",
    "extra time": "ET1",
    "pen": "PEN",
    "penalties": "PEN",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("betano")

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

def _parse_match_time_and_status(time_field) -> tuple[str, str]:
    """Parse the `time` field from a Betano event into (match_time, match_status).

    The time field may be:
      - An integer (minutes elapsed, e.g. 32)
      - A string like "32", "HT", "FT", "45+2"
      - A dict with a `minute` key
    """
    if time_field is None:
        return "", ""

    if isinstance(time_field, dict):
        minute = time_field.get("minute") or time_field.get("m")
        status = time_field.get("status") or time_field.get("s", "")
        return str(minute) if minute is not None else "", STATUS_MAP.get(
            str(status).lower().strip(), ""
        )

    raw = str(time_field).strip()
    raw_lower = raw.lower()

    if raw_lower in STATUS_MAP:
        return raw, STATUS_MAP[raw_lower]

    # Numeric or numeric-with-added-time
    if re.match(r"^\d+", raw):
        return raw, ""

    return raw, ""


def _parse_score(result) -> tuple[str, str]:
    """Return (home_score, away_score) from a Betano result object."""
    if result is None:
        return "", ""
    if isinstance(result, dict):
        home = result.get("homeScore", result.get("home", ""))
        away = result.get("awayScore", result.get("away", ""))
        return str(home) if home != "" else "", str(away) if away != "" else ""
    if isinstance(result, str) and ":" in result:
        parts = result.split(":")
        return parts[0].strip(), parts[1].strip()
    return "", ""


def _parse_selections(selections: list) -> tuple[str, str, str, str, str, str]:
    """Parse odds from a Betano selections array.

    Betano selections arrays can appear in different shapes depending on the
    market type. We look for 1X2 outcomes (label "1"/"X"/"2") and
    Over/Under outcomes, keeping the best line we encounter.
    """
    odd_1 = odd_x = odd_2 = ""
    total_line = odd_over = odd_under = ""

    if not selections:
        return odd_1, odd_x, odd_2, total_line, odd_over, odd_under

    for sel in selections:
        if not isinstance(sel, dict):
            continue

        # Navigate into nested markets / outcomes if present
        markets = sel.get("markets") or sel.get("outcomes") or []
        if markets and isinstance(markets, list):
            # Recursive call for nested structure
            o1, ox, o2, tl, ov, un = _parse_selections(markets)
            if o1:
                odd_1 = o1
            if ox:
                odd_x = ox
            if o2:
                odd_2 = o2
            if tl:
                total_line = tl
            if ov:
                odd_over = ov
            if un:
                odd_under = un
            continue

        label = (
            sel.get("name") or sel.get("label") or sel.get("type", "")
        ).strip().lower()
        price = sel.get("price") or sel.get("odds") or sel.get("odd")
        line = sel.get("line") or sel.get("handicap")

        if label in OUTCOME_HOME_KEYWORDS:
            odd_1 = _format_odd(price)
        elif label in OUTCOME_DRAW_KEYWORDS:
            odd_x = _format_odd(price)
        elif label in OUTCOME_AWAY_KEYWORDS:
            odd_2 = _format_odd(price)
        elif label in OUTCOME_OVER_KEYWORDS:
            odd_over = _format_odd(price)
            if line is not None and not total_line:
                total_line = str(line)
        elif label in OUTCOME_UNDER_KEYWORDS:
            odd_under = _format_odd(price)
            if line is not None and not total_line:
                total_line = str(line)

    return odd_1, odd_x, odd_2, total_line, odd_over, odd_under


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class BetanoClient:
    """Thin wrapper around the Betano live odds API."""

    def __init__(self, domain: str = DEFAULT_DOMAIN):
        self.base_url = f"https://{domain}"
        self.session = requests.Session()
        h = dict(HEADERS)
        h["Origin"] = self.base_url
        h["Referer"] = f"{self.base_url}/"
        self.session.headers.update(h)

    def fetch_live_soccer(self) -> dict:
        url = f"{self.base_url}/api/sport/{SOCCER_SPORT_ID}/live/"
        params = {"tz": 0}
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

def parse_betano_response(data: dict) -> List[dict]:
    """Parse Betano live API response into standard event dicts."""
    results: List[dict] = []

    payload = data.get("data") or data
    blocks = (
        payload.get("blocks")
        or payload.get("events")
        or []
    )

    if isinstance(blocks, dict):
        blocks = list(blocks.values())

    for block in blocks:
        if not isinstance(block, dict):
            continue
        tournament = block.get("title") or block.get("name") or block.get("league", "")
        events = block.get("events") or block.get("matches") or []

        if not isinstance(events, list):
            # The block itself might be an event list at top level
            if "homeTeam" in block or "home" in block:
                ev = _parse_event(block, "")
                if ev:
                    results.append(ev)
            continue

        for event in events:
            ev = _parse_event(event, tournament)
            if ev:
                results.append(ev)

    return results


def _parse_event(event: dict, tournament: str) -> dict | None:
    """Parse a single Betano event into our standard format."""
    # Team names
    home_team = event.get("homeTeam") or event.get("home") or {}
    away_team = event.get("awayTeam") or event.get("away") or {}
    if isinstance(home_team, dict):
        team1 = home_team.get("name", "")
    else:
        team1 = str(home_team)
    if isinstance(away_team, dict):
        team2 = away_team.get("name", "")
    else:
        team2 = str(away_team)

    # Fall back to flat name fields
    if not team1:
        team1 = event.get("homeName") or event.get("team1", "")
    if not team2:
        team2 = event.get("awayName") or event.get("team2", "")

    if not team1 or not team2:
        return None

    tournament = tournament or event.get("tournament", {}).get("name", "")

    result = event.get("result") or event.get("score")
    home_score, away_score = _parse_score(result)

    time_field = event.get("time") or event.get("minute") or event.get("clock")
    match_time, match_status = _parse_match_time_and_status(time_field)

    selections = (
        event.get("selections")
        or event.get("markets")
        or event.get("odds")
        or []
    )
    odd_1, odd_x, odd_2, total_line, odd_over, odd_under = \
        _parse_selections(selections)

    start = event.get("startTime") or event.get("startDate") or event.get("date")
    scheduled_dt = None
    if start:
        try:
            scheduled_dt = datetime.datetime.fromisoformat(
                str(start).replace("Z", "+00:00")
            )
        except ValueError:
            pass

    return {
        "event_id": str(event.get("id", "")),
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
    output_dir: str = "match_database/betano",
    interval: float = DEFAULT_POLL_INTERVAL,
    domain: str = DEFAULT_DOMAIN,
) -> None:
    client = BetanoClient(domain=domain)
    writer = MatchCSVWriter(output_dir)

    log.info("Betano live SOCCER odds scraper started (domain: %s)", domain)
    log.info("  output dir : %s", os.path.abspath(output_dir))
    log.info("  interval   : %.1fs", interval)
    log.info("Press Ctrl+C to stop.\n")

    cycle = 0
    while True:
        t0 = time.monotonic()
        cycle += 1
        try:
            data = client.fetch_live_soccer()
            events = parse_betano_response(data)
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
        description="Betano live soccer odds scraper"
    )
    parser.add_argument("-o", "--output-dir", default="match_database/betano")
    parser.add_argument("-i", "--interval", type=float, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument(
        "--domain",
        default=DEFAULT_DOMAIN,
        help="Betano domain (default: www.betano.com.br). "
             "Also try: www.betano.pt, www.betano.gr, www.betano.ro",
    )
    args = parser.parse_args()
    try:
        run(output_dir=args.output_dir, interval=args.interval, domain=args.domain)
    except KeyboardInterrupt:
        log.info("\nStopped by user.")


if __name__ == "__main__":
    main()
