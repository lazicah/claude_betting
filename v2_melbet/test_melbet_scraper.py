"""Tests for the Melbet v2 scraper helpers.

Run:
    python -m pytest v2_melbet/test_melbet_scraper.py -v
"""
import unittest
from v2_melbet.melbet_scraper import (
    _format_odd,
    _extract_score,
    _extract_match_status,
    parse_response,
)


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(1.85), "1.85")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")

    def test_invalid(self):
        self.assertEqual(_format_odd("abc"), "")


class TestExtractScore(unittest.TestCase):
    def test_ss_field(self):
        self.assertEqual(_extract_score({"SS": "2:1"}), ("2", "1"))

    def test_no_score(self):
        self.assertEqual(_extract_score({}), ("", ""))


class TestExtractMatchStatus(unittest.TestCase):
    def test_halftime(self):
        self.assertEqual(_extract_match_status({"ST": "HTIME"}), "HT")

    def test_period_5(self):
        self.assertEqual(_extract_match_status({"PE": 5}), "PEN")

    def test_no_status(self):
        self.assertEqual(_extract_match_status({}), "")


class TestParseResponse(unittest.TestCase):
    def _make_response(self):
        return {
            "Success": True,
            "Value": [
                {
                    "CN": "Serie A",
                    "RL": [
                        {
                            "I": 100,
                            "O1": "AC Milan",
                            "O2": "Inter Milan",
                            "SS": "0:0",
                            "T": 10,
                            "AE": [],
                        }
                    ],
                }
            ],
        }

    def test_basic(self):
        events = parse_response(self._make_response())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["team1"], "AC Milan")
        self.assertEqual(events[0]["tournament"], "Serie A")

    def test_failed(self):
        self.assertEqual(parse_response({"Success": False}), [])


if __name__ == "__main__":
    unittest.main()
