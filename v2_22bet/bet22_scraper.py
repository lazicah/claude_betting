"""
22Bet Live Soccer Odds Scraper
================================
Fetches live soccer match data (scores + odds) from the 22Bet LineFeed API.

22Bet runs on the same 1xSoftware/LineFeed platform as 1xBet, Melbet,
Betwinner, and 888Starz — only the domain changes.

API endpoint (live soccer):
    https://22bet.com/LineFeed/Get1x2_VZip
    ?sports=1&count=50&lng=en&tf=800000&tz=3&mode=4&getEmpty=true

Each live match gets its own CSV file:
    {team1}_vs_{team2}_{tournament}_22b_{date}.csv

Usage:
    python v2_22bet/bet22_scraper.py
    python v2_22bet/bet22_scraper.py --interval 5
    python v2_22bet/bet22_scraper.py -o my_data_dir

Note: 22Bet may be geo-restricted in some regions. A VPN may be required.
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
API_BASE = "https://22bet.com"
BOOKMAKER_TAG = "22b"

SOCCER_SPORT_ID = 1
LINEFEED_MODE_LIVE = 4
DEFAULT_POLL_INTERVAL = 5.0

MARKET_1X2 = 1
MARKET_TOTAL = 17

PERIOD_NAMES = {1: "", 2: "", 3: "ET1", 4: "ET2", 5: "PEN"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://22bet.com",
    "Referer": "https://22bet.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("22bet")

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
# API client
# ---------------------------------------------------------------------------

class Bet22Client:
    """Thin wrapper around the 22Bet LineFeed API."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_live_soccer(self) -> dict:
        url = f"{API_BASE}/LineFeed/Get1x2_VZip"
        params = {
            "sports": SOCCER_SPORT_ID,
            "count": 50,
            "lng": "en",
            "tf": 800000,
            "tz": 3,
            "mode": LINEFEED_MODE_LIVE,
            "getEmpty": "true",
        }
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Parsing  (identical logic to 1xBet — same API format)
# ---------------------------------------------------------------------------

def _extract_score(event: dict) -> tuple[str, str]:
    ss = event.get("SS", "")
    if ss and isinstance(ss, str) and ":" in ss:
        parts = ss.split(":")
        return parts[0].strip(), parts[1].strip()
    sc = event.get("SC") or {}
    fs = sc.get("FS", "")
    if fs and ":" in str(fs):
        parts = str(fs).split(":")
        return parts[0].strip(), parts[1].strip()
    return "", ""


def _extract_match_time(event: dict) -> str:
    t = event.get("T")
    if t is not None:
        return str(t)
    sc = event.get("SC") or {}
    tt = sc.get("TM") or sc.get("T")
    if tt is not None:
        return str(tt)
    return ""


def _extract_match_status(event: dict) -> str:
    period = event.get("PE")
    if period is not None:
        try:
            return PERIOD_NAMES.get(int(period), "")
        except (ValueError, TypeError):
            pass
    st = str(event.get("ST", "")).upper()
    if st in ("HTIME", "HT"):
        return "HT"
    if st in ("FT", "FINISHED", "ENDED"):
        return "FT"
    return ""


def _extract_odds(event: dict) -> tuple[str, str, str, str, str, str]:
    odd_1 = odd_x = odd_2 = ""
    total_line = odd_over = odd_under = ""
    for market in event.get("AE", []) or []:
        mtype = market.get("T")
        outcomes = market.get("E", []) or []
        if mtype == MARKET_1X2:
            for oc in outcomes:
                c = str(oc.get("C", "")).strip().upper()
                k = oc.get("K")
                if c == "1":
                    odd_1 = _format_odd(k)
                elif c == "X":
                    odd_x = _format_odd(k)
                elif c == "2":
                    odd_2 = _format_odd(k)
        elif mtype == MARKET_TOTAL:
            line = market.get("P") or market.get("HV")
            if line is not None:
                total_line = str(line)
            for oc in outcomes:
                c = str(oc.get("C", "")).strip().upper()
                k = oc.get("K")
                if "OVER" in c:
                    odd_over = _format_odd(k)
                elif "UNDER" in c:
                    odd_under = _format_odd(k)
    return odd_1, odd_x, odd_2, total_line, odd_over, odd_under


def _parse_event(ev: dict, tournament: str) -> dict | None:
    team1 = ev.get("O1", "")
    team2 = ev.get("O2", "")
    if not team1 or not team2:
        return None
    home_score, away_score = _extract_score(ev)
    match_time = _extract_match_time(ev)
    match_status = _extract_match_status(ev)
    odd_1, odd_x, odd_2, total_line, odd_over, odd_under = _extract_odds(ev)
    scheduled = ev.get("SD")
    if isinstance(scheduled, (int, float)) and scheduled > 0:
        try:
            ts = scheduled / 1000 if scheduled > 1_000_000_000_000 else scheduled
            scheduled_dt = datetime.datetime.fromtimestamp(ts)
        except (ValueError, OSError):
            scheduled_dt = None
    else:
        scheduled_dt = None
    return {
        "event_id": str(ev.get("I", "")),
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


def parse_response(data: dict) -> List[dict]:
    events: List[dict] = []
    if not data.get("Success"):
        return events
    for entry in data.get("Value", []) or []:
        if not isinstance(entry, dict):
            continue
        if "RL" in entry:
            champ_name = entry.get("CN", "")
            for ev in entry.get("RL", []) or []:
                parsed = _parse_event(ev, champ_name)
                if parsed:
                    events.append(parsed)
        elif "I" in entry and "O1" in entry:
            parsed = _parse_event(entry, "")
            if parsed:
                events.append(parsed)
    return events


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
    output_dir: str = "match_database/22bet",
    interval: float = DEFAULT_POLL_INTERVAL,
) -> None:
    client = Bet22Client()
    writer = MatchCSVWriter(output_dir)

    log.info("22Bet live SOCCER odds scraper started")
    log.info("  output dir : %s", os.path.abspath(output_dir))
    log.info("  interval   : %.1fs", interval)
    log.info("Press Ctrl+C to stop.\n")

    cycle = 0
    while True:
        t0 = time.monotonic()
        cycle += 1
        try:
            data = client.fetch_live_soccer()
            events = parse_response(data)
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
        description="22Bet live soccer odds scraper (LineFeed API)"
    )
    parser.add_argument("-o", "--output-dir", default="match_database/22bet")
    parser.add_argument("-i", "--interval", type=float, default=DEFAULT_POLL_INTERVAL)
    args = parser.parse_args()
    try:
        run(output_dir=args.output_dir, interval=args.interval)
    except KeyboardInterrupt:
        log.info("\nStopped by user.")


if __name__ == "__main__":
    main()
