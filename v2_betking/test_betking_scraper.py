"""Tests for the Betking v2 scraper helpers.

Run:
    python -m pytest v2_betking/test_betking_scraper.py -v
"""
import unittest
from v2_betking.betking_scraper import (
    _format_odd,
    _parse_score,
    _parse_match_time_status,
    _extract_odds,
    parse_betking_response,
)


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(1.95), "1.95")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")

    def test_string(self):
        self.assertEqual(_format_odd("2.00"), "2.00")


class TestParseScore(unittest.TestCase):
    def test_colon(self):
        self.assertEqual(_parse_score("1:0"), ("1", "0"))

    def test_dash(self):
        self.assertEqual(_parse_score("2-1"), ("2", "1"))

    def test_dict(self):
        self.assertEqual(_parse_score({"home": 0, "away": 2}), ("0", "2"))

    def test_none(self):
        self.assertEqual(_parse_score(None), ("", ""))


class TestParseMatchTimeStatus(unittest.TestCase):
    def test_minute(self):
        t, s = _parse_match_time_status({"minute": "34"})
        self.assertEqual(t, "34")
        self.assertEqual(s, "")

    def test_halftime_status(self):
        t, s = _parse_match_time_status({"statusName": "Half Time"})
        self.assertEqual(s, "HT")

    def test_empty(self):
        t, s = _parse_match_time_status({})
        self.assertEqual(t, "")
        self.assertEqual(s, "")


class TestExtractOdds(unittest.TestCase):
    def _make_event(self):
        return {
            "markets": [
                {
                    "name": "1x2",
                    "outcomes": [
                        {"label": "1", "odds": 1.80},
                        {"label": "X", "odds": 3.50},
                        {"label": "2", "odds": 4.00},
                    ],
                },
                {
                    "name": "total goals",
                    "line": 2.5,
                    "outcomes": [
                        {"label": "Over", "odds": 1.90},
                        {"label": "Under", "odds": 1.90},
                    ],
                },
            ]
        }

    def test_1x2(self):
        o1, ox, o2, _, _, _ = _extract_odds(self._make_event())
        self.assertEqual(o1, "1.80")
        self.assertEqual(ox, "3.50")
        self.assertEqual(o2, "4.00")

    def test_total(self):
        _, _, _, line, over, under = _extract_odds(self._make_event())
        self.assertEqual(line, "2.5")
        self.assertEqual(over, "1.90")
        self.assertEqual(under, "1.90")

    def test_empty(self):
        o1, ox, o2, line, over, under = _extract_odds({})
        self.assertEqual(o1, "")
        self.assertEqual(line, "")


class TestParseBetkingResponse(unittest.TestCase):
    def _make_data(self):
        return {
            "events": [
                {
                    "id": 1,
                    "homeTeam": "Enyimba FC",
                    "awayTeam": "Lobi Stars",
                    "leagueName": "NPFL",
                    "score": "1:0",
                    "minute": "40",
                    "markets": [],
                }
            ]
        }

    def test_basic(self):
        events = parse_betking_response(self._make_data())
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["team1"], "Enyimba FC")
        self.assertEqual(ev["team2"], "Lobi Stars")
        self.assertEqual(ev["home_score"], "1")
        self.assertEqual(ev["away_score"], "0")

    def test_list_input(self):
        data = [
            {
                "id": 2,
                "homeTeam": "A",
                "awayTeam": "B",
                "leagueName": "L",
                "markets": [],
            }
        ]
        events = parse_betking_response(data)
        self.assertEqual(len(events), 1)

    def test_empty(self):
        self.assertEqual(parse_betking_response({}), [])


if __name__ == "__main__":
    unittest.main()
