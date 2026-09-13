import unittest
from types import SimpleNamespace

from dota_coach.data import Hero
from dota_coach.service import coach_draft


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


class LanePolicyData:
    def __init__(self, fail_lane=None, raise_lane=None):
        self.puck = hero(1, "Puck", ["Nuker", "Escape", "Initiator", "Disabler"], 0.51)
        self.sf = hero(2, "Shadow Fiend", ["Carry", "Nuker"], 0.52)
        self.axe = hero(3, "Axe", ["Initiator", "Durable", "Disabler"], 0.51)
        self.cm = hero(4, "Crystal Maiden", ["Support", "Disabler", "Nuker"], 0.505)
        heroes = [self.puck, self.sf, self.axe, self.cm]
        self.heroes = {value.name: value for value in heroes}
        self.heroes_by_id = {value.id: value for value in heroes}
        self.source_status = {}
        self.client = SimpleNamespace(timeout=10.0, attempts=3)
        self.fail_lane = fail_lane
        self.raise_lane = raise_lane
        self.lane_load_calls = []
        self.observed_policies = []

    def load_lane_roles(self, lane_roles):
        lane_roles = tuple(lane_roles)
        self.lane_load_calls.append(lane_roles)
        self.observed_policies.append((self.client.timeout, self.client.attempts))
        for lane in lane_roles:
            if lane == self.raise_lane:
                raise RuntimeError("parser regression")
            if lane == self.fail_lane:
                self.source_status[f"OpenDota lane role:{lane}"] = "error: timeout"
            else:
                self.source_status[f"OpenDota lane role:{lane}"] = "ok"

    def load_enemy_matchups(self, enemy_ids):
        for enemy_id in enemy_ids:
            self.source_status[f"OpenDota matchups:{enemy_id}"] = "ok"

    def lane_role_sample(self, hero_id, lane_role):
        return None

    def lane_role_share(self, hero_id, lane_role):
        return None

    def candidate_win_rate_vs(self, candidate_id, enemy_id):
        return None


class OptionalLanePolicyTests(unittest.TestCase):
    def test_timeout_stops_remaining_lanes_and_restores_client_policy(self):
        data = LanePolicyData(fail_lane=2)
        result = coach_draft(data, [data.cm], [data.axe], "mid", limit=2)

        self.assertEqual(data.lane_load_calls, [(1,), (2,)])
        self.assertEqual(data.observed_policies, [(3.0, 1), (3.0, 1)])
        self.assertEqual((data.client.timeout, data.client.attempts), (10.0, 3))
        self.assertTrue(any("lane-role 2" in warning for warning in result.warnings))
        self.assertTrue(any("пропущено" in warning for warning in result.warnings))
        self.assertEqual(len(result.picks), 2)

    def test_exception_stops_batch_and_does_not_escape(self):
        data = LanePolicyData(raise_lane=1)
        result = coach_draft(data, [data.cm], [data.axe], "mid", limit=2)

        self.assertEqual(data.lane_load_calls, [(1,)])
        self.assertEqual(data.observed_policies, [(3.0, 1)])
        self.assertEqual((data.client.timeout, data.client.attempts), (10.0, 3))
        self.assertTrue(any("lane-role 1" in warning for warning in result.warnings))
        self.assertEqual(len(result.picks), 2)

    def test_successful_lane_batch_queries_each_lane_once(self):
        data = LanePolicyData()
        result = coach_draft(data, [data.cm], [data.axe], "mid", limit=2)

        self.assertEqual(data.lane_load_calls, [(1,), (2,), (3,)])
        self.assertEqual(data.observed_policies, [(3.0, 1), (3.0, 1), (3.0, 1)])
        self.assertFalse(any("lane-role" in warning for warning in result.warnings))
        self.assertEqual(len(result.picks), 2)


if __name__ == "__main__":
    unittest.main()
