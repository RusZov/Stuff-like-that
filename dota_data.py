from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

OPEN_DOTA = "https://api.opendota.com/api"
STEAM_CDN = "https://cdn.cloudflare.steamstatic.com"

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

SPECIAL_SLUGS = {"Anti-Mage": "antimage", "Centaur Warrunner": "centaur", "Clockwerk": "rattletrap", "Doom": "doom_bringer", "Io": "wisp", "Lifestealer": "life_stealer", "Nature's Prophet": "furion", "Necrophos": "necrolyte", "Outworld Destroyer": "obsidian_destroyer", "Queen of Pain": "queenofpain", "Shadow Fiend": "nevermore", "Timbersaw": "shredder", "Underlord": "abyssal_underlord", "Windranger": "windrunner", "Wraith King": "skeleton_king"}


def hero_slug(name: str) -> str:
    return SPECIAL_SLUGS.get(name, name.lower().replace("'", "").replace("-", "_").replace(" ", "_"))


def fallback_roles(name: str) -> tuple[str, ...]:
    roles: list[str] = []
    if name in POSITION_POOLS["1 Carry"]: roles.append("Carry")
    if name in POSITION_POOLS["4 Support"] or name in POSITION_POOLS["5 Hard Support"]: roles.append("Support")
    if name in DISABLERS: roles.append("Disabler")
    if name in INITIATORS: roles.append("Initiator")
    if name in DURABLE: roles.append("Durable")
    if name in PUSHERS: roles.append("Pusher")
    if name in ESCAPE: roles.append("Escape")
    if name in POSITION_POOLS["2 Mid"] and "Carry" not in roles: roles.append("Nuker")
    return tuple(roles or ["Nuker"])


@dataclass(frozen=True)
class Hero:
    id: int | None
    name: str
    roles: tuple[str, ...]
    img: str = ""
    icon: str = ""
    primary_attr: str = ""
    attack_type: str = ""
    win_rate: float | None = None

    @property
    def slug(self) -> str:
        return hero_slug(self.name)


def fallback_heroes() -> dict[str, Hero]:
    return {name: Hero(None, name, fallback_roles(name)) for name in FALLBACK_HERO_NAMES}


def _public_win_rate(row: dict) -> float | None:
    wins = picks = 0
    for bracket in range(1, 9):
        p, w = row.get(f"{bracket}_pick"), row.get(f"{bracket}_win")
        if isinstance(p, (int, float)) and isinstance(w, (int, float)):
            picks += p; wins += w
    return wins / picks if picks > 0 else None


def parse_hero_stats(payload: object) -> dict[str, Hero]:
    if not isinstance(payload, list):
        raise ValueError("OpenDota heroStats: expected JSON array")
    result: dict[str, Hero] = {}
    for row in payload:
        if not isinstance(row, dict): continue
        name, hero_id = row.get("localized_name"), row.get("id")
        if not name or not isinstance(hero_id, int): continue
        result[str(name)] = Hero(hero_id, str(name), tuple(str(x) for x in row.get("roles", []) if x), str(row.get("img") or ""), str(row.get("icon") or ""), str(row.get("primary_attr") or ""), str(row.get("attack_type") or ""), _public_win_rate(row))
    if len(result) < 100:
        raise ValueError(f"OpenDota heroStats: suspiciously small hero list ({len(result)})")
    return result


class DotaData:
    def __init__(self, root: Path | str = "data") -> None:
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.hero_cache = self.root / "hero_stats.json"
        self.matchup_cache = self.root / "matchups.json"
        self.heroes = self._load_cached_heroes()
        self.matchups = self._load_json(self.matchup_cache, {})

    @staticmethod
    def _load_json(path: Path, default):
        try: return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): return default

    @staticmethod
    def _atomic_json(path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name): os.unlink(temp_name)

    def _load_cached_heroes(self) -> dict[str, Hero]:
        cached = self._load_json(self.hero_cache, None)
        if cached is not None:
            try:
                parsed = parse_hero_stats(cached)
                for name, hero in fallback_heroes().items(): parsed.setdefault(name, hero)
                return parsed
            except ValueError: pass
        return fallback_heroes()

    @property
    def source(self) -> str:
        return "OpenDota cache" if any(h.id is not None for h in self.heroes.values()) else "offline fallback"

    def _get_json(self, url: str, timeout: float = 12.0):
        req = urllib.request.Request(url, headers={"User-Agent": "Dota2Coach/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def sync_heroes(self, timeout: float = 12.0) -> int:
        payload = self._get_json(f"{OPEN_DOTA}/heroStats", timeout)
        parsed = parse_hero_stats(payload)
        for name, hero in fallback_heroes().items(): parsed.setdefault(name, hero)
        self._atomic_json(self.hero_cache, payload); self.heroes = parsed
        return len(self.heroes)

    def sync_matchups(self, enemy_names: Iterable[str], timeout: float = 12.0) -> int:
        ids_to_names = {h.id: h.name for h in self.heroes.values() if h.id is not None}
        updated = 0
        for enemy_name in dict.fromkeys(enemy_names):
            enemy = self.heroes.get(enemy_name)
            if not enemy or enemy.id is None: continue
            payload = self._get_json(f"{OPEN_DOTA}/heroes/{enemy.id}/matchups", timeout)
            if not isinstance(payload, list): continue
            values = {}
            for row in payload:
                if not isinstance(row, dict): continue
                candidate = ids_to_names.get(row.get("hero_id")); games = row.get("games_played", 0); enemy_wins = row.get("wins", 0)
                if candidate and isinstance(games, (int, float)) and games > 0 and isinstance(enemy_wins, (int, float)):
                    values[candidate] = {"games": int(games), "candidate_win_rate": float(1.0 - (enemy_wins / games))}
            if values: self.matchups[enemy_name] = values; updated += 1
        if updated: self._atomic_json(self.matchup_cache, self.matchups)
        return updated

    def matchup(self, candidate: str, enemy: str) -> tuple[float, int] | None:
        row = self.matchups.get(enemy, {}).get(candidate)
        if not isinstance(row, dict): return None
        wr, games = row.get("candidate_win_rate"), row.get("games")
        if not isinstance(wr, (int, float)) or not isinstance(games, int): return None
        return float(wr), games

    def portrait_url(self, hero: Hero) -> str:
        if hero.img: return STEAM_CDN + hero.img.split("?", 1)[0]
        return f"{STEAM_CDN}/apps/dota2/images/dota_react/heroes/{hero.slug}.png"

    def download_portraits(self, names: Iterable[str] | None = None, timeout: float = 12.0) -> tuple[int, list[str]]:
        folder = Path("assets/heroes"); folder.mkdir(parents=True, exist_ok=True)
        targets = list(names) if names is not None else sorted(self.heroes)
        ok, failed = 0, []
        for name in targets:
            hero = self.heroes.get(name)
            if not hero: continue
            path = folder / f"{hero.slug}.png"
            if path.exists() and path.stat().st_size > 1000: ok += 1; continue
            try:
                req = urllib.request.Request(self.portrait_url(hero), headers={"User-Agent": "Dota2Coach/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as r: data = r.read()
                if len(data) < 1000: raise ValueError("image response too small")
                path.write_bytes(data); ok += 1
            except Exception: failed.append(name)
        return ok, failed
