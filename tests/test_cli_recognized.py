from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from contextlib import redirect_stderr, redirect_stdout

from dota_coach.cli import _recognize_saved_draft, make_parser
from dota_coach.draft_mvp import RecognizedCoachResult, RecognizedDraftInput
from dota_coach.draft_recognition import DraftRecognition
from dota_coach.engine import Pick
from dota_coach.service import DraftResult


class CliRecognizedDraftTests(unittest.TestCase):
    def _data(self) -> SimpleNamespace:
        heroes = {str(index): SimpleNamespace(id=index, name=f"Hero {index}") for index in range(1, 101)}
        return SimpleNamespace(heroes=heroes, heroes_by_id={hero.id: hero for hero in heroes.values()})

    def _accepted_validation(self) -> SimpleNamespace:
        return SimpleNamespace(
            accepted=True,
            passed_anchors=3,
            required_anchors=3,
            evidence=(),
            reason="accepted",
        )

    def test_parser_accepts_recognized_coach_perspective_and_anchor_profile(self) -> None:
        args = make_parser().parse_args(
            [
                "--recognize-draft",
                "draft.png",
                "--layout",
                "layout.json",
                "--portraits",
                "portraits",
                "--anchor-profile",
                "anchors.json",
                "--perspective",
                "radiant",
                "--role",
                "2",
                "--rank",
                "legend",
            ]
        )
        self.assertEqual(args.perspective, "radiant")
        self.assertEqual(args.anchor_profile, "anchors.json")
        self.assertEqual(args.recognize_draft, "draft.png")

    def test_perspective_refuses_unvalidated_frame(self) -> None:
        data = self._data()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = _recognize_saved_draft(
                data,
                "draft.png",
                "layout.json",
                "portraits",
                anchor_profile_path=None,
                picks_only=False,
                perspective="radiant",
                position="2 Mid",
                limit=3,
                rank_tier=5,
            )
        self.assertEqual(code, 2)
        self.assertIn("requires --anchor-profile", stderr.getvalue())

    def test_rejected_hud_stops_before_portrait_recognition(self) -> None:
        data = self._data()
        rejected = SimpleNamespace(
            accepted=False,
            passed_anchors=1,
            required_anchors=3,
            evidence=(),
            reason="only 1/3 required anchors matched",
        )
        stderr = io.StringIO()
        with (
            patch("dota_coach.cli.load_layout", return_value=object()),
            patch("dota_coach.cli.load_anchor_profile", return_value=object()),
            patch("dota_coach.cli.validate_draft_frame", return_value=rejected),
            patch("dota_coach.cli.PortraitIndex.from_directory", new=Mock()) as index_loader,
            patch("dota_coach.cli.recognize_draft_slots", new=Mock()) as recognize,
            redirect_stderr(stderr),
        ):
            code = _recognize_saved_draft(
                data,
                "draft.png",
                "layout.json",
                "portraits",
                anchor_profile_path="anchors.json",
                picks_only=False,
                perspective="radiant",
                position="2 Mid",
                limit=3,
                rank_tier=5,
            )
        self.assertEqual(code, 10)
        index_loader.assert_not_called()
        recognize.assert_not_called()
        self.assertIn("Recognition refused", stderr.getvalue())

    def test_recognized_draft_with_perspective_runs_coach_after_validation(self) -> None:
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
            patch("dota_coach.cli.load_anchor_profile", return_value=object()),
            patch("dota_coach.cli.validate_draft_frame", return_value=self._accepted_validation()),
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
                anchor_profile_path="anchors.json",
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
        self.assertIn("HUD validation: 3/3", rendered)
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
                anchor_profile_path=None,
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
