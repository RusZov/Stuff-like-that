from __future__ import annotations

import unittest

from dota_coach.data import Hero
from dota_coach.engine import build_strategy, rank_label, score_hero


class FakeData:
    def __init__(self, heroes, matchups=None):
        self.heroes = {hero.name: hero for hero in heroes}
        self._matchups = matchups or {}

    def candidate_win_rate_vs(self, candidate_id, enemy_id):
        return self._matchups.get((candidate_id, enemy_id))

    def lane_role_sample(self, hero_id, lane_role):
        return None

    def lane_role_share(self, hero_id, lane_role):
        return None


def hero(hero_id: int, name: str, roles: tuple[str, ...] = ()) -> Hero:
    return Hero(
        id=hero_id,
        name=name,
        primary_attr=None,
        complexity=1,
        roles=roles,
        pub_pick=20_000,
        pub_win=10_000,
    )


class EngineV07Regressions(unittest.TestCase):
    def test_all_rank_label_means_all_public(self) -> None:
        self.assertEqual(rank_label(None), "All public")

    def test_same_matchup_quality_does_not_double_score_when_more_enemies_are_visible(self) -> None:
        candidate = hero(1, "Candidate", ("Nuker", "Escape"))
        enemy_a = hero(2, "Enemy A")
        enemy_b = hero(3, "Enemy B")
        data = FakeData(
            [candidate, enemy_a, enemy_b],
            {
                (candidate.id, enemy_a.id): (0.56, 1800),
                (candidate.id, enemy_b.id): (0.56, 1800),
            },
        )

        one_enemy = score_hero(data, candidate, [], [enemy_a], "mid")
        two_enemies = score_hero(data, candidate, [], [enemy_a, enemy_b], "mid")
        self.assertAlmostEqual(one_enemy.score, two_enemies.score, places=2)

    def test_tiny_matchup_sample_does_not_generate_counter_claim(self) -> None:
        candidate = hero(1, "Candidate", ("Nuker", "Escape"))
        enemy = hero(2, "Enemy")
        data = FakeData([candidate, enemy], {(candidate.id, enemy.id): (0.60, 5)})
        pick = score_hero(data, candidate, [], [enemy], "mid")
        self.assertFalse(any("матчап" in reason for reason in pick.reasons))

    def test_one_enemy_disabler_is_not_described_as_many_sources_of_control(self) -> None:
        enemy = hero(2, "Enemy Controller", ("Disabler",))
        text = " ".join(build_strategy([], [enemy])).lower()
        self.assertIn("есть надёжный контроль", text)
        self.assertNotIn("много источников контроля", text)


if __name__ == "__main__":
    unittest.main()
