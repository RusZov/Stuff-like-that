from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from dota_data import (
    DotaData as LegacyDotaData,
    Hero,
    OPEN_DOTA_HERO_STATS,
    STEAM_CDN,
    VALVE_HERO_LIST,
    VALVE_PLUS_MATCHUPS,
    VALVE_PLUS_STATS,
    fallback_heroes,
    parse_valve_hero_list,
    parse_valve_plus_stats,
)


def parse_opendota_hero_stats(payload: object, heroes: dict[str, Hero]) -> dict[str, Hero]:
    """Apply OpenDota public win-rate data to a Valve/offline hero roster."""
    if not isinstance(payload, list) or len(payload) < 100:
        raise ValueError("OpenDota heroStats: expected a large JSON array")

    by_id = {hero.id: name for name, hero in heroes.items() if hero.id is not None}
    updated = dict(heroes)
    applied = 0

    for row in payload:
        if not isinstance(row, dict):
            continue
        name = by_id.get(row.get("id"))
        if not name:
            localized = row.get("localized_name")
            if isinstance(localized, str) and localized in updated:
                name = localized
        if not name:
            continue

        picks = row.get("pub_pick")
        wins = row.get("pub_win")
        if not isinstance(picks, (int, float)) or not isinstance(wins, (int, float)) or picks <= 0:
            picks = sum(float(row.get(f"{rank}_pick", 0) or 0) for rank in range(1, 8))
            wins = sum(float(row.get(f"{rank}_win", 0) or 0) for rank in range(1, 8))
        if picks <= 0:
            continue

        win_rate = float(wins) / float(picks)
        if 0.0 <= win_rate <= 1.0:
            updated[name] = replace(updated[name], win_rate=win_rate)
            applied += 1

    if applied < 100:
        raise ValueError(f"OpenDota heroStats: only {applied} usable hero rows")
    return updated


def parse_valve_matchups(payload: object, heroes: dict[str, Hero]) -> dict[str, dict[str, dict[str, object]]]:
    """Parse the live Valve Dota Plus ally/enemy payload.

    Live shape (verified by CI):
      ranked_hero_data -> [{rank: 0, hero_data: [{hero_id, first_other_hero_id,
      enemy_win_rate: [...]}, ...]}, ...]

    Each hero row stores only later numeric hero IDs, so we also add the inverse
    direction (1 - win rate) to obtain a complete candidate-vs-enemy lookup.
    """
    if not isinstance(payload, dict):
        raise ValueError("Valve matchup API: top-level JSON is not an object")
    chunks = payload.get("ranked_hero_data")
    if not isinstance(chunks, list) or not chunks:
        raise ValueError("Valve matchup API: ranked_hero_data is missing")

    chunk = next((item for item in chunks if isinstance(item, dict) and item.get("rank") == 0), None)
    if chunk is None:
        chunk = next((item for item in chunks if isinstance(item, dict) and isinstance(item.get("hero_data"), list)), None)
    if not isinstance(chunk, dict) or not isinstance(chunk.get("hero_data"), list):
        raise ValueError("Valve matchup API: no hero_data rank chunk")

    rows = chunk["hero_data"]
    if len(rows) < 80:
        raise ValueError(f"Valve matchup API: suspiciously small hero_data ({len(rows)})")

    id_to_name = {hero.id: name for name, hero in heroes.items() if hero.id is not None}
    matrix: dict[str, dict[str, dict[str, object]]] = {}
    pair_count = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate_name = id_to_name.get(row.get("hero_id"))
        first_other = row.get("first_other_hero_id")
        rates = row.get("enemy_win_rate")
        if not candidate_name or not isinstance(first_other, int) or not isinstance(rates, list):
            continue

        for offset, raw_rate in enumerate(rates):
            enemy_name = id_to_name.get(first_other + offset)
            if not enemy_name or enemy_name == candidate_name or not isinstance(raw_rate, (int, float)):
                continue
            wr = float(raw_rate) / 10000.0
            if not 0.0 < wr < 1.0:
                continue

            matrix.setdefault(enemy_name, {})[candidate_name] = {
                "candidate_win_rate": wr,
                "games": None,
                "source": "Valve Dota Plus",
            }
            matrix.setdefault(candidate_name, {})[enemy_name] = {
                "candidate_win_rate": 1.0 - wr,
                "games": None,
                "source": "Valve Dota Plus",
            }
            pair_count += 1

    if pair_count < 500:
        raise ValueError(f"Valve matchup API: only {pair_count} usable pairs")
    return matrix


class DotaData(LegacyDotaData):
    """Current provider used by the app.

    Roster: official Valve datafeed.
    Matchups: official Valve Dota Plus endpoint.
    Overall win rate: Valve PlusStats when valid, otherwise OpenDota heroStats.
    If both meta endpoints fail locally, the app still keeps the Valve roster and
    simply omits the meta win-rate bonus.
    """

    def __init__(self, root: Path | str = "data") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hero_cache = self.root / "valve_heroes.json"
        self.meta_cache = self.root / "hero_meta.json"
        self.matchup_cache = self.root / "valve_matchups.json"
        self.heroes = fallback_heroes()
        self.matchups: dict[str, dict[str, dict[str, object]]] = {}
        self.roster_provider = "offline fallback"
        self.meta_provider = "none"
        self.matchup_provider = "none"
        self._load_caches()

    @staticmethod
    def _load_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _atomic_json(path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _get_json(url: str, timeout: float = 15.0):
        req = urllib.request.Request(url, headers={"User-Agent": "Dota2Coach/2.1"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}: {url}")
            return json.loads(response.read().decode("utf-8"))

    def _load_caches(self) -> None:
        hero_payload = self._load_json(self.hero_cache, None)
        if hero_payload is not None:
            try:
                self.heroes = parse_valve_hero_list(hero_payload)
                self.roster_provider = "Valve cache"
            except ValueError:
                self.heroes = fallback_heroes()

        meta = self._load_json(self.meta_cache, {})
        if isinstance(meta, dict):
            rates = meta.get("win_rates")
            if isinstance(rates, dict):
                for name, rate in rates.items():
                    if name in self.heroes and isinstance(rate, (int, float)) and 0.0 <= float(rate) <= 1.0:
                        self.heroes[name] = replace(self.heroes[name], win_rate=float(rate))
                provider = meta.get("provider")
                if isinstance(provider, str):
                    self.meta_provider = provider

        cached_matchups = self._load_json(self.matchup_cache, {})
        if isinstance(cached_matchups, dict) and cached_matchups:
            self.matchups = cached_matchups
            self.matchup_provider = "Valve Dota Plus cache"

    @property
    def source(self) -> str:
        return f"roster={self.roster_provider}; meta={self.meta_provider}; matchups={self.matchup_provider}"

    def _save_meta(self, provider: str) -> None:
        rates = {name: hero.win_rate for name, hero in self.heroes.items() if hero.win_rate is not None}
        self._atomic_json(self.meta_cache, {"provider": provider, "win_rates": rates})

    def sync_heroes(self, timeout: float = 15.0) -> int:
        hero_payload = self._get_json(VALVE_HERO_LIST, timeout)
        heroes = parse_valve_hero_list(hero_payload)
        self._atomic_json(self.hero_cache, hero_payload)
        self.heroes = heroes
        self.roster_provider = "Valve dota2.com"

        # This undocumented Valve endpoint currently sometimes returns HTTP 200
        # with {success, error}. Validate the payload before trusting it.
        try:
            plus_payload = self._get_json(VALVE_PLUS_STATS, timeout)
            candidate = parse_valve_plus_stats(plus_payload, self.heroes)
            usable = sum(hero.win_rate is not None for hero in candidate.values())
            if usable < 100:
                raise ValueError(f"Valve PlusStats: only {usable} usable hero rows")
            self.heroes = candidate
            self.meta_provider = "Valve Dota Plus"
        except Exception:
            try:
                open_payload = self._get_json(OPEN_DOTA_HERO_STATS, timeout)
                self.heroes = parse_opendota_hero_stats(open_payload, self.heroes)
                self.meta_provider = "OpenDota fallback"
            except Exception:
                self.meta_provider = "unavailable"

        self._save_meta(self.meta_provider)
        return len(self.heroes)

    def sync_matchups(self, enemy_names: Iterable[str], timeout: float = 15.0) -> int:
        payload = self._get_json(VALVE_PLUS_MATCHUPS, timeout)
        matrix = parse_valve_matchups(payload, self.heroes)
        self.matchups = matrix
        self.matchup_provider = "Valve Dota Plus"
        self._atomic_json(self.matchup_cache, matrix)
        requested = list(dict.fromkeys(enemy_names))
        return sum(1 for enemy in requested if matrix.get(enemy))

    def portrait_url(self, hero: Hero) -> str:
        return f"{STEAM_CDN}/apps/dota2/images/dota_react/heroes/{hero.slug}.png"
