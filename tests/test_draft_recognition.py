from __future__ import annotations

import importlib.util
import unittest

from dota_coach.draft_layout import DraftLayout, LayoutError, NormalizedRect, SlotRegion
from dota_coach.draft_recognition import recognize_draft_slots
from dota_coach.portrait import PortraitIndex

VISION_AVAILABLE = bool(importlib.util.find_spec("numpy") and importlib.util.find_spec("PIL"))


@unittest.skipUnless(VISION_AVAILABLE, "portrait vision extras are not installed")
class DraftRecognitionTests(unittest.TestCase):
    @staticmethod
    def _portraits():
        from PIL import Image, ImageDraw

        red = Image.new("RGB", (160, 90), (150, 25, 25))
        draw = ImageDraw.Draw(red)
        draw.rectangle((12, 9, 64, 81), fill=(240, 200, 65))
        draw.ellipse((98, 25, 145, 78), fill=(225, 90, 55))

        blue = Image.new("RGB", (160, 90), (22, 45, 150))
        draw = ImageDraw.Draw(blue)
        draw.polygon([(8, 78), (78, 5), (150, 78)], fill=(70, 215, 225))
        draw.rectangle((64, 30, 98, 78), fill=(10, 22, 70))
        return red, blue

    @staticmethod
    def _layout() -> DraftLayout:
        return DraftLayout(
            name="synthetic-16-9",
            aspect_min=1.76,
            aspect_max=1.79,
            slots=(
                SlotRegion("radiant_pick_1", "pick", "radiant", NormalizedRect(0.05, 0.20, 0.35, 0.35)),
                SlotRegion("dire_pick_1", "pick", "dire", NormalizedRect(0.60, 0.20, 0.35, 0.35)),
            ),
        )

    def _index(self) -> PortraitIndex:
        red, blue = self._portraits()
        index = PortraitIndex()
        index.add_reference(1, "Red Hero", red)
        index.add_reference(2, "Blue Hero", blue)
        return index

    def _frame(self, left, right):
        from PIL import Image, ImageOps

        frame = Image.new("RGB", (320, 180), (12, 12, 12))
        boxes = self._layout().pixel_slots(320, 180)
        for slot_id, portrait in (("radiant_pick_1", left), ("dire_pick_1", right)):
            rect = boxes[slot_id]
            fitted = ImageOps.fit(portrait, (rect.width, rect.height))
            frame.paste(fitted, (rect.x, rect.y))
        return frame

    def test_recognizes_only_calibrated_slot_crops(self) -> None:
        red, blue = self._portraits()
        result = recognize_draft_slots(self._frame(red, blue), self._layout(), self._index())
        self.assertEqual([slot.hero_id for slot in result.slots], [1, 2])
        self.assertTrue(all(slot.accepted for slot in result.slots))
        self.assertEqual(len(result.accepted_slots), 2)

    def test_duplicate_hero_claim_fails_closed_for_weaker_slot(self) -> None:
        from PIL import ImageEnhance

        red, _ = self._portraits()
        darker = ImageEnhance.Brightness(red).enhance(0.72)
        result = recognize_draft_slots(self._frame(red, darker), self._layout(), self._index())
        accepted = result.accepted_slots
        unresolved = result.unresolved_slots
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].hero_id, 1)
        self.assertEqual(len(unresolved), 1)
        self.assertIn("duplicate", unresolved[0].reason)

    def test_wrong_aspect_ratio_is_rejected_before_classification(self) -> None:
        from PIL import Image

        with self.assertRaises(LayoutError):
            recognize_draft_slots(Image.new("RGB", (300, 300)), self._layout(), self._index())

    def test_constant_blank_slot_stays_unresolved(self) -> None:
        from PIL import Image

        blank = Image.new("RGB", (160, 90), (30, 30, 30))
        red, _ = self._portraits()
        result = recognize_draft_slots(self._frame(red, blank), self._layout(), self._index())
        blank_result = next(slot for slot in result.slots if slot.slot_id == "dire_pick_1")
        self.assertFalse(blank_result.accepted)
        self.assertIsNone(blank_result.hero_id)


if __name__ == "__main__":
    unittest.main()
