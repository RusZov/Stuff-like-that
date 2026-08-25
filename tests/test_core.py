import tempfile
import unittest

from data_provider import DotaData, parse_opendota_hero_stats, parse_valve_matchups
from dota_data import FALLBACK_HERO_NAMES, parse_valve_hero_list, parse_valve_plus_stats
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


def fake_opendota_payload():
    return [
        {
            "id": i,
            "localized_name": name,
            "pub_pick": 1000,
            "pub_win": 520,
        }
        for i, name in enumerate(FALLBACK_HERO_NAMES, start=1)
    ]


def fake_valve_matchup_payload():
    # Mirrors the live shape: ranked_hero_data -> rank chunk -> hero_data rows.
    rows = []
    for hero_id in range(1, 101):
        first_other = hero_id + 1
        rates = [5200] * max(0, 127 - hero_id)
        rows.append(
            {
                "hero_id": hero_id,
                "win_rate": 5200,
                "first_other_hero_id": first_other,
                "ally_win_rate": [5000] * len(rates),
                "enemy_win_rate": rates,
            }
        )

    # Anti-Mage is id 4 and Axe is id 6 in this deterministic fake roster.
    anti_row = next(row for row in rows if row["hero_id"] == 4)
    anti_row["enemy_win_rate"][6 - anti_row["first_other_hero_id"]] = 6000
    return {"ranked_hero_data": [{"rank": 0, "hero_data": rows}]}


class CoreTests(unittest.TestCase):
    def test_full_roster(self):
        self.assertEqual(len(FALLBACK_HERO_NAMES), 127)
        self.assertEqual(len(set(FALLBACK_HERO_NAMES)), 127)
        for required in ("Kez", "Ringmaster", "Largo", "Anti-Mage", "Wraith King"):
            self.assertIn(required, FALLBACK_HERO_NAMES)

    def test_recommendations_exclude_drafted_and_are_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            data = DotaData(directory)
            picks = recommendations(data, ["Crystal Maiden"], ["Axe", "Puck"], "1 Carry", 10)
            names = [pick.hero for pick in picks]
            self.assertEqual(len(names), len(set(names)))
            self.assertNotIn("Crystal Maiden", names)
            self.assertNotIn("Axe", names)
            self.assertNotIn("Puck", names)
            self.assertEqual(len(names), 10)

    def test_role_filter_has_sensible_top_pick(self):
        with tempfile.TemporaryDirectory() as directory:
            data = DotaData(directory)
            for role in ("1 Carry", "2 Mid", "3 Offlane", "4 Support", "5 Hard Support"):
                pick = recommendations(data, [], [], role, 1)[0]
                self.assertGreaterEqual(pick.score, 60, (role, pick))

    def test_strategy_is_nonempty(self):
        with tempfile.TemporaryDirectory() as directory:
            data = DotaData(directory)
            text = strategy(data, ["Axe", "Lion"], ["Anti-Mage", "Puck"])
            self.assertIn("ТАКТИКА", text)
            self.assertGreater(len(text), 100)

    def test_opendota_meta_fallback_parser(self):
        heroes = parse_valve_hero_list(fake_hero_payload())
        parsed = parse_opendota_hero_stats(fake_opendota_payload(), heroes)
        self.assertAlmostEqual(parsed["Axe"].win_rate, 0.52)
        self.assertGreaterEqual(sum(hero.win_rate is not None for hero in parsed.values()), 127)

    def test_valve_plus_error_object_is_rejected(self):
        heroes = parse_valve_hero_list(fake_hero_payload())
        with self.assertRaises(ValueError):
            parse_valve_plus_stats({"success": 8, "error": "service unavailable"}, heroes)

    def test_valve_matchup_live_shape_and_inverse_direction(self):
        heroes = parse_valve_hero_list(fake_hero_payload())
        matrix = parse_valve_matchups(fake_valve_matchup_payload(), heroes)
        self.assertAlmostEqual(matrix["Axe"]["Anti-Mage"]["candidate_win_rate"], 0.60)
        self.assertAlmostEqual(matrix["Anti-Mage"]["Axe"]["candidate_win_rate"], 0.40)
        self.assertIsNone(matrix["Axe"]["Anti-Mage"]["games"])

    def test_valve_matchup_affects_score(self):
        heroes = parse_valve_hero_list(fake_hero_payload())
        matrix = parse_valve_matchups(fake_valve_matchup_payload(), heroes)
        with tempfile.TemporaryDirectory() as directory:
            data = DotaData(directory)
            data.heroes = heroes
            data.matchups = matrix
            picks = recommendations(data, [], ["Axe"], "1 Carry", 127)
            by_name = {pick.hero: pick for pick in picks}
            self.assertIn("Dota Plus", by_name["Anti-Mage"].why)


if __name__ == "__main__":
    unittest.main()
