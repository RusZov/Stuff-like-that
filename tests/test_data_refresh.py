from __future__ import annotations

import unittest

from dota_coach.data import (
    DotaData,
    HttpJsonClient,
    OPENDOTA_HERO_STATS_URL,
    VALVE_HERO_LIST_URL,
    VALVE_PATCH_LIST_URL,
)


class RefreshingClient:
    def __init__(self) -> None:
        self.generation = 0
        self.invalidations = 0
        self.calls: list[tuple[int, str]] = []

    def invalidate(self, url=None) -> None:
        self.invalidations += 1
        self.generation += 1

    def get_json(self, url: str):
        self.calls.append((self.generation, url))
        if url == VALVE_HERO_LIST_URL:
            return {
                "result": {
                    "data": {
                        "heroes": [
                            {
                                "id": 1,
                                "name_english_loc": "Refresh Hero",
                                "primary_attr": 0,
                                "complexity": 1,
                            }
                        ]
                    }
                }
            }
        if url == OPENDOTA_HERO_STATS_URL:
            picks = 1000 + self.generation
            return [
                {
                    "id": 1,
                    "localized_name": "Refresh Hero",
                    "roles": ["Carry"],
                    "pub_pick": picks,
                    "pub_win": picks // 2,
                    "1_pick": picks,
                    "1_win": picks // 2,
                    "img": "/apps/dota2/images/dota_react/heroes/refresh_hero.png?",
                }
            ]
        if url == VALVE_PATCH_LIST_URL:
            return {
                "patches": [
                    {
                        "patch_number": f"test-{self.generation}",
                        "patch_timestamp": self.generation,
                    }
                ]
            }
        raise AssertionError(f"Unexpected URL {url}")


class HttpCacheTests(unittest.TestCase):
    def test_client_invalidate_one_or_all_cached_urls(self) -> None:
        client = HttpJsonClient()
        client._cache = {"a": 1, "b": 2}
        client.invalidate("a")
        self.assertEqual(client._cache, {"b": 2})
        client.invalidate()
        self.assertEqual(client._cache, {})

    def test_explicit_data_refresh_starts_a_new_snapshot(self) -> None:
        client = RefreshingClient()
        data = DotaData(client=client)

        data.refresh()
        first = data.resolve("Refresh Hero")
        self.assertIsNotNone(first)
        self.assertEqual(first.pub_pick, 1001)
        self.assertEqual(data.patch, "test-1")

        data.refresh()
        second = data.resolve("Refresh Hero")
        self.assertIsNotNone(second)
        self.assertEqual(second.pub_pick, 1002)
        self.assertEqual(data.patch, "test-2")
        self.assertEqual(client.invalidations, 2)

        # Each snapshot really queried all primary sources again.
        generations = {generation for generation, _ in client.calls}
        self.assertEqual(generations, {1, 2})
        self.assertEqual(len(client.calls), 6)


if __name__ == "__main__":
    unittest.main()
