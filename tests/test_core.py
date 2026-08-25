import tempfile
import unittest

from dota_data import DotaData, FALLBACK_HERO_NAMES, parse_hero_stats
from engine import recommendations, strategy


class CoreTests(unittest.TestCase):
    def test_full_roster(self):
        self.assertEqual(len(FALLBACK_HERO_NAMES), 127)
        self.assertEqual(len(set(FALLBACK_HERO_NAMES)), 127)
        for required in ("Kez", "Ringmaster", "Largo", "Anti-Mage", "Wraith King"):
            self.assertIn(required, FALLBACK_HERO_NAMES)

    def test_recommendations_exclude_drafted_and_are_unique(self):
        with tempfile.TemporaryDirectory() as d:
            data = DotaData(d)
            picks = recommendations(data, ["Crystal Maiden"], ["Axe", "Puck"], "1 Carry", 10)
            names = [p.hero for p in picks]
            self.assertEqual(len(names), len(set(names)))
            self.assertNotIn("Crystal Maiden", names)
            self.assertNotIn("Axe", names)
            self.assertNotIn("Puck", names)
            self.assertEqual(len(names), 10)

    def test_role_filter_has_sensible_top_pick(self):
        with tempfile.TemporaryDirectory() as d:
            data = DotaData(d)
            for role in ("1 Carry", "2 Mid", "3 Offlane", "4 Support", "5 Hard Support"):
                pick = recommendations(data, [], [], role, 1)[0]
                self.assertGreaterEqual(pick.score, 60, (role, pick))

    def test_strategy_is_nonempty(self):
        with tempfile.TemporaryDirectory() as d:
            data = DotaData(d)
            text = strategy(data, ["Axe", "Lion"], ["Anti-Mage", "Puck"])
            self.assertIn("ТАКТИКА", text)
            self.assertGreater(len(text), 100)

    def test_parse_opendota_payload_and_winrate(self):
        payload = []
        for i, name in enumerate(FALLBACK_HERO_NAMES, start=1):
            payload.append({"id": i, "localized_name": name, "roles": ["Carry"], "1_pick": 100, "1_win": 55, "img": "/x.png", "icon": "/i.png"})
        parsed = parse_hero_stats(payload)
        self.assertEqual(len(parsed), 127)
        self.assertAlmostEqual(parsed["Axe"].win_rate, 0.55)

    def test_matchup_cache_affects_score(self):
        with tempfile.TemporaryDirectory() as d:
            data = DotaData(d)
            data.matchups = {"Axe": {"Ursa": {"games": 1000, "candidate_win_rate": 0.60}}}
            picks = recommendations(data, [], ["Axe"], "1 Carry", 127)
            by_name = {p.hero: p for p in picks}
            self.assertIn("статистически хорош против Axe", by_name["Ursa"].why)


if __name__ == "__main__":
    unittest.main()
