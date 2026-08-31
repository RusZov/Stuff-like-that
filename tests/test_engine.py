import unittest

from dota_coach.capture import WindowInfo, choose_dota_window
from dota_coach.data import DataSourceError, DotaData, Hero
from dota_coach.engine import (
    build_strategy,
    normalize_position,
    normalize_rank_tier,
    recommend,
    score_hero,
    validate_draft,
)


class FakeData:
    def __init__(self, heroes, matchups=None, lane_samples=None):
        self.heroes = {hero.name: hero for hero in heroes}
        self._matchups = matchups or {}
        self._lane_samples = lane_samples or {}

    def candidate_win_rate_vs(self, candidate_id, enemy_id):
        return self._matchups.get((candidate_id, enemy_id))

    def lane_role_sample(self, hero_id, lane_role):
        return self._lane_samples.get((hero_id, lane_role))

    def lane_role_share(self, hero_id, lane_role):
        total = sum(
            self._lane_samples.get((hero_id, role), (0, 0))[0]
            for role in (1, 2, 3)
        )
        if total <= 0:
            return None
        return self._lane_samples.get((hero_id, lane_role), (0, 0))[0] / total


class FlakyMatchupClient:
    def __init__(self):
        self.calls = 0

    def get_json(self, url):
        self.calls += 1
        if self.calls == 1:
            raise DataSourceError("temporary timeout")
        return [{"hero_id": 2, "games_played": 100, "wins": 55}]


def hero(hero_id, name, roles, wr=0.50, games=10000, rank_picks=(), rank_wins=()):
    return Hero(
        id=hero_id,
        name=name,
        primary_attr=None,
        complexity=1,
        roles=tuple(roles),
        pub_pick=games,
        pub_win=round(games * wr),
        rank_picks=tuple(rank_picks),
        rank_wins=tuple(rank_wins),
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

    def test_rank_aliases(self):
        self.assertIsNone(normalize_rank_tier("all"))
        self.assertEqual(normalize_rank_tier("legend"), 5)
        self.assertEqual(normalize_rank_tier(8), 8)
        with self.assertRaises(ValueError):
            normalize_rank_tier("wood")

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

    def test_invalid_draft_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_draft([self.axe], [self.axe])
        with self.assertRaises(ValueError):
            recommend(FakeData(self.heroes), [self.axe], [self.axe], "3")

    def test_real_matchup_signal_changes_score(self):
        neutral = FakeData(self.heroes)
        favorable = FakeData(self.heroes, {(self.puck.id, self.axe.id): (0.62, 2400)})
        base = score_hero(neutral, self.puck, [], [self.axe], "2")
        boosted = score_hero(favorable, self.puck, [], [self.axe], "2")
        self.assertGreater(boosted.score, base.score)
        self.assertTrue(any("Axe" in reason for reason in boosted.reasons))
        self.assertTrue(any("матчап" in reason for reason in boosted.reasons))

    def test_enemy_role_fallback_rewards_control_into_escape(self):
        data = FakeData(self.heroes)
        without_enemy = score_hero(data, self.lion, [self.cm], [], "4")
        into_puck = score_hero(data, self.lion, [self.cm], [self.puck], "4")
        self.assertGreater(into_puck.score, without_enemy.score)
        self.assertTrue(any("мобиль" in reason for reason in into_puck.reasons))

    def test_meta_signal_changes_score(self):
        weak = hero(20, "Weak Mid", ["Nuker", "Escape"], 0.46, 50000)
        strong = hero(21, "Strong Mid", ["Nuker", "Escape"], 0.54, 50000)
        data = FakeData([weak, strong])
        self.assertGreater(
            score_hero(data, strong, [], [], "2").score,
            score_hero(data, weak, [], [], "2").score,
        )

    def test_selected_rank_bucket_changes_meta_signal(self):
        rank_picks = [0, 0, 0, 0, 20000, 0, 0, 0]
        strong_wins = [0, 0, 0, 0, 11200, 0, 0, 0]
        weak_wins = [0, 0, 0, 0, 8800, 0, 0, 0]
        strong = hero(30, "Legend Strong", ["Nuker", "Escape"], 0.50, 40000, rank_picks, strong_wins)
        weak = hero(31, "Legend Weak", ["Nuker", "Escape"], 0.50, 40000, rank_picks, weak_wins)
        data = FakeData([strong, weak])
        strong_pick = score_hero(data, strong, [], [], "2", "legend")
        weak_pick = score_hero(data, weak, [], [], "2", "legend")
        self.assertGreater(strong_pick.score, weak_pick.score)
        self.assertTrue(any("Legend" in reason for reason in strong_pick.reasons))

    def test_lane_role_evidence_improves_mid_fit(self):
        mid_main = hero(40, "Mid Main", ["Nuker", "Escape"], 0.50, 30000)
        lane_flex = hero(41, "Lane Flex", ["Nuker", "Escape"], 0.50, 30000)
        samples = {
            (40, 1): (150, 75),
            (40, 2): (1700, 918),
            (40, 3): (150, 75),
            (41, 1): (900, 450),
            (41, 2): (100, 50),
            (41, 3): (1000, 500),
        }
        data = FakeData([mid_main, lane_flex], lane_samples=samples)
        specialist = score_hero(data, mid_main, [], [], "2")
        flex = score_hero(data, lane_flex, [], [], "2")
        self.assertGreater(specialist.score, flex.score)
        self.assertGreater(specialist.confidence, flex.confidence)
        self.assertTrue(any("lane-role" in reason for reason in specialist.reasons))

    def test_flexible_support_does_not_saturate_score(self):
        data = FakeData(self.heroes)
        lion = score_hero(data, self.lion, [], [], "4")
        self.assertLess(lion.score, 99.0)
        self.assertGreater(lion.score, 60.0)

    def test_strategy_uses_visible_composition(self):
        lines = build_strategy([self.axe, self.jug, self.cm], [self.puck, self.sf])
        text = " ".join(lines)
        self.assertIn("инициатор", text.lower())
        self.assertIn("мобиль", text.lower())

    def test_strategy_has_position_lane_plan(self):
        lines = build_strategy([self.jug, self.cm], [self.axe], "1")
        self.assertIn("фарм", lines[0].lower())

    def test_strategy_calls_out_greedy_multi_carry_enemy(self):
        second_carry = hero(42, "Greedy Core", ["Carry", "Escape"], 0.50)
        lines = build_strategy([self.axe, self.cm], [self.jug, second_carry], "3")
        self.assertTrue(any("жад" in line.lower() for line in lines))


class ParserTests(unittest.TestCase):
    def test_valve_parser(self):
        payload = {"result": {"data": {"heroes": [{"id": 1, "name_english_loc": "Anti-Mage"}]}}}
        rows = DotaData._parse_valve_heroes(payload)
        self.assertEqual(rows[0]["id"], 1)

    def test_current_opendota_pub_fields_are_preferred_for_all_public(self):
        row = {
            "pub_pick": 1000,
            "pub_win": 540,
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
        self.assertEqual((picks, wins), (1000, 540))

        rank_picks, rank_wins = DotaData._rank_pick_wins(row)
        self.assertEqual(rank_picks[0], 100)
        self.assertEqual(rank_wins[0], 51)
        self.assertEqual(rank_picks[7], 25)
        self.assertEqual(rank_wins[7], 12)

    def test_rank_bucket_sum_is_fallback_when_pub_fields_are_absent(self):
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
        self.assertEqual(DotaData._public_pick_win(row), (375, 194))

    def test_hero_rank_sample_uses_requested_bucket(self):
        value = hero(
            99,
            "Bracket Hero",
            ["Carry"],
            0.50,
            10000,
            [100, 200, 300, 400, 500, 600, 700, 800],
            [50, 100, 150, 200, 300, 300, 350, 400],
        )
        picks, wins = value.pick_win_for_rank(5)
        self.assertEqual((picks, wins), (500, 300))
        self.assertAlmostEqual(value.win_rate_for_rank(5), 0.60)

    def test_matchup_parser(self):
        rows = DotaData._parse_enemy_matchups([
            {"hero_id": 2, "games_played": 100, "wins": 55},
            {"hero_id": 3, "games_played": 0, "wins": 0},
        ])
        self.assertAlmostEqual(rows[2][0], 0.55)
        self.assertEqual(rows[2][1], 100)
        self.assertNotIn(3, rows)

    def test_enemy_endpoint_matchup_is_inverted_for_candidate(self):
        data = DotaData()
        data._enemy_matchups = {1: {2: (0.55, 100)}}
        candidate = data.candidate_win_rate_vs(2, 1)
        self.assertIsNotNone(candidate)
        self.assertAlmostEqual(candidate[0], 0.45)
        self.assertEqual(candidate[1], 100)

    def test_lane_role_parser_aggregates_time_buckets(self):
        rows = DotaData._parse_lane_roles(
            [
                {"hero_id": 2, "lane_role": 2, "time": 600, "games": "40", "wins": "22"},
                {"hero_id": 2, "lane_role": 2, "time": 1200, "games": "60", "wins": "31"},
                {"hero_id": 2, "lane_role": 1, "time": 1200, "games": "999", "wins": "999"},
                {"hero_id": 3, "lane_role": 2, "time": 600, "games": "0", "wins": "0"},
            ],
            expected_lane_role=2,
        )
        self.assertEqual(rows, {2: (100, 53)})

    def test_transient_matchup_error_is_retryable(self):
        client = FlakyMatchupClient()
        data = DotaData(client=client)
        data.load_enemy_matchups([1])
        self.assertEqual(data.matchup_count(1), 0)
        self.assertTrue(data.source_status["OpenDota matchups:1"].startswith("error:"))

        data.load_enemy_matchups([1])
        self.assertEqual(data.matchup_count(1), 1)
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
