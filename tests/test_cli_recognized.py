from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

from dota_coach.cli import _recognize_saved_draft, make_parser
from dota_coach.draft_mvp import RecognizedCoachResult, RecognizedDraftInput
from dota_coach.draft_recognition import DraftRecognition
from dota_coach.engine import Pick
from dota_coach.service import DraftResult


class CliRecognizedDraftTests(unittest.TestCase):
    def _data(self) -> SimpleNamespace:
        # The CLI intentionally requires broad portrait-reference coverage before
        # recognition is trusted. The reference loader itself is mocked here;
        # this only makes the test data large enough to satisfy that guard.
        heroes = {str(index): SimpleNamespace(id=index, name=f"Hero {index}") for index in range(1, 101)}
        return SimpleNamespace(heroes=heroes, heroes_by_id={hero.id: hero for hero in heroes.values()})

    def test_parser_accepts_recognized_coach_perspective(self) -> None:
        args = make_parser().parse_args(
            [
                "--recognize-draft",
                "draft.png",
                "--layout",
                "layout.json",
                "--portraits",
                "portraits",
                "--perspective",
                "radiant",
                "--role",
                "2",
                "--rank",
                "legend",
            ]
        )
        self.assertEqual(args.perspective, "radiant")
        self.assertEqual(args.recognize_draft, "draft.png")

    def test_recognized_draft_with_perspective_runs_coach(self) -> None:
        data = self._data()
        recognition = DraftRecognition(layout_name="measured-16x9", slots=())
        index = SimpleNamespace(hero_count=100)
        coach_result = DraftResult(
            picks=(Pick("Ember Spirit", 71.5, 0.82, ("test evidence",)),),
            tactics=("test tactic",),
            warnings=("test warning",),
            source_notes=("test source",),
        )
        bridge_result = RecognizedCoachResult(
            recognized=RecognizedDraftInput(allies=(), enemies=(), manual_slots=(), ignored_bans=()),
            coach=coach_result,
        )

        output = io.StringIO()
        with (
            patch("dota_coach.cli.load_layout", return_value=object()),
            patch("dota_coach.cli.PortraitIndex.from_directory", return_value=index),
            patch("dota_coach.cli.recognize_draft_slots", return_value=recognition),
            patch("dota_coach.cli.coach_recognized_draft", return_value=bridge_result) as coach,
            redirect_stdout(output),
        ):
            code = _recognize_saved_draft(
                data,
                "draft.png",
                "layout.json",
                "portraits",
                picks_only=False,
                perspective="radiant",
                position="2 Mid",
                limit=3,
                rank_tier=5,
            )

        self.assertEqual(code, 0)
        coach.assert_called_once_with(
            data,
            recognition,
            "radiant",
            "2 Mid",
            limit=3,
            rank_tier=5,
        )
        rendered = output.getvalue()
        self.assertIn("Perspective: radiant", rendered)
        self.assertIn("Recommendations", rendered)
        self.assertIn("Ember Spirit", rendered)
        self.assertIn("Tactics", rendered)

    def test_recognition_without_perspective_remains_inspect_only(self) -> None:
        data = self._data()
        recognition = DraftRecognition(layout_name="measured-16x9", slots=())
        index = SimpleNamespace(hero_count=100)

        with (
            patch("dota_coach.cli.load_layout", return_value=object()),
            patch("dota_coach.cli.PortraitIndex.from_directory", return_value=index),
            patch("dota_coach.cli.recognize_draft_slots", return_value=recognition),
            patch("dota_coach.cli.coach_recognized_draft", new=Mock()) as coach,
        ):
            code = _recognize_saved_draft(
                data,
                "draft.png",
                "layout.json",
                "portraits",
                picks_only=False,
                perspective=None,
                position="2 Mid",
                limit=5,
                rank_tier=None,
            )

        self.assertEqual(code, 0)
        coach.assert_not_called()


if __name__ == "__main__":
    unittest.main()
