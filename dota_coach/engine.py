from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import sqrt
from typing import Iterable

from .data import DotaData, Hero, RANK_NAMES

POSITION_ALIASES = {
    "1": "1 Carry",
    "carry": "1 Carry",
    "pos1": "1 Carry",
    "1 carry": "1 Carry",
    "2": "2 Mid",
    "mid": "2 Mid",
    "pos2": "2 Mid",
    "2 mid": "2 Mid",
    "3": "3 Offlane",
    "offlane": "3 Offlane",
    "off": "3 Offlane",
    "pos3": "3 Offlane",
    "3 offlane": "3 Offlane",
    "4": "4 Support",
    "support": "4 Support",
    "soft support": "4 Support",
    "pos4": "4 Support",
    "4 support": "4 Support",
    "5": "5 Hard Support",
    "hard support": "5 Hard Support",
    "pos5": "5 Hard Support",
    "5 hard support": "5 Hard Support",
}

RANK_ALIASES: dict[str, int | None] = {
    "all": None,
    "overall": None,
    "any": None,
    "1": 1,
    "herald": 1,
    "2": 2,
    "guardian": 2,
    "3": 3,
    "crusader": 3,
    "4": 4,
    "archon": 4,
    "5": 5,
    "legend": 5,
    "6": 6,
    "ancient": 6,
    "7": 7,
    "divine": 7,
    "8": 8,
    "immortal": 8,
}

POSITION_ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    "1 Carry": {
        "Carry": 15.0,
        "Escape": 5.0,
        "Pusher": 4.0,
        "Durable": 2.0,
        "Disabler": 1.0,
        "Nuker": 1.0,
        "Support": -12.0,
    },
    "2 Mid": {
        "Nuker": 9.0,
        "Escape": 7.0,
        "Carry": 6.0,
        "Initiator": 5.0,
        "Disabler": 4.0,
        "Pusher": 3.0,
        "Durable": 1.5,
        "Support": -7.0,
    },
    "3 Offlane": {
        "Initiator": 11.0,
        "Durable": 10.0,
        "Disabler": 8.0,
        "Pusher": 3.0,
        "Nuker": 2.0,
        "Escape": 2.0,
        "Support": 1.0,
        "Carry": -3.0,
    },
    "4 Support": {
        "Support": 13.0,
        "Disabler": 10.0,
        "Initiator": 7.0,
        "Nuker": 5.0,
        "Escape": 3.0,
        "Pusher": 2.0,
        "Durable": 1.0,
        "Carry": -8.0,
    },
    "5 Hard Support": {
        "Support": 15.0,
        "Disabler": 11.0,
        "Durable": 4.0,
        "Initiator": 4.0,
        "Nuker": 3.0,
        "Pusher": 2.0,
        "Escape": 1.0,
        "Carry": -11.0,
    },
}

# Generic Dota role tags are useful, but they are too broad to define a lane by
# themselves. These profile gates keep clearly wrong-role heroes from floating
# to the top simply because they cover many utility tags.
POSITION_REQUIRED_TAGS: dict[str, set[str]] = {
    "1 Carry": {"Carry"},
    "2 Mid": {"Carry", "Nuker", "Escape", "Initiator", "Pusher"},
    "3 Offlane": {"Initiator", "Durable", "Disabler", "Pusher"},
    "4 Support": {"Support", "Disabler", "Initiator", "Nuker"},
    "5 Hard Support": {"Support", "Disabler"},
}

POSITION_MISS_PENALTY = {
    "1 Carry": 18.0,
    "2 Mid": 13.0,
    "3 Offlane": 15.0,
    "4 Support": 15.0,
    "5 Hard Support": 18.0,
}

TEAM_NEEDS = {
    "Disabler": 5.0,
    "Initiator": 4.5,
    "Durable": 4.0,
    "Pusher": 3.0,
    "Support": 3.0,
    "Carry": 2.5,
    "Nuker": 2.0,
    "Escape": 1.5,
}

ROLE_TEXT = {
    "Carry": "добавляет поздний core-потенциал",
    "Support": "закрывает саппорт-функции",
    "Nuker": "добавляет быстрый урон",
    "Escape": "добавляет мобильность",
    "Disabler": "добавляет контроль",
    "Initiator": "даёт инициацию",
    "Durable": "даёт фронтлейн",
    "Pusher": "усиливает давление на строения",
}


@dataclass(frozen=True)
class Pick:
    hero: str
    score: float
    confidence: float
    reasons: tuple[str, ...]


def normalize_position(position: str) -> str:
    key = " ".join(position.strip().lower().split())
    if key not in POSITION_ALIASES:
        raise ValueError(f"Unknown position: {position}")
    return POSITION_ALIASES[key]


def normalize_rank_tier(rank: str | int | None) -> int | None:
    if rank is None:
        return None
    if isinstance(rank, int):
        if rank in RANK_NAMES:
            return rank
        raise ValueError(f"Unknown rank tier: {rank}")
    key = " ".join(str(rank).strip().lower().split())
    if key not in RANK_ALIASES:
        raise ValueError(
            "Unknown rank: " + str(rank) + ". Use all, Herald, Guardian, Crusader, Archon, Legend, Ancient, Divine or Immortal."
        )
    return RANK_ALIASES[key]


def rank_label(rank_tier: int | None) -> str:
    return RANK_NAMES.get(rank_tier, "All ranked") if rank_tier is not None else "All ranked"


def validate_draft(allies: list[Hero], enemies: list[Hero]) -> None:
    if len(allies) > 5 or len(enemies) > 5:
        raise ValueError("A Dota draft can contain at most 5 heroes per team")

    ally_ids = [hero.id for hero in allies]
    enemy_ids = [hero.id for hero in enemies]
    if len(ally_ids) != len(set(ally_ids)):
        raise ValueError("The allied draft contains the same hero more than once")
    if len(enemy_ids) != len(set(enemy_ids)):
        raise ValueError("The enemy draft contains the same hero more than once")

    overlap = set(ally_ids) & set(enemy_ids)
    if overlap:
        names = sorted(hero.name for hero in allies if hero.id in overlap)
        raise ValueError("A hero cannot be on both teams: " + ", ".join(names))


def _role_counts(heroes: Iterable[Hero]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for hero in heroes:
        counts.update(hero.roles)
    return counts


def _position_points(hero: Hero, position: str) -> tuple[float, float, list[str]]:
    weights = POSITION_ROLE_WEIGHTS[position]
    hero_roles = set(hero.roles)
    points = sum(weights.get(role, 0.0) for role in hero.roles)
    reasons: list[str] = []

    positive = sorted(
        ((weights.get(role, 0.0), role) for role in hero.roles if weights.get(role, 0.0) >= 4.0),
        reverse=True,
    )
    if positive:
        reasons.append(f"профиль {positive[0][1]} подходит для {position}")

    required = POSITION_REQUIRED_TAGS[position]
    has_profile = bool(hero_roles & required)
    if not has_profile:
        points -= POSITION_MISS_PENALTY[position]
        reasons.append(f"слабый профиль для {position}")

    if position == "1 Carry" and "Support" in hero_roles and "Carry" not in hero_roles:
        points -= 8.0
    elif position == "2 Mid" and "Support" in hero_roles and not ({"Carry", "Nuker"} & hero_roles):
        points -= 7.0
    elif position == "3 Offlane" and hero_roles == {"Carry"}:
        points -= 8.0
    elif position in {"4 Support", "5 Hard Support"} and "Carry" in hero_roles and "Support" not in hero_roles:
        points -= 6.0

    if not hero.roles:
        points -= 8.0

    position_confidence = 1.0 if has_profile else 0.25
    return points, position_confidence, reasons


def _meta_points(hero: Hero, rank_tier: int | None) -> tuple[float, float, list[str]]:
    picks, wins = hero.pick_win_for_rank(rank_tier)
    if picks <= 0:
        return -1.5, 0.0, ["нет надёжной публичной статистики"]

    win_rate = wins / picks
    sample_confidence = hero.sample_confidence_for_rank(rank_tier)
    # heroStats is medal-specific but still not position-specific, so keep this
    # signal secondary to position fit and cap it tightly.
    raw = (win_rate - 0.50) * 120.0
    points = max(-6.0, min(6.0, raw)) * sample_confidence
    reasons: list[str] = []
    bracket = RANK_NAMES.get(rank_tier, "ranked") if rank_tier is not None else "ranked"
    if points >= 1.8:
        reasons.append(f"{bracket} WR {win_rate:.1%} на {picks:,} играх")
    elif points <= -2.2:
        reasons.append(f"{bracket} WR ниже среднего: {win_rate:.1%}")
    return points, sample_confidence, reasons


def _team_points(hero: Hero, ally_counts: Counter[str], position: str) -> tuple[float, list[str]]:
    weights = POSITION_ROLE_WEIGHTS[position]
    points = 0.0
    hits: list[tuple[float, str]] = []
    for role, bonus in TEAM_NEEDS.items():
        if role not in hero.roles or ally_counts.get(role, 0) > 0:
            continue
        # Do not let a generic team-need bonus rescue a hero that conflicts with
        # the selected position (for example Support on position 1).
        if weights.get(role, 0.0) < 0:
            continue
        points += bonus
        hits.append((bonus, role))

    ally_roles = set(ally_counts)
    hero_roles = set(hero.roles)
    if "Initiator" in ally_roles and "Nuker" in hero_roles:
        points += 2.0
    if "Disabler" in ally_roles and "Carry" in hero_roles:
        points += 1.5
    if "Carry" in ally_roles and "Support" in hero_roles:
        points += 2.0
    if "Durable" in ally_roles and ("Carry" in hero_roles or "Nuker" in hero_roles):
        points += 1.0

    reasons: list[str] = []
    if hits:
        role = max(hits)[1]
        reasons.append(ROLE_TEXT.get(role, f"закрывает нехватку {role}"))
    return points, reasons


def _enemy_role_points(hero: Hero, enemies: list[Hero]) -> tuple[float, list[str]]:
    """Small role-tag fallback when detailed matchup rows are missing.

    These are deliberately weak composition heuristics. They must never outrank
    position fit or pretend to model ability-level counters.
    """
    enemy_counts = _role_counts(enemies)
    hero_roles = set(hero.roles)
    points = 0.0
    reasons: list[str] = []

    if enemy_counts.get("Escape", 0) and "Disabler" in hero_roles:
        bonus = min(2.5, 1.5 + 0.4 * enemy_counts["Escape"])
        points += bonus
        reasons.append("контроль полезен против мобильного драфта")
    if enemy_counts.get("Pusher", 0) and "Initiator" in hero_roles:
        points += 1.25
        reasons.append("инициация помогает наказывать сплит-пуш")
    if enemy_counts.get("Initiator", 0) and "Escape" in hero_roles:
        points += 1.0
        reasons.append("мобильность помогает переживать вражеский заход")
    if enemy_counts.get("Carry", 0) >= 2 and "Disabler" in hero_roles:
        points += 0.75

    return min(5.0, points), reasons


def _matchup_points(data: DotaData, hero: Hero, enemies: list[Hero]) -> tuple[float, float, list[str]]:
    if not enemies:
        return 0.0, 0.0, []

    total = 0.0
    evidence = 0.0
    rows: list[tuple[float, int, str]] = []
    for enemy in enemies:
        matchup = data.candidate_win_rate_vs(hero.id, enemy.id)
        if matchup is None:
            continue
        win_rate, games = matchup
        # OpenDota's hero matchup endpoint is supplemental aggregate evidence,
        # not a current-role/current-bracket public truth. Keep it weaker than fit.
        reliability = min(1.0, sqrt(max(games, 0) / 1800.0))
        delta = max(-4.5, min(4.5, (win_rate - 0.50) * 45.0)) * reliability
        total += delta
        evidence += reliability
        rows.append((win_rate, games, enemy.name))

    total = max(-10.0, min(10.0, total))
    reasons: list[str] = []
    if rows:
        best = max(rows, key=lambda row: row[0])
        worst = min(rows, key=lambda row: row[0])
        if best[0] >= 0.53:
            reasons.append(f"aggregate-матчап хорош против {best[2]} ({best[0]:.1%}, {best[1]} игр)")
        if worst[0] <= 0.47:
            reasons.append(f"aggregate-матчап рискованный против {worst[2]} ({worst[0]:.1%}, {worst[1]} игр)")
    return total, min(1.0, evidence / max(1, len(enemies))), reasons


def score_hero(
    data: DotaData,
    hero: Hero,
    allies: list[Hero],
    enemies: list[Hero],
    position: str,
    rank_tier: str | int | None = None,
) -> Pick:
    position = normalize_position(position)
    rank_tier = normalize_rank_tier(rank_tier)
    score = 50.0
    reasons: list[str] = []

    points, position_confidence, extra = _position_points(hero, position)
    score += points
    reasons.extend(extra)

    points, meta_confidence, extra = _meta_points(hero, rank_tier)
    score += points
    reasons.extend(extra)

    ally_counts = _role_counts(allies)
    points, extra = _team_points(hero, ally_counts, position)
    score += points
    reasons.extend(extra)

    points, extra = _enemy_role_points(hero, enemies)
    score += points
    reasons.extend(extra)

    points, matchup_confidence, extra = _matchup_points(data, hero, enemies)
    score += points
    reasons.extend(extra)

    confidence = (
        0.25
        + 0.25 * position_confidence
        + 0.30 * meta_confidence
        + 0.20 * matchup_confidence
    )
    confidence = max(0.0, min(1.0, confidence))
    unique_reasons = tuple(dict.fromkeys(reasons))[:5]
    if not unique_reasons:
        unique_reasons = ("нейтральный вариант по доступным данным",)

    return Pick(
        hero=hero.name,
        score=round(max(1.0, min(99.0, score)), 2),
        confidence=round(confidence, 3),
        reasons=unique_reasons,
    )


def recommend(
    data: DotaData,
    allies: list[Hero],
    enemies: list[Hero],
    position: str,
    limit: int = 5,
    rank_tier: str | int | None = None,
) -> list[Pick]:
    position = normalize_position(position)
    rank_tier = normalize_rank_tier(rank_tier)
    validate_draft(allies, enemies)
    unavailable = {hero.id for hero in allies + enemies}
    candidates = [hero for hero in data.heroes.values() if hero.id not in unavailable]
    picks = [score_hero(data, hero, allies, enemies, position, rank_tier) for hero in candidates]
    picks.sort(key=lambda pick: (-pick.score, -pick.confidence, pick.hero))
    return picks[: max(1, limit)]


def build_strategy(allies: list[Hero], enemies: list[Hero], position: str | None = None) -> list[str]:
    validate_draft(allies, enemies)
    ally_counts = _role_counts(allies)
    enemy_counts = _role_counts(enemies)
    ally_roles = set(ally_counts)
    enemy_roles = set(enemy_counts)
    lines: list[str] = []

    if position is not None:
        position = normalize_position(position)
        lane_plan = {
            "1 Carry": "На линии приоритет — стабильный фарм и сохранение ресурсов; не разменивайте HP ради лишнего харасса без выгоды по крипам.",
            "2 Mid": "На миде сначала обеспечьте волну и контроль рун, а ротации делайте после пропушенной линии, чтобы не отдавать бесплатный опыт.",
            "3 Offlane": "На оффлейне давите вражеского carry ресурсами, но не ломайте позицию ради одного лишнего удара без вижена на саппортов.",
            "4 Support": "На четвёрке помогите оффлейну стабилизировать линию, затем ищите ротацию только когда уход не оставляет core без линии.",
            "5 Hard Support": "На пятёрке защищайте экономику carry: контролируйте отводы, вижен и расходники, не забирая безопасный фарм и опыт без причины.",
        }
        lines.append(lane_plan[position])

    if "Initiator" in ally_roles:
        lines.append("Начинайте ключевые драки своим инициатором и заранее ставьте вижен под его заход.")
    else:
        lines.append("Надёжной инициации мало: играйте от контратаки, вижена и ошибок соперника.")

    if "Disabler" in enemy_roles:
        lines.append("У врага много контроля: core-героям заранее планировать BKB/диспел и не показываться первыми.")
    if "Escape" in enemy_roles:
        lines.append("Против мобильных целей сохраняйте мгновенный контроль; не тратьте все disable в первый фронтлейн.")
    if "Pusher" in enemy_roles:
        lines.append("Не отдавайте боковые линии бесплатно: заранее пропушивайте волны и держите телепорты на защиту вышек.")
    if "Durable" in enemy_roles:
        lines.append("Не обязательно начинать с самого толстого героя: ищите доступ к backline и более уязвимым целям.")
    if "Nuker" in enemy_roles and "Durable" not in ally_roles:
        lines.append("Против сильного burst без своего фронтлейна не стойте кучно и не показывайте несколько уязвимых героев одной информацией.")

    if "Pusher" in ally_roles:
        lines.append("После выигранной драки сразу конвертируйте преимущество в башню, Roshan или контроль территории.")
    else:
        lines.append("После выигранной драки приоритет — Roshan, линии и территория, а не длинная погоня за одним героем.")

    if "Initiator" in ally_roles and "Nuker" in ally_roles:
        lines.append("У состава есть связка инициация + burst: заранее определите, кто начинает, а кто мгновенно продолжает контроль и урон.")
    if "Carry" in ally_roles:
        lines.append("Сохраняйте безопасный фарм для основного core и играйте вокруг его первого сильного тайминга предметов.")
    if len(allies) >= 3 and "Durable" not in ally_roles:
        lines.append("У состава нет явного фронтлейна: core не должен первым давать информацию о своей позиции.")
    if len(allies) >= 3 and "Support" not in ally_roles:
        lines.append("Саппорт-функций мало: особенно важны вижен, сейв-предметы и дисциплина по ресурсам.")
    if len(allies) >= 3 and "Disabler" not in ally_roles and "Escape" in enemy_roles:
        lines.append("Контроля мало против мобильного драфта: избегайте длинных погонь и играйте от узких проходов/объектов.")

    return list(dict.fromkeys(lines))[:7]
