from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from dota_data import DotaData, Hero, POSITION_POOLS


@dataclass(frozen=True)
class Pick:
    hero: str
    score: float
    why: str


# How valuable each hero tag is for a specific Dota position.
# Positive values reward a tag, negative values penalize a tag that usually
# conflicts with the selected position. The explicit POSITION_POOLS check below
# remains the strongest position-fit signal.
POSITION_ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    "1 Carry": {
        "Carry": 11.0,
        "Escape": 5.0,
        "Pusher": 4.0,
        "Durable": 2.0,
        "Nuker": 1.5,
        "Disabler": 1.0,
        "Initiator": 0.5,
        "Support": -10.0,
    },
    "2 Mid": {
        "Nuker": 10.0,
        "Escape": 7.0,
        "Initiator": 5.0,
        "Disabler": 4.0,
        "Pusher": 4.0,
        "Carry": 3.0,
        "Durable": 1.5,
        "Support": -7.0,
    },
    "3 Offlane": {
        "Initiator": 10.0,
        "Durable": 9.0,
        "Disabler": 7.0,
        "Pusher": 3.0,
        "Nuker": 2.0,
        "Escape": 1.5,
        "Support": 1.0,
        "Carry": -2.0,
    },
    "4 Support": {
        "Support": 11.0,
        "Disabler": 9.0,
        "Initiator": 6.0,
        "Nuker": 4.0,
        "Escape": 3.0,
        "Pusher": 2.0,
        "Durable": 1.0,
        "Carry": -7.0,
    },
    "5 Hard Support": {
        "Support": 13.0,
        "Disabler": 10.0,
        "Initiator": 4.0,
        "Nuker": 3.0,
        "Durable": 3.0,
        "Pusher": 2.0,
        "Escape": 1.0,
        "Carry": -9.0,
    },
}


# Missing functions are useful regardless of the selected lane/position.
TEAM_NEED_WEIGHTS: dict[str, float] = {
    "Disabler": 5.0,
    "Initiator": 4.5,
    "Durable": 4.0,
    "Pusher": 3.5,
    "Carry": 2.5,
    "Support": 2.5,
    "Nuker": 2.0,
    "Escape": 1.5,
}


ROLE_REASON_TEXT = {
    "Carry": "даёт команде core-потенциал",
    "Support": "закрывает саппорт-функции",
    "Nuker": "добавляет burst-урон",
    "Escape": "даёт мобильность и выживаемость",
    "Disabler": "добавляет контроль",
    "Initiator": "даёт инициацию",
    "Durable": "добавляет фронтлейн",
    "Pusher": "усиливает давление на строения",
}


def _role_counts(data: DotaData, names: list[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for name in names:
        hero = data.heroes.get(name)
        if hero:
            counts.update(hero.roles)
    return counts


def _role_set(data: DotaData, names: list[str]) -> set[str]:
    return set(_role_counts(data, names))


def _position_score(hero: Hero, position: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    hero_roles = set(hero.roles)
    role_pool = POSITION_POOLS.get(position, set())

    if hero.name in role_pool:
        score += 24.0
        reasons.append("подходит на выбранную позицию")
    else:
        # Strong enough to stop supports from floating into carry/mid results
        # only because they cover many generic team needs.
        score -= 28.0

    weights = POSITION_ROLE_WEIGHTS.get(position, {})
    weighted_hits: list[tuple[float, str]] = []
    for tag in hero_roles:
        weight = weights.get(tag, 0.0)
        score += weight
        if weight >= 4.0:
            weighted_hits.append((weight, tag))

    if weighted_hits:
        _, best_tag = max(weighted_hits)
        reasons.append(f"сильный профиль {best_tag} для {position}")

    return score, reasons


def _team_balance_score(hero: Hero, ally_counts: Counter[str]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    hero_roles = set(hero.roles)

    missing_hits: list[tuple[float, str]] = []
    for tag, bonus in TEAM_NEED_WEIGHTS.items():
        if tag not in hero_roles:
            continue
        count = ally_counts.get(tag, 0)
        if count == 0:
            score += bonus
            missing_hits.append((bonus, tag))
        elif count >= 2 and tag in {"Initiator", "Durable", "Pusher", "Nuker"}:
            # Mild diminishing return only. Duplicate roles can still be useful.
            score -= 1.0

    if missing_hits:
        _, best_tag = max(missing_hits)
        reasons.append(ROLE_REASON_TEXT.get(best_tag, f"закрывает нехватку {best_tag}"))

    # Simple complementary synergies based on visible role tags.
    ally_roles = set(ally_counts)
    if "Initiator" in ally_roles and "Nuker" in hero_roles:
        score += 2.5
        reasons.append("может быстро продолжать инициацию команды")
    if "Disabler" in ally_roles and "Carry" in hero_roles:
        score += 2.0
    if "Durable" in ally_roles and ("Carry" in hero_roles or "Nuker" in hero_roles):
        score += 1.5
    if "Carry" in ally_roles and "Support" in hero_roles:
        score += 2.5

    return score, reasons


def _enemy_response_score(hero: Hero, enemy_counts: Counter[str]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    hero_roles = set(hero.roles)
    enemy_roles = set(enemy_counts)

    if "Escape" in enemy_roles and "Disabler" in hero_roles:
        score += 5.0
        reasons.append("контроль полезен против мобильных врагов")
    if "Carry" in enemy_roles and "Disabler" in hero_roles:
        score += 3.0
    if "Initiator" in enemy_roles and "Escape" in hero_roles:
        score += 2.0
        reasons.append("мобильность помогает переживать вражеский заход")
    if "Pusher" in enemy_roles and ("Initiator" in hero_roles or "Escape" in hero_roles):
        score += 2.0
    if "Durable" in enemy_roles and "Pusher" in hero_roles:
        # If bursting the frontline is awkward, map pressure is an alternate win condition.
        score += 1.5

    return score, reasons


def _matchup_score(data: DotaData, hero: Hero, enemies: list[str]) -> tuple[float, list[str]]:
    points: list[tuple[float, str, float, int | None]] = []
    for enemy in enemies:
        matchup = data.matchup(hero.name, enemy)
        if not matchup:
            continue
        win_rate, games = matchup
        if games is not None and games < 20:
            continue
        pts = max(-7.0, min(7.0, (win_rate - 0.50) * 50.0))
        points.append((pts, enemy, win_rate, games))

    if not points:
        return 0.0, []

    # Do not allow five matchup rows to overwhelm position fit by themselves.
    total = max(-16.0, min(16.0, sum(item[0] for item in points)))
    reasons: list[str] = []

    best = max(points, key=lambda item: item[0])
    if best[0] > 0.5:
        if best[3] is None:
            reasons.append(f"хорош по Dota Plus против {best[1]} ({best[2]:.1%})")
        else:
            reasons.append(f"статистически хорош против {best[1]} ({best[2]:.1%}, {best[3]} игр)")

    worst = min(points, key=lambda item: item[0])
    if worst[0] < -1.5:
        reasons.append(f"есть риск против {worst[1]} ({worst[2]:.1%})")

    return total, reasons


def score_hero(data: DotaData, hero: Hero, allies: list[str], enemies: list[str], role: str) -> Pick:
    score = 50.0
    reasons: list[str] = []

    position_points, position_reasons = _position_score(hero, role)
    score += position_points
    reasons.extend(position_reasons)

    matchup_points, matchup_reasons = _matchup_score(data, hero, enemies)
    score += matchup_points
    reasons.extend(matchup_reasons)

    if hero.win_rate is not None:
        meta = max(-7.0, min(7.0, (hero.win_rate - 0.50) * 100.0 * 1.35))
        score += meta
        if meta >= 2.0:
            reasons.append(f"хорошая общая статистика ({hero.win_rate:.1%})")
        elif meta <= -3.0:
            reasons.append(f"слабее по текущей общей статистике ({hero.win_rate:.1%})")

    ally_counts = _role_counts(data, allies)
    team_points, team_reasons = _team_balance_score(hero, ally_counts)
    score += team_points
    reasons.extend(team_reasons)

    enemy_counts = _role_counts(data, enemies)
    response_points, response_reasons = _enemy_response_score(hero, enemy_counts)
    score += response_points
    reasons.extend(response_reasons)

    # Keep explanations readable while exposing more than the old 3 reasons.
    unique_reasons = list(dict.fromkeys(reasons))
    explanation = ", ".join(unique_reasons[:5]) or "стабильный вариант"
    return Pick(hero.name, max(1.0, min(99.0, score)), explanation)


def recommendations(data: DotaData, allies: list[str], enemies: list[str], role: str, limit: int = 5) -> list[Pick]:
    unavailable = set(allies + enemies)
    candidates = [hero for hero in data.heroes.values() if hero.name not in unavailable]
    ranked = sorted(
        (score_hero(data, hero, allies, enemies, role) for hero in candidates),
        key=lambda pick: (-pick.score, pick.hero),
    )
    return ranked[:limit]


def strategy(data: DotaData, allies: list[str], enemies: list[str]) -> str:
    ally_counts = _role_counts(data, allies)
    enemy_counts = _role_counts(data, enemies)
    ally_roles = set(ally_counts)
    enemy_roles = set(enemy_counts)
    lines = ["ТАКТИКА НА МАТЧ"]

    if "Initiator" in ally_roles:
        lines.append("• Начинайте ключевые драки своим инициатором и заранее готовьте вижен под его заход.")
    else:
        lines.append("• У состава мало надёжной инициации: играйте от контратаки, вижена и ошибок соперника.")

    if "Disabler" in enemy_roles:
        lines.append("• У врага много контроля: core-героям заранее оценить BKB/диспел/позиционную защиту.")
    if "Escape" in enemy_roles:
        lines.append("• Против мобильных героев сохраняйте instant-disable и не тратьте весь контроль в первый фронтлейн.")
    if "Durable" in enemy_roles:
        lines.append("• Не обязательно начинать с самого толстого героя: ищите доступ к backline и слабым целям.")
    if "Pusher" in enemy_roles:
        lines.append("• Не отдавайте бесплатные линии: заранее защищайте вышки и реагируйте на сплит-пуш.")

    if "Pusher" in ally_roles:
        lines.append("• После выигранной драки сразу конвертируйте преимущество в башню, Roshan или контроль карты.")
    else:
        lines.append("• После выигранной драки приоритет: Roshan, территория и линии, а не длинная погоня.")

    if "Nuker" in ally_roles and "Initiator" in ally_roles:
        lines.append("• У состава есть burst после инициации: заранее договоритесь, кто начинает и кто мгновенно продолжает.")
    if "Carry" in ally_roles:
        lines.append("• Не ломайте экономику core без причины: саппортам отдавать безопасный фарм и играть вокруг его тайминга.")
    if "Support" not in ally_roles and len(allies) >= 3:
        lines.append("• В составе мало саппорт-функций: особенно важны вижен, сейв-предметы и дисциплина по ресурсам.")
    if "Durable" not in ally_roles and len(allies) >= 3:
        lines.append("• Нет явного фронтлейна: не показывайте core первым и начинайте драки только с хорошей позиции.")

    lines.append("• Подсказки используют только выбранные/видимые данные и не выполняют действий в Dota 2.")
    return "\n".join(lines)
