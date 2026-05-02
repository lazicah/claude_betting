"""Tests for the 888Starz v2 scraper helpers.

Run:
    python -m pytest v2_888starz/test_starz888_scraper.py -v
"""
import unittest
from v2_888starz.starz888_scraper import _format_odd, _extract_score, parse_response


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(4.5), "4.50")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")


class TestExtractScore(unittest.TestCase):
    def test_ss(self):
        self.assertEqual(_extract_score({"SS": "3:0"}), ("3", "0"))

    def test_empty(self):
        self.assertEqual(_extract_score({}), ("", ""))


class TestParseResponse(unittest.TestCase):
    def test_basic(self):
        data = {
            "Success": True,
            "Value": [
                {
                    "CN": "Champions League",
                    "RL": [{"I": 1, "O1": "PSG", "O2": "Chelsea", "AE": []}],
                }
            ],
        }
        events = parse_response(data)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["team2"], "Chelsea")

    def test_failed(self):
        self.assertEqual(parse_response({"Success": False}), [])


if __name__ == "__main__":
    unittest.main()
