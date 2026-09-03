from __future__ import annotations

import unittest
from unittest.mock import patch

from dota_coach.data import Hero
from dota_coach.draft_layout import PixelRect
from dota_coach.draft_mvp import coach_recognized_draft, recognition_to_draft_input
from dota_coach.draft_recognition import DraftRecognition, SlotRecognition
from dota_coach.engine import Pick
from dota_coach.service import DraftResult


def _hero(hero_id: int, name: str) -> Hero:
    return Hero(
        id=hero_id,
        name=name,
        primary_attr="str",
        complexity=1,
        roles=("Disabler",),
        pub_pick=1000,
        pub_win=520,
    )


def _slot(
    slot_id: str,
    *,
    team: str,
    kind: str = "pick",
    hero_id: int | None = None,
    hero_name: str | None = None,
    accepted: bool = True,
) -> SlotRecognition:
    return SlotRecognition(
        slot_id=slot_id,
        kind=kind,
        team=team,
        rect=PixelRect(0, 0, 10, 10),
        hero_id=hero_id,
        hero_name=hero_name,
        similarity=0.9 if hero_id else 0.0,
        margin=0.08 if hero_id else 0.0,
        confidence=0.85 if hero_id else 0.0,
        accepted=accepted,
        reason="accepted" if accepted else "manual",
    )


class _FakeData:
    def __init__(self, heroes: list[Hero]) -> None:
        self.heroes_by_id = {hero.id: hero for hero in heroes}
        self.heroes = {hero.name: hero for hero in heroes}


class DraftMvpTests(unittest.TestCase):
    def test_only_accepted_pick_slots_feed_the_coach(self) -> None:
        axe = _hero(2, "Axe")
        cm = _hero(5, "Crystal Maiden")
        data = _FakeData([axe, cm])
        recognition = DraftRecognition(
            layout_name="test",
            slots=(
                _slot("r1", team="radiant", hero_id=axe.id, hero_name=axe.name),
                _slot("d1", team="dire", hero_id=cm.id, hero_name=cm.name),
                _slot("r2", team="radiant", hero_id=None, hero_name=None, accepted=False),
                _slot("b1", team="radiant", kind="ban", hero_id=cm.id, hero_name=cm.name),
                _slot("u1", team="unknown", hero_id=axe.id, hero_name=axe.name),
            ),
        )

        result = recognition_to_draft_input(data, recognition, "radiant")
        self.assertEqual([hero.name for hero in result.allies], ["Axe"])
        self.assertEqual([hero.name for hero in result.enemies], ["Crystal Maiden"])
        self.assertEqual({slot.slot_id for slot in result.manual_slots}, {"r2", "u1"})
        self.assertEqual([slot.slot_id for slot in result.ignored_bans], ["b1"])

    def test_perspective_inverts_allies_and_enemies(self) -> None:
        axe = _hero(2, "Axe")
        cm = _hero(5, "Crystal Maiden")
        data = _FakeData([axe, cm])
        recognition = DraftRecognition(
            layout_name="test",
            slots=(
                _slot("r1", team="radiant", hero_id=axe.id, hero_name=axe.name),
                _slot("d1", team="dire", hero_id=cm.id, hero_name=cm.name),
            ),
        )

        result = recognition_to_draft_input(data, recognition, "dire")
        self.assertEqual([hero.name for hero in result.allies], ["Crystal Maiden"])
        self.assertEqual([hero.name for hero in result.enemies], ["Axe"])

    def test_unknown_or_stale_hero_id_stays_manual(self) -> None:
        data = _FakeData([_hero(2, "Axe")])
        recognition = DraftRecognition(
            layout_name="test",
            slots=(_slot("r1", team="radiant", hero_id=999, hero_name="Stale"),),
        )
        result = recognition_to_draft_input(data, recognition, "radiant")
        self.assertEqual(result.allies, ())
        self.assertEqual([slot.slot_id for slot in result.manual_slots], ["r1"])

    def test_coach_bridge_appends_manual_fallback_warning(self) -> None:
        axe = _hero(2, "Axe")
        data = _FakeData([axe])
        recognition = DraftRecognition(
            layout_name="test",
            slots=(
                _slot("r1", team="radiant", hero_id=axe.id, hero_name=axe.name),
                _slot("d1", team="dire", hero_id=None, hero_name=None, accepted=False),
            ),
        )
        base = DraftResult(
            picks=(Pick("Axe", 61.0, 0.8, ("test",)),),
            tactics=("test tactic",),
            warnings=(),
            source_notes=("test source",),
        )

        with patch("dota_coach.draft_mvp.coach_draft", return_value=base) as mocked:
            result = coach_recognized_draft(data, recognition, "radiant", "3", limit=3, rank_tier="legend")

        mocked.assert_called_once()
        args, kwargs = mocked.call_args
        self.assertEqual([hero.name for hero in args[1]], ["Axe"])
        self.assertEqual(args[2], [])
        self.assertEqual(kwargs["limit"], 3)
        self.assertIn("manual/unresolved", result.coach.warnings[0])

    def test_invalid_perspective_fails_closed(self) -> None:
        data = _FakeData([])
        with self.assertRaises(ValueError):
            recognition_to_draft_input(data, DraftRecognition("test", ()), "unknown")


if __name__ == "__main__":
    unittest.main()
