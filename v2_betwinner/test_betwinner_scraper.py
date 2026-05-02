"""Tests for the Betwinner v2 scraper helpers.

Run:
    python -m pytest v2_betwinner/test_betwinner_scraper.py -v
"""
import unittest
from v2_betwinner.betwinner_scraper import _format_odd, _extract_score, parse_response


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(2.10), "2.10")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")


class TestExtractScore(unittest.TestCase):
    def test_ss(self):
        self.assertEqual(_extract_score({"SS": "0:1"}), ("0", "1"))

    def test_empty(self):
        self.assertEqual(_extract_score({}), ("", ""))


class TestParseResponse(unittest.TestCase):
    def test_basic(self):
        data = {
            "Success": True,
            "Value": [
                {
                    "CN": "La Liga",
                    "RL": [{"I": 1, "O1": "Barcelona", "O2": "Real Madrid", "AE": []}],
                }
            ],
        }
        events = parse_response(data)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["team1"], "Barcelona")

    def test_failed(self):
        self.assertEqual(parse_response({"Success": False}), [])


if __name__ == "__main__":
    unittest.main()
