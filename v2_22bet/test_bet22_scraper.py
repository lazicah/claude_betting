"""Tests for the 22Bet v2 scraper helpers.

Run:
    python -m pytest v2_22bet/test_bet22_scraper.py -v
"""
import unittest
from v2_22bet.bet22_scraper import _format_odd, _extract_score, parse_response


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(3.25), "3.25")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")


class TestExtractScore(unittest.TestCase):
    def test_ss(self):
        self.assertEqual(_extract_score({"SS": "1:2"}), ("1", "2"))

    def test_empty(self):
        self.assertEqual(_extract_score({}), ("", ""))


class TestParseResponse(unittest.TestCase):
    def test_basic(self):
        data = {
            "Success": True,
            "Value": [
                {
                    "CN": "Bundesliga",
                    "RL": [{"I": 1, "O1": "Bayern", "O2": "Dortmund", "AE": []}],
                }
            ],
        }
        events = parse_response(data)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["team1"], "Bayern")

    def test_failed(self):
        self.assertEqual(parse_response({"Success": False}), [])


if __name__ == "__main__":
    unittest.main()
