"""Tests for the Sportybet v2 scraper helpers.

Run:
    python -m pytest v2_sportybet/test_sportybet_scraper.py -v
"""
import unittest
from v2_sportybet.sportybet_scraper import (
    _format_odd,
    _played_seconds_to_time,
    _parse_match_status,
    _extract_line_from_specifier,
    _extract_odds_from_markets,
    parse_sportybet_response,
)


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(1.90), "1.90")

    def test_string(self):
        self.assertEqual(_format_odd("3.25"), "3.25")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")


class TestPlayedSecondsToTime(unittest.TestCase):
    def test_first_half(self):
        self.assertEqual(_played_seconds_to_time(1920), "32")

    def test_zero(self):
        self.assertEqual(_played_seconds_to_time(0), "0")

    def test_none(self):
        self.assertEqual(_played_seconds_to_time(None), "")


class TestParseMatchStatus(unittest.TestCase):
    def test_halftime(self):
        self.assertEqual(_parse_match_status("Half-Time"), "HT")

    def test_fulltime(self):
        self.assertEqual(_parse_match_status("Full-Time"), "FT")

    def test_penalties(self):
        self.assertEqual(_parse_match_status("Penalties"), "PEN")

    def test_running(self):
        self.assertEqual(_parse_match_status("1st half"), "")

    def test_empty(self):
        self.assertEqual(_parse_match_status(""), "")


class TestExtractLineFromSpecifier(unittest.TestCase):
    def test_2_5(self):
        self.assertEqual(_extract_line_from_specifier("total=2.5"), "2.5")

    def test_3(self):
        self.assertEqual(_extract_line_from_specifier("total=3"), "3")

    def test_empty(self):
        self.assertEqual(_extract_line_from_specifier(""), "")


class TestExtractOddsFromMarkets(unittest.TestCase):
    def _make_markets(self):
        return [
            {
                "id": "1",
                "specifier": "",
                "outcomes": [
                    {"desc": "1", "odds": "1.85", "isActive": 1},
                    {"desc": "X", "odds": "3.60", "isActive": 1},
                    {"desc": "2", "odds": "4.20", "isActive": 1},
                ],
            },
            {
                "id": "18",
                "specifier": "total=2.5",
                "outcomes": [
                    {"desc": "Over", "odds": "1.90", "isActive": 1},
                    {"desc": "Under", "odds": "1.90", "isActive": 1},
                ],
            },
        ]

    def test_1x2(self):
        o1, ox, o2, _, _, _ = _extract_odds_from_markets(self._make_markets())
        self.assertEqual(o1, "1.85")
        self.assertEqual(ox, "3.60")
        self.assertEqual(o2, "4.20")

    def test_total(self):
        _, _, _, line, over, under = _extract_odds_from_markets(self._make_markets())
        self.assertEqual(line, "2.5")
        self.assertEqual(over, "1.90")
        self.assertEqual(under, "1.90")

    def test_inactive_ignored(self):
        markets = [
            {
                "id": "1",
                "specifier": "",
                "outcomes": [
                    {"desc": "1", "odds": "1.85", "isActive": 0},
                    {"desc": "X", "odds": "3.60", "isActive": 0},
                    {"desc": "2", "odds": "4.20", "isActive": 0},
                ],
            }
        ]
        o1, ox, o2, _, _, _ = _extract_odds_from_markets(markets)
        self.assertEqual(o1, "")

    def test_empty(self):
        o1, ox, o2, line, over, under = _extract_odds_from_markets([])
        self.assertEqual(o1, "")
        self.assertEqual(line, "")


class TestParseSportybetResponse(unittest.TestCase):
    def _make_data(self):
        return {
            "data": {
                "sports": [
                    {
                        "id": "sr:sport:1",
                        "name": "Soccer",
                        "tournaments": [
                            {
                                "id": "sr:tournament:1",
                                "name": "Premier League",
                                "category": {"id": "sr:category:1", "name": "England"},
                                "events": [
                                    {
                                        "eventId": "sr:match:1",
                                        "homeTeamName": "Arsenal",
                                        "awayTeamName": "Chelsea",
                                        "homeScore": 1,
                                        "awayScore": 1,
                                        "matchStatus": "2nd half",
                                        "playedSeconds": 3600,
                                        "scheduledTime": "2026-05-02T16:00:00Z",
                                        "markets": [],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }

    def test_basic(self):
        events = parse_sportybet_response(self._make_data())
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["team1"], "Arsenal")
        self.assertEqual(ev["team2"], "Chelsea")
        self.assertEqual(ev["home_score"], "1")
        self.assertEqual(ev["away_score"], "1")
        self.assertEqual(ev["match_time"], "60")
        self.assertIn("Premier League", ev["tournament"])

    def test_empty(self):
        self.assertEqual(parse_sportybet_response({}), [])


if __name__ == "__main__":
    unittest.main()
