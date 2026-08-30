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
# OpenDota's /heroes/{id}/matchups endpoint is aggregate matchup evidence and
# can be noticeably slower than heroStats. Treat it as optional evidence.
OPENDOTA_MATCHUPS_URL = "https://api.opendota.com/api/heroes/{hero_id}/matchups"
# Query one lane at a time. OpenDota's implementation caps laneRoles at 1200
# rows; an unfiltered query can truncate hero/time buckets, while one lane is
# comfortably below that limit for the current roster.
OPENDOTA_LANE_ROLES_URL = "https://api.opendota.com/api/scenarios/laneRoles?lane_role={lane_role}"

RANK_NAMES = {
    1: "Herald",
    2: "Guardian",
    3: "Crusader",
    4: "Archon",
    5: "Legend",
    6: "Ancient",
    7: "Divine",
    8: "Immortal",
}


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
    rank_picks: tuple[int, ...] = ()
    rank_wins: tuple[int, ...] = ()
    portrait_path: str | None = None
    icon_path: str | None = None

    @property
    def win_rate(self) -> float | None:
        if self.pub_pick <= 0:
            return None
        return self.pub_win / self.pub_pick

    @property
    def sample_confidence(self) -> float:
        return self._sample_confidence(self.pub_pick)

    def pick_win_for_rank(self, rank_tier: int | None) -> tuple[int, int]:
        """Return picks/wins for one OpenDota medal bucket or overall.

        If a requested bucket is absent in an older payload, fall back to the
        aggregate ranked sample instead of silently treating the hero as having
        zero games.
        """
        if rank_tier is None:
            return self.pub_pick, self.pub_win
        if rank_tier not in RANK_NAMES:
            raise ValueError(f"rank_tier must be 1-8 or None, got {rank_tier!r}")
        index = rank_tier - 1
        if index < len(self.rank_picks) and index < len(self.rank_wins):
            picks = max(0, int(self.rank_picks[index]))
            wins = min(picks, max(0, int(self.rank_wins[index])))
            if picks > 0:
                return picks, wins
        return self.pub_pick, self.pub_win

    def win_rate_for_rank(self, rank_tier: int | None) -> float | None:
        picks, wins = self.pick_win_for_rank(rank_tier)
        if picks <= 0:
            return None
        return wins / picks

    def sample_confidence_for_rank(self, rank_tier: int | None) -> float:
        picks, _ = self.pick_win_for_rank(rank_tier)
        return self._sample_confidence(picks)

    @staticmethod
    def _sample_confidence(picks: int) -> float:
        if picks <= 0:
            return 0.0
        return min(1.0, math.log10(picks + 1) / 5.0)


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
                "User-Agent": "DotaCoachMVP/0.4 (+https://github.com/RusZov/Stuff-like-that)",
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
        self._lane_roles: dict[tuple[int, int], tuple[int, int]] = {}
        self._loaded_lane_roles: set[int] = set()
        self._normalised_names: dict[str, Hero] = {}

    def refresh(self) -> None:
        valve_rows: list[dict[str, Any]] = []
        stats_rows: list[dict[str, Any]] = []
        self.source_status = {}

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

            rank_picks, rank_wins = self._rank_pick_wins(stats)
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
                    rank_picks=rank_picks,
                    rank_wins=rank_wins,
                    portrait_path=str(stats.get("img")) if stats.get("img") else None,
                    icon_path=str(stats.get("icon")) if stats.get("icon") else None,
                )
            )

        self.heroes = {hero.name: hero for hero in heroes}
        self.heroes_by_id = {hero.id: hero for hero in heroes}
        self._normalised_names = {self._normalise_name(hero.name): hero for hero in heroes}
        # Supplemental evidence can become stale across refreshes or a new
        # patch. Never carry old matrices into a refreshed roster.
        self._enemy_matchups.clear()
        self._lane_roles.clear()
        self._loaded_lane_roles.clear()
        if not self.heroes:
            raise DataSourceError("No heroes could be parsed from live data")

        meta_count = sum(hero.pub_pick > 0 for hero in heroes)
        if stats_rows and meta_count == 0:
            self.source_status["OpenDota stats"] = "error: heroStats returned no usable ranked pick/win data"

        try:
            self.patch = self._parse_latest_patch(self.client.get_json(VALVE_PATCH_LIST_URL))
            self.source_status["Valve patch list"] = "ok"
        except DataSourceError as exc:
            self.patch = None
            self.source_status["Valve patch list"] = f"error: {exc}"

    @property
    def meta_coverage(self) -> int:
        return sum(hero.pub_pick > 0 for hero in self.heroes.values())

    def rank_meta_coverage(self, rank_tier: int) -> int:
        if rank_tier not in RANK_NAMES:
            raise ValueError(f"rank_tier must be 1-8, got {rank_tier!r}")
        return sum(hero.pick_win_for_rank(rank_tier)[0] > 0 for hero in self.heroes.values())

    def resolve(self, name: str) -> Hero | None:
        return self._normalised_names.get(self._normalise_name(name))

    def load_enemy_matchups(self, enemy_ids: list[int]) -> None:
        for enemy_id in dict.fromkeys(enemy_ids):
            if enemy_id in self._enemy_matchups:
                continue
            url = OPENDOTA_MATCHUPS_URL.format(hero_id=enemy_id)
            key = f"OpenDota pro matchups:{enemy_id}"
            try:
                payload = self.client.get_json(url)
                rows = self._parse_enemy_matchups(payload)
                self._enemy_matchups[enemy_id] = rows
                self.source_status[key] = f"ok ({len(rows)} rows)"
            except DataSourceError as exc:
                # Important: do not cache an empty matrix on a transient error.
                # A later call in the same process must be allowed to retry.
                self.source_status[key] = f"error: {exc}"

    def matchup_count(self, enemy_id: int) -> int:
        return len(self._enemy_matchups.get(enemy_id, {}))

    def candidate_win_rate_vs(self, candidate_id: int, enemy_id: int) -> tuple[float, int] | None:
        """Infer candidate WR vs enemy from OpenDota's queried matchup row.

        This endpoint is used as supplemental aggregate matchup evidence, not
        as a position- or bracket-specific current-public truth source.
        """
        row = self._enemy_matchups.get(enemy_id, {}).get(candidate_id)
        if row is None:
            return None
        enemy_win_rate, games = row
        return 1.0 - enemy_win_rate, games

    def load_lane_roles(self, lane_roles: list[int] | tuple[int, ...] = (1, 2, 3)) -> None:
        """Load aggregate OpenDota lane-role evidence without relying on a truncated all-lanes query.

        OpenDota lane roles are lane assignments (1=safelane, 2=mid,
        3=offlane), not exact farm priorities. We therefore use them only as
        supplemental positional evidence in the scoring engine.
        """
        for lane_role in dict.fromkeys(lane_roles):
            if lane_role not in {1, 2, 3}:
                raise ValueError(f"lane_role must be 1, 2 or 3, got {lane_role!r}")
            if lane_role in self._loaded_lane_roles:
                continue
            url = OPENDOTA_LANE_ROLES_URL.format(lane_role=lane_role)
            key = f"OpenDota lane role:{lane_role}"
            try:
                parsed = self._parse_lane_roles(self.client.get_json(url), expected_lane_role=lane_role)
                for hero_id, games_wins in parsed.items():
                    self._lane_roles[(hero_id, lane_role)] = games_wins
                self._loaded_lane_roles.add(lane_role)
                self.source_status[key] = f"ok ({len(parsed)} heroes)"
            except DataSourceError as exc:
                # Like matchups, lane roles are supplemental. A transient error
                # must not poison future attempts or break manual recommendations.
                self.source_status[key] = f"error: {exc}"

    def lane_role_sample(self, hero_id: int, lane_role: int) -> tuple[int, int] | None:
        return self._lane_roles.get((hero_id, lane_role))

    def lane_role_share(self, hero_id: int, lane_role: int) -> float | None:
        """Share of observed lane-role scenario games in the requested lane.

        A share is returned only after all three normal lane roles were loaded,
        otherwise the denominator would be biased by missing lanes.
        """
        if not {1, 2, 3}.issubset(self._loaded_lane_roles):
            return None
        target = self._lane_roles.get((hero_id, lane_role), (0, 0))[0]
        total = sum(self._lane_roles.get((hero_id, role), (0, 0))[0] for role in (1, 2, 3))
        if total <= 0:
            return None
        return target / total

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
    def _rank_pick_wins(row: dict[str, Any]) -> tuple[tuple[int, ...], tuple[int, ...]]:
        picks: list[int] = []
        wins: list[int] = []
        for rank in range(1, 9):
            rank_picks = max(0, DotaData._as_int(row.get(f"{rank}_pick")))
            rank_wins = min(rank_picks, max(0, DotaData._as_int(row.get(f"{rank}_win"))))
            picks.append(rank_picks)
            wins.append(rank_wins)
        return tuple(picks), tuple(wins)

    @staticmethod
    def _public_pick_win(row: dict[str, Any]) -> tuple[int, int]:
        """Return aggregate ranked public picks/wins from OpenDota heroStats."""
        rank_picks, rank_wins = DotaData._rank_pick_wins(row)
        ranked_pick = sum(rank_picks)
        ranked_win = sum(rank_wins)
        if ranked_pick > 0:
            return ranked_pick, min(ranked_pick, max(0, ranked_win))

        # Compatibility fallback for old/cached OpenDota payloads.
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
    def _parse_lane_roles(
        payload: Any,
        expected_lane_role: int | None = None,
    ) -> dict[int, tuple[int, int]]:
        """Aggregate OpenDota lane-role time buckets into hero -> (games, wins)."""
        if not isinstance(payload, list):
            raise DataSourceError("Unexpected OpenDota laneRoles response")
        totals: dict[int, list[int]] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            hero_id = DotaData._as_int(row.get("hero_id"))
            lane_role = DotaData._as_int(row.get("lane_role"))
            games = max(0, DotaData._as_int(row.get("games")))
            wins = min(games, max(0, DotaData._as_int(row.get("wins"))))
            if hero_id <= 0 or lane_role not in {1, 2, 3} or games <= 0:
                continue
            if expected_lane_role is not None and lane_role != expected_lane_role:
                continue
            current = totals.setdefault(hero_id, [0, 0])
            current[0] += games
            current[1] += wins
        return {hero_id: (values[0], min(values[0], values[1])) for hero_id, values in totals.items()}

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
