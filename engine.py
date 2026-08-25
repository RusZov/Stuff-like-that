from __future__ import annotations

from dataclasses import dataclass

from dota_data import DotaData, Hero, POSITION_POOLS

@dataclass(frozen=True)
class Pick:
    hero: str
    score: float
    why: str


def _role_set(data: DotaData, names: list[str]) -> set[str]:
    out: set[str] = set()
    for name in names:
        hero = data.heroes.get(name)
        if hero:
            out.update(hero.roles)
    return out


def score_hero(data: DotaData, hero: Hero, allies: list[str], enemies: list[str], role: str) -> Pick:
    score = 50.0
    reasons: list[str] = []
    role_pool = POSITION_POOLS.get(role, set())
    if hero.name in role_pool:
        score += 20
        reasons.append("подходит на выбранную позицию")
    else:
        score -= 14

    if hero.win_rate is not None:
        meta = max(-8.0, min(8.0, (hero.win_rate - 0.50) * 100.0 * 1.5))
        score += meta
        if meta >= 2:
            reasons.append(f"хорошая общая статистика ({hero.win_rate:.1%})")

    matchup_points = []
    for enemy in enemies:
        matchup = data.matchup(hero.name, enemy)
        if matchup:
            wr, games = matchup
            if games >= 20:
                pts = max(-7.0, min(7.0, (wr - 0.50) * 50.0))
                score += pts
                matchup_points.append((pts, enemy, wr, games))
    if matchup_points:
        best = max(matchup_points, key=lambda x: x[0])
        if best[0] > 0.5:
            reasons.append(f"статистически хорош против {best[1]} ({best[2]:.1%}, {best[3]} игр)")
        worst = min(matchup_points, key=lambda x: x[0])
        if worst[0] < -1.5:
            reasons.append(f"есть риск против {worst[1]} ({worst[2]:.1%})")

    ally_roles = _role_set(data, allies)
    hero_roles = set(hero.roles)
    needs = [
        ("Disabler", 5.0, "добавляет контроль"),
        ("Initiator", 5.0, "даёт инициацию"),
        ("Durable", 4.0, "добавляет фронтлейн"),
        ("Pusher", 3.0, "помогает забирать строения"),
    ]
    for tag, bonus, text in needs:
        if tag in hero_roles and tag not in ally_roles:
            score += bonus
            reasons.append(text)

    return Pick(hero.name, max(1.0, min(99.0, score)), ", ".join(reasons[:3]) or "стабильный вариант")


def recommendations(data: DotaData, allies: list[str], enemies: list[str], role: str, limit: int = 5) -> list[Pick]:
    unavailable = set(allies + enemies)
    candidates = [h for h in data.heroes.values() if h.name not in unavailable]
    ranked = sorted((score_hero(data, h, allies, enemies, role) for h in candidates), key=lambda p: (-p.score, p.hero))
    return ranked[:limit]


def strategy(data: DotaData, allies: list[str], enemies: list[str]) -> str:
    ally_roles = _role_set(data, allies)
    enemy_roles = _role_set(data, enemies)
    lines = ["ТАКТИКА НА МАТЧ"]

    if "Initiator" in ally_roles:
        lines.append("• Не отдавайте первый контакт случайно: начинайте драки своим инициатором и заранее ставьте вижен.")
    else:
        lines.append("• У состава мало надёжной инициации: играйте от контратаки, вижена и ошибок соперника.")
    if "Disabler" in enemy_roles:
        lines.append("• У врага много контроля: core-героям заранее оценить BKB/диспел/позиционную защиту.")
    if "Pusher" in enemy_roles:
        lines.append("• Не раздавайте бесплатные линии: заранее защищайте вышки и быстро реагируйте на сплит-пуш.")
    if "Pusher" in ally_roles:
        lines.append("• После выигранной драки сразу конвертируйте преимущество в башню, Roshan или контроль карты.")
    else:
        lines.append("• После выигранной драки приоритет: Roshan/территория/линии, а не длинная погоня за одним героем.")
    if "Carry" in enemy_roles:
        lines.append("• Сохраняйте ключевой контроль на вражеского core; не тратьте все способности в самого толстого героя.")
    if "Escape" in enemy_roles:
        lines.append("• Против мобильных героев держите instant-disable и не начинайте погоню без информации о телепортах.")

    lines.append("• Подсказки используют только выбранные/видимые данные и не выполняют действий в Dota 2.")
    return "\n".join(lines)
