import unittest

from dota_coach.capture import WindowInfo, choose_dota_window
from dota_coach.data import DataSourceError, DotaData, Hero
from dota_coach.engine import build_strategy, normalize_position, recommend, score_hero


class FakeData:
    def __init__(self, heroes, matchups=None):
        self.heroes = {hero.name: hero for hero in heroes}
        self._matchups = matchups or {}

    def candidate_win_rate_vs(self, candidate_id, enemy_id):
        return self._matchups.get((candidate_id, enemy_id))


class FlakyMatchupClient:
    def __init__(self):
        self.calls = 0

    def get_json(self, url):
        self.calls += 1
        if self.calls == 1:
            raise DataSourceError("temporary timeout")
        return [{"hero_id": 2, "games_played": 100, "wins": 55}]


def hero(hero_id, name, roles, wr=0.50, games=10000):
    return Hero(
        id=hero_id,
        name=name,
        primary_attr=None,
        complexity=1,
        roles=tuple(roles),
        pub_pick=games,
        pub_win=round(games * wr),
    )


class CaptureTests(unittest.TestCase):
    def test_dota_window_selection_uses_real_matching_window_and_largest_client(self):
        windows = [
            WindowInfo(10, "Discord", 1, 1920, 1080),
            WindowInfo(11, "Dota 2", 2, 1280, 720),
            WindowInfo(12, "Dota 2 - Vulkan", 2, 1920, 1080),
            WindowInfo(13, "Dota 2", 2, 0, 0),
        ]
        picked = choose_dota_window(windows)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.hwnd, 12)
        self.assertAlmostEqual(picked.aspect_ratio, 16 / 9)

    def test_dota_window_selection_does_not_fall_back_to_desktop_noise(self):
        windows = [WindowInfo(10, "Steam", 1, 1920, 1080)]
        self.assertIsNone(choose_dota_window(windows))


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.jug = hero(1, "Juggernaut", ["Carry", "Pusher", "Escape"], 0.515)
        self.puck = hero(2, "Puck", ["Nuker", "Escape", "Initiator", "Disabler"], 0.505)
        self.axe = hero(3, "Axe", ["Initiator", "Durable", "Disabler"], 0.51)
        self.cm = hero(4, "Crystal Maiden", ["Support", "Disabler", "Nuker"], 0.505)
        self.lion = hero(5, "Lion", ["Support", "Disabler", "Nuker", "Initiator"], 0.50)
        self.sf = hero(6, "Shadow Fiend", ["Carry", "Nuker"], 0.52)
        self.heroes = [self.jug, self.puck, self.axe, self.cm, self.lion, self.sf]

    def test_position_aliases(self):
        self.assertEqual(normalize_position("mid"), "2 Mid")
        self.assertEqual(normalize_position("5"), "5 Hard Support")

    def test_mid_prefers_mid_profile(self):
        data = FakeData(self.heroes)
        picks = recommend(data, [], [], "mid", 3)
        names = [pick.hero for pick in picks]
        self.assertIn("Puck", names[:2])
        self.assertNotEqual(names[0], "Crystal Maiden")

    def test_hard_support_penalizes_carry(self):
        data = FakeData(self.heroes)
        cm = score_hero(data, self.cm, [], [], "5")
        jug = score_hero(data, self.jug, [], [], "5")
        self.assertGreater(cm.score, jug.score)

    def test_carry_gate_penalizes_non_carry_profile(self):
        data = FakeData(self.heroes)
        jug = score_hero(data, self.jug, [], [], "1")
        puck = score_hero(data, self.puck, [], [], "1")
        self.assertGreater(jug.score, puck.score)
        self.assertGreater(jug.confidence, puck.confidence)

    def test_offlane_prefers_frontline_initiator(self):
        data = FakeData(self.heroes)
        axe = score_hero(data, self.axe, [], [], "3")
        sf = score_hero(data, self.sf, [], [], "3")
        self.assertGreater(axe.score, sf.score)

    def test_drafted_heroes_are_excluded(self):
        data = FakeData(self.heroes)
        picks = recommend(data, [self.cm], [self.axe], "1", 10)
        names = [pick.hero for pick in picks]
        self.assertNotIn("Crystal Maiden", names)
        self.assertNotIn("Axe", names)

    def test_real_matchup_signal_changes_score(self):
        neutral = FakeData(self.heroes)
        favorable = FakeData(self.heroes, {(self.puck.id, self.axe.id): (0.62, 2400)})
        base = score_hero(neutral, self.puck, [], [self.axe], "2")
        boosted = score_hero(favorable, self.puck, [], [self.axe], "2")
        self.assertGreater(boosted.score, base.score)
        self.assertTrue(any("Axe" in reason for reason in boosted.reasons))
        self.assertTrue(any("pro-матчап" in reason for reason in boosted.reasons))

    def test_meta_signal_changes_score(self):
        weak = hero(20, "Weak Mid", ["Nuker", "Escape"], 0.46, 50000)
        strong = hero(21, "Strong Mid", ["Nuker", "Escape"], 0.54, 50000)
        data = FakeData([weak, strong])
        self.assertGreater(
            score_hero(data, strong, [], [], "2").score,
            score_hero(data, weak, [], [], "2").score,
        )

    def test_strategy_uses_visible_composition(self):
        lines = build_strategy([self.axe, self.jug, self.cm], [self.puck, self.axe])
        text = " ".join(lines)
        self.assertIn("инициатор", text.lower())
        self.assertIn("мобиль", text.lower())

    def test_strategy_has_position_lane_plan(self):
        lines = build_strategy([self.jug, self.cm], [self.axe], "1")
        self.assertIn("фарм", lines[0].lower())


class ParserTests(unittest.TestCase):
    def test_valve_parser(self):
        payload = {"result": {"data": {"heroes": [{"id": 1, "name_english_loc": "Anti-Mage"}]}}}
        rows = DotaData._parse_valve_heroes(payload)
        self.assertEqual(rows[0]["id"], 1)

    def test_current_opendota_rank_buckets_are_aggregated(self):
        row = {
            "1_pick": 100,
            "1_win": 51,
            "2_pick": 200,
            "2_win": 104,
            "7_pick": 50,
            "7_win": 27,
            "8_pick": 25,
            "8_win": 12,
        }
        picks, wins = DotaData._public_pick_win(row)
        self.assertEqual(picks, 375)
        self.assertEqual(wins, 194)

    def test_legacy_pub_stats_remain_supported(self):
        self.assertEqual(
            DotaData._public_pick_win({"pub_pick": 1000, "pub_win": 530}),
            (1000, 530),
        )

    def test_matchup_parser(self):
        rows = DotaData._parse_enemy_matchups([
            {"hero_id": 2, "games_played": 100, "wins": 55},
            {"hero_id": 3, "games_played": 0, "wins": 0},
        ])
        self.assertAlmostEqual(rows[2][0], 0.55)
        self.assertEqual(rows[2][1], 100)
        self.assertNotIn(3, rows)

    def test_transient_matchup_error_is_retryable(self):
        client = FlakyMatchupClient()
        data = DotaData(client=client)
        data.load_enemy_matchups([1])
        self.assertEqual(data.matchup_count(1), 0)
        self.assertTrue(data.source_status["OpenDota pro matchups:1"].startswith("error:"))

        data.load_enemy_matchups([1])
        self.assertEqual(data.matchup_count(1), 1)
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
