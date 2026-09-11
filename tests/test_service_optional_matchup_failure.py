from __future__ import annotations

import unittest

from dota_coach.data import Hero
from dota_coach.service import _load_matchups_fail_fast


class FakeClient:
    def __init__(self) -> None:
        self.timeout = 12.0
        self.attempts = 3


class RaisingData:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.source_status: dict[str, str] = {}
        self.calls: list[list[int]] = []

    def load_enemy_matchups(self, hero_ids: list[int]) -> None:
        self.calls.append(list(hero_ids))
        raise RuntimeError("optional endpoint/parser failure")


def hero(hero_id: int, name: str) -> Hero:
    return Hero(
        id=hero_id,
        name=name,
        primary_attr=None,
        complexity=1,
        roles=(),
        pub_pick=1_000,
        pub_win=500,
    )


class OptionalMatchupFailureRegression(unittest.TestCase):
    def test_loader_exception_degrades_instead_of_crashing_and_restores_http_policy(self) -> None:
        data = RaisingData()
        enemies = [hero(2, "Enemy A"), hero(3, "Enemy B")]
        warnings: list[str] = []

        _load_matchups_fail_fast(data, enemies, warnings)

        self.assertEqual(data.calls, [[2]])
        self.assertEqual(data.client.timeout, 12.0)
        self.assertEqual(data.client.attempts, 3)
        self.assertTrue(any("Enemy A" in warning and "недоступны" in warning for warning in warnings))
        self.assertTrue(any("1 matchup" in warning and "пропущено" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
