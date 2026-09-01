import tempfile
import unittest
from pathlib import Path

from dota_coach.draft_layout import (
    DraftLayout,
    LayoutError,
    NormalizedRect,
    SlotRegion,
    load_layout,
    save_layout,
)


class DraftLayoutTests(unittest.TestCase):
    def test_normalized_rect_converts_to_pixels(self):
        rect = NormalizedRect(0.10, 0.20, 0.25, 0.30)
        pixels = rect.to_pixels(1920, 1080)
        self.assertEqual((pixels.x, pixels.y), (192, 216))
        self.assertEqual((pixels.width, pixels.height), (480, 324))

    def test_rect_must_stay_inside_frame(self):
        with self.assertRaises(LayoutError):
            NormalizedRect(0.9, 0.2, 0.2, 0.2)
        with self.assertRaises(LayoutError):
            NormalizedRect(0.1, 0.1, 0.0, 0.2)

    def test_layout_rejects_duplicate_slot_ids(self):
        rect = NormalizedRect(0.1, 0.1, 0.1, 0.1)
        with self.assertRaises(LayoutError):
            DraftLayout(
                "dup",
                1.7,
                1.8,
                (
                    SlotRegion("r1", "pick", "radiant", rect),
                    SlotRegion("r1", "pick", "dire", rect),
                ),
            )

    def test_aspect_guard_prevents_wrong_profile(self):
        layout = DraftLayout(
            "16x9 calibration",
            1.76,
            1.79,
            (SlotRegion("r1", "pick", "radiant", NormalizedRect(0.1, 0.1, 0.1, 0.1)),),
        )
        self.assertTrue(layout.supports_frame(1920, 1080))
        self.assertFalse(layout.supports_frame(1920, 1200))
        with self.assertRaises(LayoutError):
            layout.pixel_slots(1920, 1200)

    def test_json_roundtrip_and_file_io(self):
        layout = DraftLayout(
            "fixture",
            1.59,
            1.79,
            (
                SlotRegion("radiant_pick_1", "pick", "radiant", NormalizedRect(0.05, 0.1, 0.1, 0.1)),
                SlotRegion("dire_ban_1", "ban", "dire", NormalizedRect(0.8, 0.1, 0.08, 0.08)),
            ),
            anchors=(NormalizedRect(0.45, 0.02, 0.1, 0.05),),
        )
        restored = DraftLayout.from_json(layout.to_json())
        self.assertEqual(restored, layout)
        self.assertEqual(len(restored.pick_slots), 1)
        self.assertEqual(len(restored.ban_slots), 1)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "layout.json"
            save_layout(layout, path)
            self.assertEqual(load_layout(path), layout)


if __name__ == "__main__":
    unittest.main()
