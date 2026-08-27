from __future__ import annotations

from dataclasses import dataclass
import json
import math
import time
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
    def __init__(self, timeout: float = 10.0, attempts: int = 3) -> None:
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self._cache: dict[str, Any] = {}

    def get_json(self, url: str) -> Any:
        if url in self._cache:
            return self._cache[url]
        request = Request(
            url,
            headers={
                "User-Agent": "DotaCoachMVP/0.2 (+https://github.com/RusZov/Stuff-like-that)",
                "Accept": "application/json",
            },
        )
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self._cache[url] = payload
                return payload
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.attempts:
                    time.sleep(0.35 * attempt)
        raise DataSourceError(
            f"Failed to fetch {url} after {self.attempts} attempts: {last_error}"
        ) from last_error


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

            pub_pick, pub_win = self._public_pick_win(stats)
            heroes.append(
                Hero(
                    id=hero_id,
                    name=str(name),
                    primary_attr=primary_attr,
                    complexity=complexity,
                    roles=roles,
                    pub_pick=pub_pick,
                    pub_win=pub_win,
                )
            )

        self.heroes = {hero.name: hero for hero in heroes}
        self.heroes_by_id = {hero.id: hero for hero in heroes}
        if not self.heroes:
            raise DataSourceError("No heroes could be parsed from live data")

        meta_count = sum(hero.pub_pick > 0 for hero in heroes)
        if stats_rows and meta_count == 0:
            self.source_status["OpenDota stats"] = "error: heroStats returned no usable ranked pick/win data"

        try:
            self.patch = self._parse_latest_patch(self.client.get_json(VALVE_PATCH_LIST_URL))
            self.source_status["Valve patch list"] = "ok"
        except DataSourceError as exc:
            self.source_status["Valve patch list"] = f"error: {exc}"

    @property
    def meta_coverage(self) -> int:
        return sum(hero.pub_pick > 0 for hero in self.heroes.values())

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
                rows = self._parse_enemy_matchups(payload)
                self._enemy_matchups[enemy_id] = rows
                self.source_status[f"OpenDota matchups:{enemy_id}"] = f"ok ({len(rows)} rows)"
            except DataSourceError as exc:
                self._enemy_matchups[enemy_id] = {}
                self.source_status[f"OpenDota matchups:{enemy_id}"] = f"error: {exc}"

    def matchup_count(self, enemy_id: int) -> int:
        return len(self._enemy_matchups.get(enemy_id, {}))

    def candidate_win_rate_vs(self, candidate_id: int, enemy_id: int) -> tuple[float, int] | None:
        """Infer candidate WR vs enemy from the queried enemy's matchup row."""
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
    def _public_pick_win(row: dict[str, Any]) -> tuple[int, int]:
        """Return ranked public picks/wins from OpenDota heroStats.

        Current OpenDota exposes rank buckets 1_pick..8_pick and 1_win..8_win.
        Older payloads sometimes exposed pub_pick/pub_win, so keep that as a
        compatibility fallback instead of silently producing zero meta data.
        """
        ranked_pick = sum(DotaData._as_int(row.get(f"{rank}_pick")) for rank in range(1, 9))
        ranked_win = sum(DotaData._as_int(row.get(f"{rank}_win")) for rank in range(1, 9))
        if ranked_pick > 0:
            return ranked_pick, min(ranked_pick, max(0, ranked_win))

        pub_pick = DotaData._as_int(row.get("pub_pick"))
        pub_win = DotaData._as_int(row.get("pub_win"))
        if pub_pick > 0:
            return pub_pick, min(pub_pick, max(0, pub_win))
        return 0, 0

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
            wins = min(games, max(0, wins))
            result[hero_id] = (wins / games, games)
        return result

    @staticmethod
    def _parse_latest_patch(payload: Any) -> str | None:
        rows = payload.get("patches") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise DataSourceError("Unexpected Valve patch-list response")
        row = max(
            rows,
            key=lambda item: DotaData._as_int(item.get("patch_timestamp")) if isinstance(item, dict) else 0,
        )
        if not isinstance(row, dict):
            return None
        return str(row.get("patch_number") or row.get("patch_name") or "") or None

    @staticmethod
    def _normalise_attr(value: Any) -> str | None:
        mapping = {0: "Strength", 1: "Agility", 2: "Intelligence", 3: "Universal"}
        if isinstance(value, int):
            return mapping.get(value)
        if isinstance(value, str):
            aliases = {
                "str": "Strength",
                "agi": "Agility",
                "int": "Intelligence",
                "all": "Universal",
                "universal": "Universal",
            }
            return aliases.get(value.lower(), value)
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
