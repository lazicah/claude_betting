"""Tests for the Bet9ja v2 scraper helpers.

Run:
    python -m pytest v2_bet9ja/test_bet9ja_scraper.py -v
"""
import unittest
from v2_bet9ja.bet9ja_scraper import (
    _format_odd,
    _millodds_to_decimal,
    _extract_line_from_label,
    _extract_score,
    _extract_live_time,
    _extract_live_status,
    _extract_odds_from_bet_offers,
    parse_soccer_events,
)


class TestFormatOdd(unittest.TestCase):
    def test_float(self):
        self.assertEqual(_format_odd(1.85), "1.85")

    def test_none(self):
        self.assertEqual(_format_odd(None), "")

    def test_invalid(self):
        self.assertEqual(_format_odd("x"), "")


class TestMillodds(unittest.TestCase):
    def test_18500(self):
        self.assertEqual(_millodds_to_decimal(18500), "18.50")

    def test_10000(self):
        self.assertEqual(_millodds_to_decimal(10000), "10.00")

    def test_invalid(self):
        self.assertEqual(_millodds_to_decimal("bad"), "")


class TestExtractLineFromLabel(unittest.TestCase):
    def test_over(self):
        self.assertEqual(_extract_line_from_label("Over 2.5"), "2.5")

    def test_under(self):
        self.assertEqual(_extract_line_from_label("Under 3.5"), "3.5")

    def test_no_number(self):
        self.assertEqual(_extract_line_from_label("Over"), "")


class TestExtractScore(unittest.TestCase):
    def test_score(self):
        ld = {"score": {"home": 1, "away": 0}}
        self.assertEqual(_extract_score(ld), ("1", "0"))

    def test_empty(self):
        self.assertEqual(_extract_score({}), ("", ""))


class TestExtractLiveTime(unittest.TestCase):
    def test_seconds(self):
        ld = {"currentTime": {"seconds": 1980}}  # 33 minutes
        self.assertEqual(_extract_live_time(ld), "33")

    def test_empty(self):
        self.assertEqual(_extract_live_time({}), "")


class TestExtractLiveStatus(unittest.TestCase):
    def test_halftime(self):
        ld = {"currentTime": {"period": "HALF_TIME"}}
        self.assertEqual(_extract_live_status(ld), "HT")

    def test_first_half(self):
        ld = {"currentTime": {"period": "FIRST_HALF"}}
        self.assertEqual(_extract_live_status(ld), "")

    def test_penalties(self):
        ld = {"currentTime": {"period": "PENALTIES"}}
        self.assertEqual(_extract_live_status(ld), "PEN")

    def test_empty(self):
        self.assertEqual(_extract_live_status({}), "")


class TestExtractOddsFromBetOffers(unittest.TestCase):
    def _make_offers(self):
        return [
            {
                "betOfferType": {"englishName": "Three Way"},
                "criterion": {"englishLabel": "Match"},
                "suspended": False,
                "outcomes": [
                    {"type": "OT_ONE", "oddsDecimal": 1.85, "status": "OPEN"},
                    {"type": "OT_CROSS", "oddsDecimal": 3.60, "status": "OPEN"},
                    {"type": "OT_TWO", "oddsDecimal": 4.20, "status": "OPEN"},
                ],
            },
            {
                "betOfferType": {"englishName": "Over/Under"},
                "criterion": {"englishLabel": "Total Goals"},
                "suspended": False,
                "outcomes": [
                    {
                        "type": "OT_OVER",
                        "englishLabel": "Over 2.5",
                        "oddsDecimal": 1.90,
                        "status": "OPEN",
                    },
                    {
                        "type": "OT_UNDER",
                        "englishLabel": "Under 2.5",
                        "oddsDecimal": 1.90,
                        "status": "OPEN",
                    },
                ],
            },
        ]

    def test_1x2(self):
        o1, ox, o2, line, over, under = _extract_odds_from_bet_offers(self._make_offers())
        self.assertEqual(o1, "1.85")
        self.assertEqual(ox, "3.60")
        self.assertEqual(o2, "4.20")

    def test_total(self):
        o1, ox, o2, line, over, under = _extract_odds_from_bet_offers(self._make_offers())
        self.assertEqual(line, "2.5")
        self.assertEqual(over, "1.90")
        self.assertEqual(under, "1.90")

    def test_suspended_skipped(self):
        offers = [
            {
                "betOfferType": {"englishName": "Three Way"},
                "criterion": {"englishLabel": "Match"},
                "suspended": True,
                "outcomes": [
                    {"type": "OT_ONE", "oddsDecimal": 1.85, "status": "OPEN"},
                ],
            }
        ]
        o1, ox, o2, _, _, _ = _extract_odds_from_bet_offers(offers)
        self.assertEqual(o1, "")

    def test_empty(self):
        o1, ox, o2, line, over, under = _extract_odds_from_bet_offers([])
        self.assertEqual(o1, "")


class TestParseSoccerEvents(unittest.TestCase):
    def _make_data(self):
        return {
            "events": [
                {
                    "event": {
                        "id": 1002869693,
                        "homeName": "Enyimba",
                        "awayName": "Kano Pillars",
                        "group": "NPFL",
                        "sport": "FOOTBALL",
                        "type": "MATCH",
                        "state": "STARTED",
                        "liveData": {
                            "score": {"home": 1, "away": 0},
                            "currentTime": {"seconds": 2100, "period": "SECOND_HALF"},
                        },
                        "start": "2026-05-02T15:00:00Z",
                    },
                    "betOffers": [],
                }
            ]
        }

    def test_basic(self):
        events = parse_soccer_events(self._make_data())
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["team1"], "Enyimba")
        self.assertEqual(ev["team2"], "Kano Pillars")
        self.assertEqual(ev["tournament"], "NPFL")
        self.assertEqual(ev["home_score"], "1")
        self.assertEqual(ev["away_score"], "0")
        self.assertEqual(ev["match_time"], "35")

    def test_non_football_skipped(self):
        data = {"events": [{"event": {"sport": "TENNIS", "homeName": "A", "awayName": "B"}, "betOffers": []}]}
        self.assertEqual(parse_soccer_events(data), [])

    def test_empty(self):
        self.assertEqual(parse_soccer_events({}), [])


if __name__ == "__main__":
    unittest.main()
