import unittest

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


class ServiceData:
    def __init__(self, heroes, matchups=None, lane_samples=None):
        self.heroes = {value.name: value for value in heroes}
        self.source_status = {}
        self._matchups = matchups or {}
        self._lane_samples = lane_samples or {}
        self.matchup_load_calls = []
        self.lane_load_calls = []

    def load_enemy_matchups(self, enemy_ids):
        self.matchup_load_calls.append(tuple(enemy_ids))
        for enemy_id in enemy_ids:
            self.source_status[f"OpenDota matchups:{enemy_id}"] = "ok"

    def load_lane_roles(self, lane_roles):
        self.lane_load_calls.append(tuple(lane_roles))
        for lane in lane_roles:
            self.source_status[f"OpenDota lane role:{lane}"] = "ok"

    def candidate_win_rate_vs(self, candidate_id, enemy_id):
        return self._matchups.get((candidate_id, enemy_id))

    def lane_role_sample(self, hero_id, lane_role):
        return self._lane_samples.get((hero_id, lane_role))

    def lane_role_share(self, hero_id, lane_role):
        total = sum(self._lane_samples.get((hero_id, role), (0, 0))[0] for role in (1, 2, 3))
        if total <= 0:
            return None
        return self._lane_samples.get((hero_id, lane_role), (0, 0))[0] / total


class DraftCoachServiceTests(unittest.TestCase):
    def setUp(self):
        self.puck = hero(1, "Puck", ["Nuker", "Escape", "Initiator", "Disabler"], 0.51)
        self.sf = hero(2, "Shadow Fiend", ["Carry", "Nuker"], 0.52)
        self.axe = hero(3, "Axe", ["Initiator", "Durable", "Disabler"], 0.51)
        self.cm = hero(4, "Crystal Maiden", ["Support", "Disabler", "Nuker"], 0.505)
        self.qop = hero(5, "Queen of Pain", ["Nuker", "Escape", "Carry"], 0.515)
        self.heroes = [self.puck, self.sf, self.axe, self.cm, self.qop]

    def test_service_preloads_enemy_matchups(self):
        data = ServiceData(self.heroes, {(self.puck.id, self.axe.id): (0.56, 900)})
        result = coach_draft(data, [self.cm], [self.axe], "mid", 3)
        self.assertTrue(data.matchup_load_calls)
        self.assertIn((self.axe.id,), data.matchup_load_calls)
        self.assertEqual(len(result.picks), 3)

    def test_user_facing_matchup_reason_is_labeled_pro_league(self):
        data = ServiceData(self.heroes, {(self.puck.id, self.axe.id): (0.60, 2400)})
        result = coach_draft(data, [self.cm], [self.axe], "mid", 5)
        puck = next(pick for pick in result.picks if pick.hero == "Puck")
        self.assertTrue(any("pro/league" in reason for reason in puck.reasons))
        self.assertTrue(any("pro/league" in note for note in result.source_notes))

    def test_low_confidence_extreme_score_is_shrunk_toward_neutral(self):
        sparse = hero(20, "Sparse Mid", ["Nuker", "Escape"], 0.60, 1)
        data = ServiceData([sparse, self.sf])
        result = coach_draft(data, [], [], "mid", 2)
        pick = next(item for item in result.picks if item.hero == "Sparse Mid")
        # The service should not expose the raw additive score as equally certain
        # when almost no statistical evidence exists.
        self.assertLess(pick.score, 80.0)

    def test_tactics_add_mobile_enemy_control_warning(self):
        mobile2 = hero(30, "Mobile Two", ["Escape", "Carry"], 0.50)
        allies = [self.sf]
        enemies = [self.puck, mobile2]
        data = ServiceData(self.heroes + [mobile2])
        result = coach_draft(data, allies, enemies, "mid", 2)
        text = " ".join(result.tactics).lower()
        self.assertIn("мало надёжного контроля", text)

    def test_optional_source_failure_becomes_warning_not_crash(self):
        class FailingData(ServiceData):
            def load_enemy_matchups(self, enemy_ids):
                for enemy_id in enemy_ids:
                    self.source_status[f"OpenDota matchups:{enemy_id}"] = "error: timeout"

        data = FailingData(self.heroes)
        result = coach_draft(data, [self.cm], [self.axe], "mid", 2)
        self.assertTrue(any("Axe" in warning for warning in result.warnings))
        self.assertEqual(len(result.picks), 2)


if __name__ == "__main__":
    unittest.main()
