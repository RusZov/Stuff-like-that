from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VALVE_HERO_LIST_URL = "https://www.dota2.com/datafeed/herolist?language=english"
VALVE_PATCH_LIST_URL = "https://www.dota2.com/datafeed/patchnoteslist"
OPENDOTA_HERO_STATS_URL = "https://api.opendota.com/api/heroStats"
OPENDOTA_MATCHUPS_URL = "https://api.opendota.com/api/heroes/{hero_id}/matchups"


class DataSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Hero:
    id: int
    name: str
    primary_attr: str | None
    complexity: int | None
    roles: tuple[str, ...]
    pub_pick: int = 0
    pub_win: int = 0

    @property
    def win_rate(self) -> float | None:
        if self.pub_pick <= 0:
            return None
        return self.pub_win / self.pub_pick

    @property
    def sample_confidence(self) -> float:
        if self.pub_pick <= 0:
            return 0.0
        return min(1.0, math.log10(self.pub_pick + 1) / 5.0)


class HttpJsonClient:
    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self._cache: dict[str, Any] = {}

    def get_json(self, url: str) -> Any:
        if url in self._cache:
            return self._cache[url]
        request = Request(
            url,
            headers={
                "User-Agent": "DotaCoachMVP/0.1 (+https://github.com/RusZov/Stuff-like-that)",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DataSourceError(f"Failed to fetch {url}: {exc}") from exc
        self._cache[url] = payload
        return payload


class DotaData:
    """Live hero/meta data with graceful fallback between Valve and OpenDota."""

    def __init__(self, client: HttpJsonClient | None = None) -> None:
        self.client = client or HttpJsonClient()
        self.heroes: dict[str, Hero] = {}
        self.heroes_by_id: dict[int, Hero] = {}
        self.patch: str | None = None
        self.source_status: dict[str, str] = {}
        self._enemy_matchups: dict[int, dict[int, tuple[float, int]]] = {}

    def refresh(self) -> None:
        valve_rows: list[dict[str, Any]] = []
        stats_rows: list[dict[str, Any]] = []

        try:
            valve_rows = self._parse_valve_heroes(self.client.get_json(VALVE_HERO_LIST_URL))
            self.source_status["Valve heroes"] = "ok"
        except DataSourceError as exc:
            self.source_status["Valve heroes"] = f"error: {exc}"

        try:
            stats_rows = self._parse_opendota_stats(self.client.get_json(OPENDOTA_HERO_STATS_URL))
            self.source_status["OpenDota stats"] = "ok"
        except DataSourceError as exc:
            self.source_status["OpenDota stats"] = f"error: {exc}"

        if not valve_rows and not stats_rows:
            raise DataSourceError("Both Valve hero data and OpenDota hero stats are unavailable")

        valve_by_id = {int(row["id"]): row for row in valve_rows}
        stats_by_id = {int(row["id"]): row for row in stats_rows}
        ids = sorted(set(valve_by_id) | set(stats_by_id))

        heroes: list[Hero] = []
        for hero_id in ids:
            valve = valve_by_id.get(hero_id, {})
            stats = stats_by_id.get(hero_id, {})
            name = (
                valve.get("name_english_loc")
                or valve.get("name_loc")
                or stats.get("localized_name")
                or stats.get("name")
            )
            if not name:
                continue
            roles = tuple(str(role) for role in stats.get("roles", []) if role)
            primary_attr = self._normalise_attr(valve.get("primary_attr", stats.get("primary_attr")))
            complexity = valve.get("complexity")
            try:
                complexity = int(complexity) if complexity is not None else None
            except (TypeError, ValueError):
                complexity = None
            heroes.append(
                Hero(
                    id=hero_id,
                    name=str(name),
                    primary_attr=primary_attr,
                    complexity=complexity,
                    roles=roles,
                    pub_pick=self._as_int(stats.get("pub_pick")),
                    pub_win=self._as_int(stats.get("pub_win")),
                )
            )

        self.heroes = {hero.name: hero for hero in heroes}
        self.heroes_by_id = {hero.id: hero for hero in heroes}
        if not self.heroes:
            raise DataSourceError("No heroes could be parsed from live data")

        try:
            self.patch = self._parse_latest_patch(self.client.get_json(VALVE_PATCH_LIST_URL))
            self.source_status["Valve patch list"] = "ok"
        except DataSourceError as exc:
            self.source_status["Valve patch list"] = f"error: {exc}"

    def resolve(self, name: str) -> Hero | None:
        needle = self._normalise_name(name)
        for hero in self.heroes.values():
            if self._normalise_name(hero.name) == needle:
                return hero
        return None

    def load_enemy_matchups(self, enemy_ids: list[int]) -> None:
        for enemy_id in enemy_ids:
            if enemy_id in self._enemy_matchups:
                continue
            url = OPENDOTA_MATCHUPS_URL.format(hero_id=enemy_id)
            try:
                payload = self.client.get_json(url)
                self._enemy_matchups[enemy_id] = self._parse_enemy_matchups(payload)
                self.source_status[f"OpenDota matchups:{enemy_id}"] = "ok"
            except DataSourceError as exc:
                self._enemy_matchups[enemy_id] = {}
                self.source_status[f"OpenDota matchups:{enemy_id}"] = f"error: {exc}"

    def candidate_win_rate_vs(self, candidate_id: int, enemy_id: int) -> tuple[float, int] | None:
        """Return candidate's inferred WR vs enemy using the enemy's matchup row.

        OpenDota's row stores wins for the queried hero. We query each visible enemy
        once, then invert that enemy win rate for every candidate. This keeps the
        draft recommendation path to at most five matchup HTTP calls.
        """
        row = self._enemy_matchups.get(enemy_id, {}).get(candidate_id)
        if row is None:
            return None
        enemy_win_rate, games = row
        return 1.0 - enemy_win_rate, games

    @staticmethod
    def _parse_valve_heroes(payload: Any) -> list[dict[str, Any]]:
        try:
            rows = payload["result"]["data"]["heroes"]
        except (KeyError, TypeError) as exc:
            raise DataSourceError("Unexpected Valve hero-list response") from exc
        if not isinstance(rows, list):
            raise DataSourceError("Valve hero-list response did not contain a list")
        return [row for row in rows if isinstance(row, dict) and "id" in row]

    @staticmethod
    def _parse_opendota_stats(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            raise DataSourceError("Unexpected OpenDota heroStats response")
        return [row for row in payload if isinstance(row, dict) and "id" in row]

    @staticmethod
    def _parse_enemy_matchups(payload: Any) -> dict[int, tuple[float, int]]:
        if not isinstance(payload, list):
            raise DataSourceError("Unexpected OpenDota matchup response")
        result: dict[int, tuple[float, int]] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            hero_id = DotaData._as_int(row.get("hero_id"))
            games = DotaData._as_int(row.get("games_played"))
            wins = DotaData._as_int(row.get("wins"))
            if hero_id <= 0 or games <= 0:
                continue
            result[hero_id] = (max(0.0, min(1.0, wins / games)), games)
        return result

    @staticmethod
    def _parse_latest_patch(payload: Any) -> str | None:
        rows = payload.get("patches") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise DataSourceError("Unexpected Valve patch-list response")
        row = max(rows, key=lambda item: DotaData._as_int(item.get("patch_timestamp")) if isinstance(item, dict) else 0)
        if not isinstance(row, dict):
            return None
        return str(row.get("patch_number") or row.get("patch_name") or "") or None

    @staticmethod
    def _normalise_attr(value: Any) -> str | None:
        mapping = {0: "Strength", 1: "Agility", 2: "Intelligence", 3: "Universal"}
        if isinstance(value, int):
            return mapping.get(value)
        if isinstance(value, str):
            lower = value.lower()
            aliases = {
                "str": "Strength",
                "agi": "Agility",
                "int": "Intelligence",
                "all": "Universal",
                "universal": "Universal",
            }
            return aliases.get(lower, value)
        return None

    @staticmethod
    def _normalise_name(value: str) -> str:
        return "".join(ch.lower() for ch in value if ch.isalnum())

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
