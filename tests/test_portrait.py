from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
import unittest

from dota_coach.data import Hero
from dota_coach.portrait import PortraitIndex, PortraitIndexError, hero_portrait_url

VISION_AVAILABLE = bool(importlib.util.find_spec("numpy") and importlib.util.find_spec("PIL"))


class PortraitUrlTests(unittest.TestCase):
    def _hero(self, path: str | None) -> Hero:
        return Hero(1, "Test Hero", "Strength", 1, ("Carry",), portrait_path=path)

    def test_relative_opendota_portrait_uses_steam_cdn(self) -> None:
        hero = self._hero("/apps/dota2/images/dota_react/heroes/test_hero.png?")
        self.assertEqual(
            hero_portrait_url(hero),
            "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/test_hero.png?",
        )

    def test_absolute_portrait_url_is_preserved(self) -> None:
        hero = self._hero("https://example.test/hero.png")
        self.assertEqual(hero_portrait_url(hero), "https://example.test/hero.png")

    def test_missing_portrait_path_returns_none(self) -> None:
        self.assertIsNone(hero_portrait_url(self._hero(None)))


@unittest.skipUnless(VISION_AVAILABLE, "portrait vision extras are not installed")
class PortraitIndexTests(unittest.TestCase):
    @staticmethod
    def _images():
        from PIL import Image, ImageDraw

        red = Image.new("RGB", (160, 90), (150, 25, 25))
        draw = ImageDraw.Draw(red)
        draw.rectangle((10, 8, 55, 82), fill=(245, 195, 70))
        draw.rectangle((92, 18, 148, 38), fill=(40, 15, 15))
        draw.ellipse((95, 48, 135, 84), fill=(230, 105, 65))

        blue = Image.new("RGB", (160, 90), (20, 45, 155))
        draw = ImageDraw.Draw(blue)
        draw.polygon([(5, 80), (75, 5), (150, 80)], fill=(65, 210, 230))
        draw.rectangle((65, 28, 95, 70), fill=(15, 20, 65))

        green = Image.new("RGB", (160, 90), (25, 125, 55))
        draw = ImageDraw.Draw(green)
        draw.ellipse((18, 10, 85, 78), fill=(190, 225, 90))
        draw.rectangle((103, 5, 145, 85), fill=(25, 65, 30))
        return red, blue, green

    def _index(self) -> PortraitIndex:
        red, blue, green = self._images()
        index = PortraitIndex()
        index.add_reference(1, "Red Hero", red)
        index.add_reference(2, "Blue Hero", blue)
        index.add_reference(3, "Green Hero", green)
        return index

    def test_same_portrait_is_accepted(self) -> None:
        red, _, _ = self._images()
        match = self._index().classify(red)
        self.assertEqual(match.hero_id, 1)
        self.assertTrue(match.accepted)
        self.assertGreater(match.similarity, 0.98)
        self.assertGreater(match.margin, 0.05)

    def test_brightness_change_keeps_identity(self) -> None:
        from PIL import ImageEnhance

        red, _, _ = self._images()
        darker = ImageEnhance.Brightness(red).enhance(0.58)
        match = self._index().classify(darker)
        self.assertEqual(match.hero_id, 1)
        self.assertGreater(match.similarity, 0.85)

    def test_near_duplicate_reference_is_rejected_by_margin(self) -> None:
        red, _, _ = self._images()
        index = PortraitIndex()
        index.add_reference(1, "Hero A", red)
        index.add_reference(2, "Hero B", red.copy())
        match = index.classify(red)
        self.assertFalse(match.accepted)
        self.assertAlmostEqual(match.margin, 0.0, places=4)

    def test_empty_index_fails_closed(self) -> None:
        red, _, _ = self._images()
        with self.assertRaises(PortraitIndexError):
            PortraitIndex().classify(red)

    def test_directory_index_uses_hero_ids(self) -> None:
        red, blue, _ = self._images()
        heroes = [
            Hero(11, "One", "Strength", 1, ("Carry",)),
            Hero(22, "Two", "Agility", 1, ("Carry",)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            red.save(root / "11.png")
            blue.save(root / "22.png")
            index = PortraitIndex.from_directory(heroes, root)
            self.assertEqual(index.hero_count, 2)
            self.assertEqual(index.classify(blue).hero_id, 22)


if __name__ == "__main__":
    unittest.main()
