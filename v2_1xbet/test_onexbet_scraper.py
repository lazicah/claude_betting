"""Tests for the 1xBet v2 scraper helpers.

Run:
    python -m pytest v2_1xbet/test_onexbet_scraper.py -v
"""
import unittest
from v2_1xbet.onexbet_scraper import (
    _format_odd,
    _extract_score,
    _extract_match_time,
    _extract_match_status,
    _extract_odds,
    parse_response,
)


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(2.5), "2.50")

    def test_int(self):
        self.assertEqual(_format_odd(3), "3.00")

    def test_string(self):
        self.assertEqual(_format_odd("1.85"), "1.85")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")

    def test_empty(self):
        self.assertEqual(_format_odd(""), "")

    def test_invalid(self):
        self.assertEqual(_format_odd("xyz"), "")


class TestExtractScore(unittest.TestCase):
    def test_ss_field(self):
        self.assertEqual(_extract_score({"SS": "2:1"}), ("2", "1"))

    def test_sc_fs_field(self):
        self.assertEqual(_extract_score({"SC": {"FS": "0:3"}}), ("0", "3"))

    def test_no_score(self):
        self.assertEqual(_extract_score({}), ("", ""))

    def test_invalid_ss(self):
        self.assertEqual(_extract_score({"SS": ""}), ("", ""))


class TestExtractMatchTime(unittest.TestCase):
    def test_t_field(self):
        self.assertEqual(_extract_match_time({"T": 45}), "45")

    def test_t_field_string(self):
        self.assertEqual(_extract_match_time({"T": "67"}), "67")

    def test_no_time(self):
        self.assertEqual(_extract_match_time({}), "")


class TestExtractMatchStatus(unittest.TestCase):
    def test_period_1(self):
        self.assertEqual(_extract_match_status({"PE": 1}), "")

    def test_period_3(self):
        self.assertEqual(_extract_match_status({"PE": 3}), "ET1")

    def test_period_5(self):
        self.assertEqual(_extract_match_status({"PE": 5}), "PEN")

    def test_halftime(self):
        self.assertEqual(_extract_match_status({"ST": "HTIME"}), "HT")

    def test_no_status(self):
        self.assertEqual(_extract_match_status({}), "")


class TestExtractOdds(unittest.TestCase):
    def _make_event(self):
        return {
            "AE": [
                {
                    "T": 1,
                    "E": [
                        {"T": 1, "C": "1", "K": 1.85},
                        {"T": 2, "C": "X", "K": 3.60},
                        {"T": 3, "C": "2", "K": 4.20},
                    ],
                },
                {
                    "T": 17,
                    "P": "2.5",
                    "E": [
                        {"T": 9, "C": "Over", "K": 1.90},
                        {"T": 10, "C": "Under", "K": 1.90},
                    ],
                },
            ]
        }

    def test_1x2_odds(self):
        o1, ox, o2, line, over, under = _extract_odds(self._make_event())
        self.assertEqual(o1, "1.85")
        self.assertEqual(ox, "3.60")
        self.assertEqual(o2, "4.20")

    def test_total_odds(self):
        o1, ox, o2, line, over, under = _extract_odds(self._make_event())
        self.assertEqual(line, "2.5")
        self.assertEqual(over, "1.90")
        self.assertEqual(under, "1.90")

    def test_no_markets(self):
        o1, ox, o2, line, over, under = _extract_odds({})
        self.assertEqual(o1, "")
        self.assertEqual(ox, "")
        self.assertEqual(o2, "")


class TestParseResponse(unittest.TestCase):
    def _make_response(self):
        return {
            "Success": True,
            "Value": [
                {
                    "CI": 123,
                    "CN": "Premier League",
                    "RL": [
                        {
                            "I": 67890,
                            "O1": "Liverpool",
                            "O2": "Arsenal",
                            "SS": "1:0",
                            "T": 32,
                            "PE": 1,
                            "AE": [
                                {
                                    "T": 1,
                                    "E": [
                                        {"C": "1", "K": 1.85},
                                        {"C": "X", "K": 3.60},
                                        {"C": "2", "K": 4.20},
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }

    def test_basic_parse(self):
        events = parse_response(self._make_response())
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["team1"], "Liverpool")
        self.assertEqual(ev["team2"], "Arsenal")
        self.assertEqual(ev["tournament"], "Premier League")
        self.assertEqual(ev["home_score"], "1")
        self.assertEqual(ev["away_score"], "0")
        self.assertEqual(ev["match_time"], "32")
        self.assertEqual(ev["odd_1"], "1.85")
        self.assertEqual(ev["odd_X"], "3.60")
        self.assertEqual(ev["odd_2"], "4.20")

    def test_failed_response(self):
        events = parse_response({"Success": False})
        self.assertEqual(events, [])

    def test_empty_value(self):
        events = parse_response({"Success": True, "Value": []})
        self.assertEqual(events, [])

    def test_missing_teams(self):
        data = {"Success": True, "Value": [{"CN": "Liga", "RL": [{"I": 1}]}]}
        events = parse_response(data)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
