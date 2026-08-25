import tempfile
import unittest

from dota_data import (
    DotaData,
    FALLBACK_HERO_NAMES,
    parse_valve_hero_list,
    parse_valve_matchups,
    parse_valve_plus_stats,
)
from engine import recommendations, strategy


def fake_hero_payload():
    return {
        "result": {
            "data": {
                "heroes": [
                    {
                        "id": i,
                        "name": f"npc_dota_hero_{i}",
                        "name_loc": name,
                        "name_english_loc": name,
                        "primary_attr": i % 4,
                        "complexity": 1 + (i % 3),
                    }
                    for i, name in enumerate(FALLBACK_HERO_NAMES, start=1)
                ]
            }
        }
    }


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

    def test_parse_valve_roster_and_plus_stats(self):
        heroes = parse_valve_hero_list(fake_hero_payload())
        self.assertGreaterEqual(len(heroes), 127)
        axe_id = heroes["Axe"].id
        payload = {
            "heroes": [
                {
                    "hero_id": hero.id,
                    "hero_data_per_chunk": [
                        {"rank_chunk": 0, "weeks": [{"win_percent": 5500, "pick_percent": 800, "ban_percent": 100}]}
                    ],
                }
                for hero in heroes.values()
                if hero.id is not None
            ]
        }
        parsed = parse_valve_plus_stats(payload, heroes)
        self.assertIsNotNone(axe_id)
        self.assertAlmostEqual(parsed["Axe"].win_rate, 0.55)

    def test_valve_matchup_matrix_affects_score_without_fake_games(self):
        heroes = parse_valve_hero_list(fake_hero_payload())
        ursa_id = heroes["Ursa"].id
        axe_id = heroes["Axe"].id
        self.assertIsNotNone(ursa_id)
        self.assertIsNotNone(axe_id)
        rates = [0] * 127
        rates[axe_id - 1] = 6000
        payload = {
            "ranked_hero_data": [
                {
                    "hero_id": ursa_id,
                    "win_rate": 5200,
                    "first_other_hero_id": 1,
                    "ally_win_rate": [0] * 127,
                    "enemy_win_rate": rates,
                }
            ]
        }
        matrix = parse_valve_matchups(payload, heroes)
        self.assertAlmostEqual(matrix["Axe"]["Ursa"]["candidate_win_rate"], 0.60)
        self.assertIsNone(matrix["Axe"]["Ursa"]["games"])

        with tempfile.TemporaryDirectory() as d:
            data = DotaData(d)
            data.heroes = heroes
            data.matchups = matrix
            picks = recommendations(data, [], ["Axe"], "1 Carry", 127)
            by_name = {p.hero: p for p in picks}
            self.assertIn("Dota Plus", by_name["Ursa"].why)


if __name__ == "__main__":
    unittest.main()
