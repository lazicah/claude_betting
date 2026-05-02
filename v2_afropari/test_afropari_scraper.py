"""Tests for the Afropari v2 scraper helpers.

Run:
    python -m pytest v2_afropari/test_afropari_scraper.py -v
"""
import unittest
from v2_afropari.afropari_scraper import (
    _format_odd,
    _parse_score,
    _parse_time_status,
    _extract_odds,
    parse_afropari_response,
)


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(2.75), "2.75")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")

    def test_invalid(self):
        self.assertEqual(_format_odd("n/a"), "")


class TestParseScore(unittest.TestCase):
    def test_colon(self):
        self.assertEqual(_parse_score("1:0"), ("1", "0"))

    def test_dict(self):
        self.assertEqual(_parse_score({"home": 2, "away": 1}), ("2", "1"))

    def test_none(self):
        self.assertEqual(_parse_score(None), ("", ""))


class TestParseTimeStatus(unittest.TestCase):
    def test_minute(self):
        t, s = _parse_time_status({"minute": 55})
        self.assertEqual(t, "55")
        self.assertEqual(s, "")

    def test_halftime_status(self):
        t, s = _parse_time_status({"status": "halftime"})
        self.assertEqual(s, "HT")

    def test_empty(self):
        t, s = _parse_time_status({})
        self.assertEqual(t, "")
        self.assertEqual(s, "")


class TestExtractOdds(unittest.TestCase):
    def _make_event(self):
        return {
            "markets": [
                {
                    "name": "1x2",
                    "outcomes": [
                        {"label": "1", "price": 1.70},
                        {"label": "x", "price": 3.40},
                        {"label": "2", "price": 4.50},
                    ],
                },
                {
                    "name": "total goals over/under",
                    "line": 2.5,
                    "outcomes": [
                        {"label": "over", "price": 1.85},
                        {"label": "under", "price": 1.95},
                    ],
                },
            ]
        }

    def test_1x2(self):
        o1, ox, o2, _, _, _ = _extract_odds(self._make_event())
        self.assertEqual(o1, "1.70")
        self.assertEqual(ox, "3.40")
        self.assertEqual(o2, "4.50")

    def test_total(self):
        _, _, _, line, over, under = _extract_odds(self._make_event())
        self.assertEqual(line, "2.5")
        self.assertEqual(over, "1.85")
        self.assertEqual(under, "1.95")

    def test_empty(self):
        o1, ox, o2, line, over, under = _extract_odds({})
        self.assertEqual(o1, "")
        self.assertEqual(line, "")


class TestParseAfropariResponse(unittest.TestCase):
    def test_list_of_events(self):
        data = [
            {
                "id": 1,
                "homeTeam": "Asante Kotoko",
                "awayTeam": "Hearts of Oak",
                "tournament": "Ghana Premier League",
                "score": "0:0",
                "minute": 30,
                "markets": [],
            }
        ]
        events = parse_afropari_response(data)
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["team1"], "Asante Kotoko")
        self.assertEqual(ev["match_time"], "30")

    def test_dict_with_events(self):
        data = {
            "events": [
                {
                    "id": 2,
                    "homeTeam": "A",
                    "awayTeam": "B",
                    "markets": [],
                }
            ]
        }
        events = parse_afropari_response(data)
        self.assertEqual(len(events), 1)

    def test_empty(self):
        self.assertEqual(parse_afropari_response({}), [])

    def test_no_teams(self):
        data = [{"id": 1}]
        self.assertEqual(parse_afropari_response(data), [])


if __name__ == "__main__":
    unittest.main()
