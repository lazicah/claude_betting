"""Tests for the Betano v2 scraper helpers.

Run:
    python -m pytest v2_betano/test_betano_scraper.py -v
"""
import unittest
from v2_betano.betano_scraper import (
    _format_odd,
    _parse_match_time_and_status,
    _parse_score,
    _parse_selections,
    parse_betano_response,
)


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(2.05), "2.05")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")


class TestParseMatchTimeAndStatus(unittest.TestCase):
    def test_integer_minute(self):
        t, s = _parse_match_time_and_status(32)
        self.assertEqual(t, "32")
        self.assertEqual(s, "")

    def test_string_minute(self):
        t, s = _parse_match_time_and_status("45+2")
        self.assertEqual(t, "45+2")
        self.assertEqual(s, "")

    def test_halftime_string(self):
        t, s = _parse_match_time_and_status("HT")
        self.assertEqual(s, "HT")

    def test_dict(self):
        t, s = _parse_match_time_and_status({"minute": 67, "status": ""})
        self.assertEqual(t, "67")

    def test_none(self):
        t, s = _parse_match_time_and_status(None)
        self.assertEqual(t, "")
        self.assertEqual(s, "")


class TestParseScore(unittest.TestCase):
    def test_dict(self):
        self.assertEqual(_parse_score({"homeScore": 2, "awayScore": 1}), ("2", "1"))

    def test_string(self):
        self.assertEqual(_parse_score("1:0"), ("1", "0"))

    def test_none(self):
        self.assertEqual(_parse_score(None), ("", ""))


class TestParseSelections(unittest.TestCase):
    def _make_selections(self):
        return [
            {"name": "1", "price": 1.85},
            {"name": "X", "price": 3.60},
            {"name": "2", "price": 4.20},
            {"name": "Over", "price": 1.90, "line": 2.5},
            {"name": "Under", "price": 1.90, "line": 2.5},
        ]

    def test_1x2(self):
        o1, ox, o2, _, _, _ = _parse_selections(self._make_selections())
        self.assertEqual(o1, "1.85")
        self.assertEqual(ox, "3.60")
        self.assertEqual(o2, "4.20")

    def test_total(self):
        _, _, _, line, over, under = _parse_selections(self._make_selections())
        self.assertEqual(line, "2.5")
        self.assertEqual(over, "1.90")
        self.assertEqual(under, "1.90")

    def test_empty(self):
        o1, ox, o2, line, over, under = _parse_selections([])
        self.assertEqual(o1, "")
        self.assertEqual(line, "")


class TestParseBetanoResponse(unittest.TestCase):
    def _make_data(self):
        return {
            "data": {
                "blocks": [
                    {
                        "title": "Brasileirão",
                        "events": [
                            {
                                "id": 101,
                                "homeTeam": {"name": "Flamengo"},
                                "awayTeam": {"name": "Palmeiras"},
                                "result": {"homeScore": 1, "awayScore": 0},
                                "time": 55,
                                "selections": [
                                    {"name": "1", "price": 1.70},
                                    {"name": "X", "price": 3.50},
                                    {"name": "2", "price": 4.80},
                                ],
                            }
                        ],
                    }
                ]
            }
        }

    def test_basic(self):
        events = parse_betano_response(self._make_data())
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["team1"], "Flamengo")
        self.assertEqual(ev["team2"], "Palmeiras")
        self.assertEqual(ev["home_score"], "1")
        self.assertEqual(ev["away_score"], "0")
        self.assertEqual(ev["match_time"], "55")
        self.assertEqual(ev["odd_1"], "1.70")
        self.assertEqual(ev["tournament"], "Brasileirão")

    def test_empty(self):
        self.assertEqual(parse_betano_response({}), [])

    def test_no_teams(self):
        data = {"data": {"blocks": [{"title": "Liga", "events": [{"id": 1}]}]}}
        self.assertEqual(parse_betano_response(data), [])


if __name__ == "__main__":
    unittest.main()
