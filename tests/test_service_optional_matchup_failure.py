from __future__ import annotations

import unittest

from dota_coach.data import Hero
from dota_coach.service import _load_matchups_fail_fast, coach_draft


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


def hero(hero_id: int, name: str, roles: tuple[str, ...] = ()) -> Hero:
    return Hero(
        id=hero_id,
        name=name,
        primary_attr=None,
        complexity=1,
        roles=roles,
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


class OptionalLaneRoleFailureRegression(unittest.TestCase):
    def _heroes(self) -> list[Hero]:
        return [
            hero(10, "Mid One", ("Nuker", "Escape")),
            hero(11, "Mid Two", ("Carry", "Nuker")),
            hero(12, "Support", ("Support", "Disabler")),
        ]

    def test_lane_loader_exception_degrades_without_second_attempt(self) -> None:
        class LaneFailureData:
            def __init__(self, heroes: list[Hero]) -> None:
                self.heroes = {value.name: value for value in heroes}
                self.heroes_by_id = {value.id: value for value in heroes}
                self.source_status: dict[str, str] = {}
                self.lane_calls = 0

            def load_lane_roles(self, lane_roles: list[int]) -> None:
                self.lane_calls += 1
                raise RuntimeError("unexpected optional lane-role parser failure")

            def candidate_win_rate_vs(self, candidate_id: int, enemy_id: int):
                return None

            def lane_role_sample(self, hero_id: int, lane_role: int):
                return None

            def lane_role_share(self, hero_id: int, lane_role: int):
                return None

        data = LaneFailureData(self._heroes())
        result = coach_draft(data, [], [], "mid", limit=2)

        self.assertEqual(data.lane_calls, 1)
        self.assertEqual(len(result.picks), 2)
        self.assertTrue(any("lane-role данные недоступны" in warning for warning in result.warnings))

    def test_lane_status_error_is_not_retried_inside_recommend(self) -> None:
        class LaneStatusData:
            def __init__(self, heroes: list[Hero]) -> None:
                self.heroes = {value.name: value for value in heroes}
                self.heroes_by_id = {value.id: value for value in heroes}
                self.source_status: dict[str, str] = {}
                self.lane_calls = 0

            def load_lane_roles(self, lane_roles: list[int]) -> None:
                self.lane_calls += 1
                for lane in lane_roles:
                    self.source_status[f"OpenDota lane role:{lane}"] = "error: timeout"

            def candidate_win_rate_vs(self, candidate_id: int, enemy_id: int):
                return None

            def lane_role_sample(self, hero_id: int, lane_role: int):
                return None

            def lane_role_share(self, hero_id: int, lane_role: int):
                return None

        data = LaneStatusData(self._heroes())
        result = coach_draft(data, [], [], "mid", limit=2)

        self.assertEqual(data.lane_calls, 1)
        self.assertEqual(len(result.picks), 2)
        self.assertEqual(sum("lane-role" in warning for warning in result.warnings), 3)


if __name__ == "__main__":
    unittest.main()
