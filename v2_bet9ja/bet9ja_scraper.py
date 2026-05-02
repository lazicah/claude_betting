"""
Bet9ja Live Soccer Odds Scraper
=================================
Fetches live soccer match data (scores + odds) from the Kambi API that
powers Bet9ja's sportsbook.

Kambi is a B2B sports betting technology company whose platform is used
by many bookmakers (Bet9ja, Unibet, Rush Street Interactive, etc.).
The Bet9ja Kambi endpoint is publicly accessible — no VPN required.

API endpoint (live soccer):
    https://eu-offering-api.kambicdn.com/offering/v2018/bet9ja/listView/football.json
    ?lang=en_GB&market=NG&client_id=2&channel_id=1&ncid=1
    &useCombined=true&depth=3&live=true

Fields:
    events[].event.homeName   — home team name
    events[].event.awayName   — away team name
    events[].event.group      — competition/tournament name
    events[].event.liveData.score.{home,away}
    events[].event.liveData.currentTime.{seconds,period}
    events[].betOffers[].outcomes[].{oddsDecimal,odds,label,type}

Odds format:
    oddsDecimal (preferred) — decimal odds like 1.85
    odds        (fallback)  — millodds like 18500 → divide by 1000 to get 1.850

Each live match gets its own CSV file:
    {team1}_vs_{team2}_{tournament}_b9j_{date}.csv

Usage:
    python v2_bet9ja/bet9ja_scraper.py
    python v2_bet9ja/bet9ja_scraper.py --interval 5
    python v2_bet9ja/bet9ja_scraper.py -o my_data_dir
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
KAMBI_API_BASE = "https://eu-offering-api.kambicdn.com"
KAMBI_CLIENT_ID = "bet9ja"
BOOKMAKER_TAG = "b9j"

DEFAULT_POLL_INTERVAL = 5.0

# Kambi criterion IDs for market types
# Three-way (1X2) markets are identified by betOfferType name containing "Way"
# Over/Under markets contain "Over/Under" or "Total Goals"
MATCH_RESULT_KEYWORDS = {"three way", "match", "1x2", "full time result"}
TOTAL_GOALS_KEYWORDS = {"over/under", "total goals", "total"}

# Kambi outcome types
OT_ONE = "OT_ONE"       # Home win
OT_CROSS = "OT_CROSS"   # Draw
OT_TWO = "OT_TWO"       # Away win
OT_OVER = "OT_OVER"     # Over
OT_UNDER = "OT_UNDER"   # Under

# Kambi period identifiers → our status strings
PERIOD_MAP = {
    "FIRST_HALF": "",         # Running — show only minute
    "SECOND_HALF": "",
    "HALF_TIME": "HT",
    "EXTRA_TIME_FIRST_HALF": "ET1",
    "EXTRA_TIME_HALF_TIME": "ETHT",
    "EXTRA_TIME_SECOND_HALF": "ET2",
    "PENALTIES": "PEN",
    "FULL_TIME": "FT",
    "INTERRUPTED": "INT",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.bet9ja.com",
    "Referer": "https://www.bet9ja.com/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bet9ja")

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


def _millodds_to_decimal(millodds) -> str:
    """Convert Kambi millodds (e.g. 18500) to decimal odds (e.g. 1.85)."""
    try:
        return _format_odd(int(millodds) / 1000.0)
    except (ValueError, TypeError):
        return ""


def _extract_odd_from_outcome(oc: dict) -> str:
    """Extract decimal odds from a Kambi outcome, preferring oddsDecimal."""
    if "oddsDecimal" in oc and oc["oddsDecimal"] is not None:
        return _format_odd(oc["oddsDecimal"])
    if "odds" in oc and oc["odds"] is not None:
        return _millodds_to_decimal(oc["odds"])
    return ""


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class KambiClient:
    """Thin wrapper around the Kambi offering API for Bet9ja."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_live_soccer(self) -> dict:
        """Fetch all live soccer events from Kambi."""
        url = (
            f"{KAMBI_API_BASE}/offering/v2018/{KAMBI_CLIENT_ID}"
            "/listView/football.json"
        )
        params = {
            "lang": "en_GB",
            "market": "NG",
            "client_id": 2,
            "channel_id": 1,
            "ncid": 1,
            "useCombined": "true",
            "depth": 3,
            "live": "true",
        }
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _extract_live_time(live_data: dict) -> str:
    """Return match minute as a string from Kambi liveData."""
    ct = live_data.get("currentTime") or {}
    seconds = ct.get("seconds")
    if seconds is not None:
        try:
            return str(int(seconds) // 60)
        except (ValueError, TypeError):
            pass
    # Sometimes the time is in liveData directly
    minute = live_data.get("matchClock", {}).get("minute")
    if minute is not None:
        return str(minute)
    return ""


def _extract_live_status(live_data: dict) -> str:
    """Return status string (HT, FT, PEN …) from Kambi liveData."""
    ct = live_data.get("currentTime") or {}
    period = ct.get("period", "")
    return PERIOD_MAP.get(period, "")


def _extract_score(live_data: dict) -> tuple[str, str]:
    """Return (home_score, away_score) from Kambi liveData."""
    score = live_data.get("score") or {}
    home = score.get("home", "")
    away = score.get("away", "")
    return str(home) if home != "" else "", str(away) if away != "" else ""


def _extract_line_from_label(label: str) -> str:
    """Extract numeric line from an outcome label like 'Over 2.5'."""
    m = re.search(r"\d+(?:\.\d+)?", label)
    return m.group(0) if m else ""


def _extract_odds_from_bet_offers(bet_offers: list) -> tuple[str, str, str, str, str, str]:
    """Parse 1X2 and total goals markets from Kambi betOffers array."""
    odd_1 = odd_x = odd_2 = ""
    total_line = odd_over = odd_under = ""

    for offer in bet_offers:
        offer_type = offer.get("betOfferType") or {}
        type_name = (
            offer_type.get("englishName", "") or offer_type.get("name", "")
        ).lower()
        criterion = offer.get("criterion") or {}
        criterion_label = (
            criterion.get("englishLabel", "") or criterion.get("label", "")
        ).lower()

        outcomes = offer.get("outcomes", []) or []
        is_suspended = offer.get("suspended", False)
        if is_suspended:
            continue

        # Identify 1X2 (Three Way) market
        if any(kw in type_name or kw in criterion_label
               for kw in MATCH_RESULT_KEYWORDS):
            for oc in outcomes:
                if oc.get("status") == "CLOSED":
                    continue
                otype = oc.get("type", "")
                val = _extract_odd_from_outcome(oc)
                if otype == OT_ONE:
                    odd_1 = val
                elif otype == OT_CROSS:
                    odd_x = val
                elif otype == OT_TWO:
                    odd_2 = val

        # Identify Over/Under (Total Goals) market
        elif any(kw in type_name or kw in criterion_label
                 for kw in TOTAL_GOALS_KEYWORDS):
            for oc in outcomes:
                if oc.get("status") == "CLOSED":
                    continue
                otype = oc.get("type", "")
                label = oc.get("englishLabel", "") or oc.get("label", "")
                val = _extract_odd_from_outcome(oc)
                if otype == OT_OVER:
                    odd_over = val
                    if not total_line:
                        total_line = _extract_line_from_label(label)
                elif otype == OT_UNDER:
                    odd_under = val

    return odd_1, odd_x, odd_2, total_line, odd_over, odd_under


def parse_soccer_events(data: dict) -> List[dict]:
    """Parse Kambi API response into a list of event dicts."""
    results: List[dict] = []
    for entry in data.get("events", []) or []:
        ev = entry.get("event") or {}
        if ev.get("sport", "").upper() != "FOOTBALL":
            continue
        if ev.get("type", "").upper() not in ("MATCH", ""):
            continue

        team1 = ev.get("homeName", "")
        team2 = ev.get("awayName", "")
        if not team1 or not team2:
            continue

        tournament = (
            ev.get("group", "")
            or ev.get("league", "")
            or ev.get("path", [{}])[-1].get("name", "")
        )

        live_data = ev.get("liveData") or {}
        match_time = _extract_live_time(live_data)
        match_status = _extract_live_status(live_data)
        home_score, away_score = _extract_score(live_data)

        bet_offers = entry.get("betOffers", []) or []
        odd_1, odd_x, odd_2, total_line, odd_over, odd_under = \
            _extract_odds_from_bet_offers(bet_offers)

        start = ev.get("start", "")
        scheduled_dt = None
        if start:
            try:
                scheduled_dt = datetime.datetime.fromisoformat(
                    start.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        results.append({
            "event_id": str(ev.get("id", "")),
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
        })

    return results


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
    output_dir: str = "match_database/bet9ja",
    interval: float = DEFAULT_POLL_INTERVAL,
) -> None:
    client = KambiClient()
    writer = MatchCSVWriter(output_dir)

    log.info("Bet9ja live SOCCER odds scraper started (Kambi API)")
    log.info("  output dir : %s", os.path.abspath(output_dir))
    log.info("  interval   : %.1fs", interval)
    log.info("Press Ctrl+C to stop.\n")

    cycle = 0
    while True:
        t0 = time.monotonic()
        cycle += 1
        try:
            data = client.fetch_live_soccer()
            events = parse_soccer_events(data)
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
        description="Bet9ja live soccer odds scraper (Kambi API)"
    )
    parser.add_argument("-o", "--output-dir", default="match_database/bet9ja")
    parser.add_argument("-i", "--interval", type=float, default=DEFAULT_POLL_INTERVAL)
    args = parser.parse_args()
    try:
        run(output_dir=args.output_dir, interval=args.interval)
    except KeyboardInterrupt:
        log.info("\nStopped by user.")


if __name__ == "__main__":
    main()
