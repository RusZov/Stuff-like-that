from __future__ import annotations

import unittest

from PIL import Image, ImageDraw, ImageEnhance

from dota_coach.draft_layout import DraftLayout, NormalizedRect
from dota_coach.draft_validation import (
    DraftAnchorProfile,
    DraftValidationError,
    calibrate_anchor_profile,
    validate_draft_frame,
)


def _reference_frame() -> Image.Image:
    image = Image.new("RGB", (640, 360), (18, 20, 24))
    draw = ImageDraw.Draw(image)

    draw.rectangle((32, 36, 160, 90), fill=(145, 40, 35))
    for x in range(40, 156, 18):
        draw.line((x, 40, x + 18, 86), fill=(240, 205, 80), width=3)

    draw.rectangle((448, 36, 608, 90), fill=(35, 80, 145))
    for y in range(42, 88, 10):
        draw.line((452, y, 604, y), fill=(90, 220, 230), width=3)

    draw.rectangle((256, 288, 384, 342), fill=(55, 105, 55))
    draw.ellipse((282, 296, 354, 338), outline=(220, 235, 160), width=5)
    draw.line((266, 332, 374, 298), fill=(230, 150, 70), width=4)
    return image


def _layout() -> DraftLayout:
    return DraftLayout(
        name="synthetic-16x9",
        aspect_min=1.76,
        aspect_max=1.79,
        slots=(),
        anchors=(
            NormalizedRect(0.05, 0.10, 0.20, 0.15),
            NormalizedRect(0.70, 0.10, 0.25, 0.15),
            NormalizedRect(0.40, 0.80, 0.20, 0.15),
        ),
    )


class DraftValidationTests(unittest.TestCase):
    def test_profile_round_trip_and_reference_frame_pass(self) -> None:
        layout = _layout()
        frame = _reference_frame()
        profile = calibrate_anchor_profile(frame, layout)
        restored = DraftAnchorProfile.from_json(profile.to_json())

        result = validate_draft_frame(frame, layout, restored)
        self.assertTrue(result.accepted)
        self.assertEqual(result.passed_anchors, 3)
        self.assertEqual(result.required_anchors, 3)
        self.assertTrue(all(item.similarity > 0.99 for item in result.evidence))

    def test_brightness_shift_keeps_fixed_anchor_evidence(self) -> None:
        layout = _layout()
        frame = _reference_frame()
        profile = calibrate_anchor_profile(frame, layout, min_similarity=0.74, min_pass_fraction=2 / 3)
        darker = ImageEnhance.Brightness(frame).enhance(0.72)

        result = validate_draft_frame(darker, layout, profile)
        self.assertTrue(result.accepted)
        self.assertGreaterEqual(result.passed_anchors, 2)

    def test_non_draft_flat_frame_is_rejected(self) -> None:
        layout = _layout()
        profile = calibrate_anchor_profile(_reference_frame(), layout, min_pass_fraction=2 / 3)
        unrelated = Image.new("RGB", (640, 360), (25, 25, 25))

        result = validate_draft_frame(unrelated, layout, profile)
        self.assertFalse(result.accepted)
        self.assertEqual(result.passed_anchors, 0)

    def test_wrong_aspect_is_rejected_before_anchor_matching(self) -> None:
        layout = _layout()
        profile = calibrate_anchor_profile(_reference_frame(), layout)
        wrong_aspect = Image.new("RGB", (640, 400), (20, 20, 20))

        result = validate_draft_frame(wrong_aspect, layout, profile)
        self.assertFalse(result.accepted)
        self.assertEqual(result.evidence, ())
        self.assertIn("aspect", result.reason)

    def test_calibration_requires_multiple_measured_anchors(self) -> None:
        layout = DraftLayout(
            name="bad",
            aspect_min=1.7,
            aspect_max=1.9,
            slots=(),
            anchors=(NormalizedRect(0.05, 0.10, 0.20, 0.15),),
        )
        with self.assertRaises(DraftValidationError):
            calibrate_anchor_profile(_reference_frame(), layout)


if __name__ == "__main__":
    unittest.main()
