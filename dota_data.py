from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

VALVE_HERO_LIST = "https://www.dota2.com/datafeed/herolist?language=english"
VALVE_PLUS_STATS = "https://www.dota2.com/webapi/IDOTA2Plus/GetPlusStatsData/v001"
VALVE_PLUS_MATCHUPS = "https://www.dota2.com/webapi/IDOTA2Plus/GetPlusHeroAllyAndEnemyData/v001"
STEAM_CDN = "https://cdn.cloudflare.steamstatic.com"

# OpenDota is kept only as a fallback provider. It is not the primary source.
OPEN_DOTA_HERO_STATS = "https://api.opendota.com/api/heroStats"

FALLBACK_HERO_NAMES = [
    "Abaddon", "Alchemist", "Ancient Apparition", "Anti-Mage", "Arc Warden", "Axe",
    "Bane", "Batrider", "Beastmaster", "Bloodseeker", "Bounty Hunter", "Brewmaster",
    "Bristleback", "Broodmother", "Centaur Warrunner", "Chaos Knight", "Chen", "Clinkz",
    "Clockwerk", "Crystal Maiden", "Dark Seer", "Dark Willow", "Dawnbreaker", "Dazzle",
    "Death Prophet", "Disruptor", "Doom", "Dragon Knight", "Drow Ranger", "Earth Spirit",
    "Earthshaker", "Elder Titan", "Ember Spirit", "Enchantress", "Enigma", "Faceless Void",
    "Grimstroke", "Gyrocopter", "Hoodwink", "Huskar", "Invoker", "Io", "Jakiro",
    "Juggernaut", "Keeper of the Light", "Kez", "Kunkka", "Largo", "Legion Commander",
    "Leshrac", "Lich", "Lifestealer", "Lina", "Lion", "Lone Druid", "Luna", "Lycan",
    "Magnus", "Marci", "Mars", "Medusa", "Meepo", "Mirana", "Monkey King", "Morphling",
    "Muerta", "Naga Siren", "Nature's Prophet", "Necrophos", "Night Stalker", "Nyx Assassin",
    "Ogre Magi", "Omniknight", "Oracle", "Outworld Destroyer", "Pangolier", "Phantom Assassin",
    "Phantom Lancer", "Phoenix", "Primal Beast", "Puck", "Pudge", "Pugna", "Queen of Pain",
    "Razor", "Riki", "Ringmaster", "Rubick", "Sand King", "Shadow Demon", "Shadow Fiend",
    "Shadow Shaman", "Silencer", "Skywrath Mage", "Slardar", "Slark", "Snapfire", "Sniper",
    "Spectre", "Spirit Breaker", "Storm Spirit", "Sven", "Techies", "Templar Assassin",
    "Terrorblade", "Tidehunter", "Timbersaw", "Tinker", "Tiny", "Treant Protector",
    "Troll Warlord", "Tusk", "Underlord", "Undying", "Ursa", "Vengeful Spirit", "Venomancer",
    "Viper", "Visage", "Void Spirit", "Warlock", "Weaver", "Windranger", "Winter Wyvern",
    "Witch Doctor", "Wraith King", "Zeus",
]

POSITION_POOLS = {
    "1 Carry": {"Alchemist", "Anti-Mage", "Arc Warden", "Bloodseeker", "Chaos Knight", "Clinkz", "Drow Ranger", "Faceless Void", "Gyrocopter", "Juggernaut", "Kez", "Lifestealer", "Luna", "Medusa", "Monkey King", "Morphling", "Muerta", "Naga Siren", "Phantom Assassin", "Phantom Lancer", "Razor", "Slark", "Sniper", "Spectre", "Sven", "Templar Assassin", "Terrorblade", "Troll Warlord", "Ursa", "Weaver", "Wraith King"},
    "2 Mid": {"Arc Warden", "Batrider", "Death Prophet", "Dragon Knight", "Earth Spirit", "Ember Spirit", "Huskar", "Invoker", "Kez", "Leshrac", "Lina", "Lone Druid", "Magnus", "Meepo", "Monkey King", "Necrophos", "Outworld Destroyer", "Pangolier", "Primal Beast", "Puck", "Queen of Pain", "Razor", "Shadow Fiend", "Sniper", "Storm Spirit", "Templar Assassin", "Tiny", "Tinker", "Viper", "Void Spirit", "Zeus"},
    "3 Offlane": {"Abaddon", "Axe", "Beastmaster", "Brewmaster", "Bristleback", "Broodmother", "Centaur Warrunner", "Dark Seer", "Dawnbreaker", "Doom", "Dragon Knight", "Enigma", "Legion Commander", "Magnus", "Mars", "Night Stalker", "Pangolier", "Primal Beast", "Sand King", "Slardar", "Tidehunter", "Timbersaw", "Underlord", "Viper", "Visage", "Wraith King"},
    "4 Support": {"Batrider", "Bounty Hunter", "Chen", "Clockwerk", "Dark Willow", "Earth Spirit", "Earthshaker", "Enchantress", "Grimstroke", "Hoodwink", "Io", "Jakiro", "Keeper of the Light", "Kunkka", "Largo", "Lion", "Marci", "Mirana", "Nyx Assassin", "Phoenix", "Pudge", "Ringmaster", "Rubick", "Shadow Demon", "Shadow Shaman", "Skywrath Mage", "Snapfire", "Spirit Breaker", "Techies", "Tiny", "Treant Protector", "Tusk", "Vengeful Spirit", "Venomancer", "Warlock", "Weaver", "Windranger", "Winter Wyvern", "Witch Doctor"},
    "5 Hard Support": {"Abaddon", "Ancient Apparition", "Bane", "Chen", "Crystal Maiden", "Dazzle", "Disruptor", "Enchantress", "Grimstroke", "Io", "Jakiro", "Keeper of the Light", "Largo", "Lich", "Lion", "Ogre Magi", "Omniknight", "Oracle", "Ringmaster", "Shadow Demon", "Shadow Shaman", "Silencer", "Snapfire", "Treant Protector", "Undying", "Vengeful Spirit", "Warlock", "Winter Wyvern", "Witch Doctor"},
}

DISABLERS = {"Axe", "Bane", "Beastmaster", "Centaur Warrunner", "Chaos Knight", "Clockwerk", "Dark Willow", "Disruptor", "Earth Spirit", "Earthshaker", "Enigma", "Faceless Void", "Grimstroke", "Jakiro", "Kunkka", "Legion Commander", "Lion", "Magnus", "Mars", "Nyx Assassin", "Ogre Magi", "Pangolier", "Puck", "Pudge", "Ringmaster", "Rubick", "Sand King", "Shadow Shaman", "Slardar", "Spirit Breaker", "Sven", "Tidehunter", "Tiny", "Treant Protector", "Tusk", "Vengeful Spirit", "Winter Wyvern"}
INITIATORS = {"Axe", "Batrider", "Beastmaster", "Brewmaster", "Centaur Warrunner", "Clockwerk", "Dark Seer", "Dawnbreaker", "Doom", "Earth Spirit", "Earthshaker", "Enigma", "Kunkka", "Legion Commander", "Magnus", "Mars", "Night Stalker", "Pangolier", "Primal Beast", "Puck", "Pudge", "Sand King", "Slardar", "Spirit Breaker", "Tidehunter", "Tiny", "Tusk", "Underlord"}
PUSHERS = {"Beastmaster", "Broodmother", "Chen", "Clinkz", "Death Prophet", "Dragon Knight", "Drow Ranger", "Leshrac", "Lone Druid", "Luna", "Lycan", "Meepo", "Naga Siren", "Nature's Prophet", "Pugna", "Shadow Shaman", "Sniper", "Terrorblade", "Tiny", "Visage"}
DURABLE = {"Abaddon", "Axe", "Brewmaster", "Bristleback", "Centaur Warrunner", "Dawnbreaker", "Doom", "Dragon Knight", "Huskar", "Kunkka", "Legion Commander", "Mars", "Necrophos", "Night Stalker", "Ogre Magi", "Primal Beast", "Slardar", "Tidehunter", "Timbersaw", "Underlord", "Undying", "Wraith King"}
ESCAPE = {"Anti-Mage", "Bounty Hunter", "Broodmother", "Clinkz", "Dark Seer", "Ember Spirit", "Faceless Void", "Hoodwink", "Kez", "Mirana", "Monkey King", "Morphling", "Pangolier", "Phantom Assassin", "Phantom Lancer", "Puck", "Queen of Pain", "Riki", "Slark", "Storm Spirit", "Timbersaw", "Void Spirit", "Weaver", "Windranger"}

SPECIAL_SLUGS = {
    "Anti-Mage": "antimage", "Centaur Warrunner": "centaur", "Clockwerk": "rattletrap",
    "Doom": "doom_bringer", "Io": "wisp", "Lifestealer": "life_stealer",
    "Nature's Prophet": "furion", "Necrophos": "necrolyte", "Outworld Destroyer": "obsidian_destroyer",
    "Queen of Pain": "queenofpain", "Shadow Fiend": "nevermore", "Timbersaw": "shredder",
    "Underlord": "abyssal_underlord", "Windranger": "windrunner", "Wraith King": "skeleton_king",
}

ATTRS = {0: "str", 1: "agi", 2: "int", 3: "all"}


def hero_slug(name: str) -> str:
    return SPECIAL_SLUGS.get(name, name.lower().replace("'", "").replace("-", "_").replace(" ", "_"))


def fallback_roles(name: str) -> tuple[str, ...]:
    roles: list[str] = []
    if name in POSITION_POOLS["1 Carry"]:
        roles.append("Carry")
    if name in POSITION_POOLS["4 Support"] or name in POSITION_POOLS["5 Hard Support"]:
        roles.append("Support")
    if name in DISABLERS:
        roles.append("Disabler")
    if name in INITIATORS:
        roles.append("Initiator")
    if name in DURABLE:
        roles.append("Durable")
    if name in PUSHERS:
        roles.append("Pusher")
    if name in ESCAPE:
        roles.append("Escape")
    if name in POSITION_POOLS["2 Mid"] and "Carry" not in roles:
        roles.append("Nuker")
    return tuple(roles or ["Nuker"])


@dataclass(frozen=True)
class Hero:
    id: int | None
    name: str
    roles: tuple[str, ...]
    primary_attr: str = ""
    complexity: int | None = None
    win_rate: float | None = None

    @property
    def slug(self) -> str:
        return hero_slug(self.name)


def fallback_heroes() -> dict[str, Hero]:
    return {name: Hero(None, name, fallback_roles(name)) for name in FALLBACK_HERO_NAMES}


def parse_valve_hero_list(payload: object) -> dict[str, Hero]:
    try:
        rows = payload["result"]["data"]["heroes"]  # type: ignore[index]
    except Exception as exc:
        raise ValueError("Valve herolist: unexpected JSON shape") from exc
    if not isinstance(rows, list):
        raise ValueError("Valve herolist: heroes is not an array")

    result: dict[str, Hero] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        hero_id = row.get("id")
        name = row.get("name_loc") or row.get("name_english_loc")
        if not isinstance(hero_id, int) or not isinstance(name, str) or not name:
            continue
        result[name] = Hero(
            id=hero_id,
            name=name,
            roles=fallback_roles(name),
            primary_attr=ATTRS.get(row.get("primary_attr"), ""),
            complexity=row.get("complexity") if isinstance(row.get("complexity"), int) else None,
        )

    if len(result) < 120:
        raise ValueError(f"Valve herolist: suspiciously small roster ({len(result)})")
    for name, hero in fallback_heroes().items():
        result.setdefault(name, hero)
    return result


def parse_valve_plus_stats(payload: object, heroes: dict[str, Hero]) -> dict[str, Hero]:
    if not isinstance(payload, dict) or not isinstance(payload.get("heroes"), list):
        raise ValueError("Valve GetPlusStatsData: unexpected JSON shape")
    by_id = {hero.id: name for name, hero in heroes.items() if hero.id is not None}
    updated = dict(heroes)

    for row in payload["heroes"]:
        if not isinstance(row, dict):
            continue
        name = by_id.get(row.get("hero_id"))
        chunks = row.get("hero_data_per_chunk")
        if not name or not isinstance(chunks, list):
            continue
        chunk = next((c for c in chunks if isinstance(c, dict) and c.get("rank_chunk") == 0), None)
        if chunk is None:
            chunk = next((c for c in chunks if isinstance(c, dict)), None)
        if not isinstance(chunk, dict) or not isinstance(chunk.get("weeks"), list) or not chunk["weeks"]:
            continue
        # Valve returns the current/recent week first. Use the first valid record.
        week = next((w for w in chunk["weeks"] if isinstance(w, dict) and isinstance(w.get("win_percent"), (int, float))), None)
        if week is None:
            continue
        win_rate = float(week["win_percent"]) / 10000.0
        if 0.0 <= win_rate <= 1.0:
            updated[name] = replace(updated[name], win_rate=win_rate)
    return updated


def parse_valve_matchups(payload: object, heroes: dict[str, Hero]) -> dict[str, dict[str, dict[str, object]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("ranked_hero_data"), list):
        raise ValueError("Valve GetPlusHeroAllyAndEnemyData: unexpected JSON shape")

    id_to_name = {hero.id: name for name, hero in heroes.items() if hero.id is not None}
    matrix: dict[str, dict[str, dict[str, object]]] = {}

    # Each row describes one candidate hero. enemy_win_rate values correspond to
    # consecutive other-hero IDs starting at first_other_hero_id. Invalid/gap IDs
    # are simply ignored because they are absent from id_to_name.
    for row in payload["ranked_hero_data"]:
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
    return matrix


class DotaData:
    def __init__(self, root: Path | str = "data") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.hero_cache = self.root / "valve_heroes.json"
        self.stats_cache = self.root / "valve_plus_stats.json"
        self.matchup_cache = self.root / "valve_matchups.json"
        self.heroes = fallback_heroes()
        self.matchups: dict[str, dict[str, dict[str, object]]] = {}
        self._using_valve_cache = False
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
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _load_caches(self) -> None:
        hero_payload = self._load_json(self.hero_cache, None)
        if hero_payload is not None:
            try:
                self.heroes = parse_valve_hero_list(hero_payload)
                self._using_valve_cache = True
            except ValueError:
                self.heroes = fallback_heroes()

        stats_payload = self._load_json(self.stats_cache, None)
        if stats_payload is not None:
            try:
                self.heroes = parse_valve_plus_stats(stats_payload, self.heroes)
                self._using_valve_cache = True
            except ValueError:
                pass

        cached_matchups = self._load_json(self.matchup_cache, {})
        if isinstance(cached_matchups, dict):
            self.matchups = cached_matchups

    @property
    def source(self) -> str:
        return "Valve dota2.com cache" if self._using_valve_cache else "offline fallback"

    @staticmethod
    def _get_json(url: str, timeout: float = 15.0):
        req = urllib.request.Request(url, headers={"User-Agent": "Dota2Coach/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}: {url}")
            raw = response.read()
            return json.loads(raw.decode("utf-8"))

    def sync_heroes(self, timeout: float = 15.0) -> int:
        hero_payload = self._get_json(VALVE_HERO_LIST, timeout)
        heroes = parse_valve_hero_list(hero_payload)

        stats_payload = self._get_json(VALVE_PLUS_STATS, timeout)
        heroes = parse_valve_plus_stats(stats_payload, heroes)

        self._atomic_json(self.hero_cache, hero_payload)
        self._atomic_json(self.stats_cache, stats_payload)
        self.heroes = heroes
        self._using_valve_cache = True
        return len(self.heroes)

    def sync_matchups(self, enemy_names: Iterable[str], timeout: float = 15.0) -> int:
        payload = self._get_json(VALVE_PLUS_MATCHUPS, timeout)
        matrix = parse_valve_matchups(payload, self.heroes)
        self.matchups = matrix
        self._atomic_json(self.matchup_cache, matrix)
        requested = list(dict.fromkeys(enemy_names))
        return sum(1 for enemy in requested if matrix.get(enemy))

    def matchup(self, candidate: str, enemy: str) -> tuple[float, int | None] | None:
        row = self.matchups.get(enemy, {}).get(candidate)
        if not isinstance(row, dict):
            return None
        wr = row.get("candidate_win_rate")
        games = row.get("games")
        if not isinstance(wr, (int, float)):
            return None
        return float(wr), games if isinstance(games, int) else None

    def portrait_url(self, hero: Hero) -> str:
        return f"{STEAM_CDN}/apps/dota2/images/dota_react/heroes/{hero.slug}.png"

    def download_portraits(self, output: Path | str = "assets/heroes", timeout: float = 15.0) -> int:
        out = Path(output)
        out.mkdir(parents=True, exist_ok=True)
        count = 0
        for hero in self.heroes.values():
            target = out / f"{hero.slug}.png"
            if target.exists() and target.stat().st_size > 1000:
                count += 1
                continue
            try:
                req = urllib.request.Request(self.portrait_url(hero), headers={"User-Agent": "Dota2Coach/2.0"})
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    data = response.read()
                if len(data) < 1000:
                    continue
                target.write_bytes(data)
                count += 1
            except (OSError, urllib.error.URLError, TimeoutError):
                continue
        return count
