from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .data import DotaData, Hero, OPENDOTA_MATCHUP_WINDOW_DAYS
from .engine import Pick, build_strategy, normalize_position, normalize_rank_tier, recommend, validate_draft

# Matchup evidence is supplemental. A stalled optional endpoint must not make an
# otherwise usable draft recommendation wait through the normal robust retry
# budget that protects canonical roster/meta refreshes.
OPTIONAL_MATCHUP_TIMEOUT_SECONDS = 3.0
OPTIONAL_MATCHUP_ATTEMPTS = 1


@dataclass(frozen=True)
class DraftResult:
    picks: tuple[Pick, ...]
    tactics: tuple[str, ...]
    warnings: tuple[str, ...]
    source_notes: tuple[str, ...]


def _role_counts(heroes: list[Hero]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for hero in heroes:
        counts.update(hero.roles)
    return counts


def _calibrate_pick(pick: Pick) -> Pick:
    """Shrink extreme scores when the available evidence is weak.

    The raw engine score is intentionally explainable and additive. For user-facing
    ranking we additionally pull low-confidence estimates toward neutral instead of
    letting sparse evidence look as certain as a fully-supported recommendation.
    """
    strength = 0.65 + 0.35 * max(0.0, min(1.0, pick.confidence))
    calibrated = 50.0 + (pick.score - 50.0) * strength
    calibrated = round(max(1.0, min(99.0, calibrated)), 2)
    if abs(calibrated - pick.score) < 0.75:
        return pick
    reasons = tuple(dict.fromkeys((*pick.reasons, "оценка слегка снижена из-за качества доступных данных")))[:5]
    return Pick(hero=pick.hero, score=calibrated, confidence=pick.confidence, reasons=reasons)


def _tactical_additions(allies: list[Hero], enemies: list[Hero], position: str) -> list[str]:
    ally = _role_counts(allies)
    enemy = _role_counts(enemies)
    lines: list[str] = []

    if ally.get("Disabler", 0) == 0 and enemy.get("Escape", 0) >= 2:
        lines.append("Главный риск драфта — мало надёжного контроля против мобильных целей: не строить план на длинной погоне, играть вокруг объектов и узких проходов.")
    if ally.get("Initiator", 0) == 0 and ally.get("Pusher", 0) > 0:
        lines.append("Без явной инициации ценнее играть через давление линий и вынужденные реакции соперника, а не искать фронтальную драку 5v5.")
    if enemy.get("Pusher", 0) >= 2 and ally.get("Pusher", 0) == 0:
        lines.append("У врага заметно больше давления по строениям: заранее выталкивайте боковые линии перед Roshan и важными перемещениями.")
    if ally.get("Carry", 0) >= 2 and ally.get("Support", 0) == 0:
        lines.append("Состав перегружен core-функциями и беден на поддержку: распределяйте фарм заранее и компенсируйте это ранними utility-предметами и виженом.")

    if position == "2 Mid" and enemy.get("Initiator", 0) >= 2:
        lines.append("Мидеру против нескольких инициаторов важнее не показываться первым на волне после лейнинга: сначала информация, потом допуш линии.")
    elif position in {"4 Support", "5 Hard Support"} and enemy.get("Escape", 0) >= 2:
        lines.append("Саппорту стоит беречь мгновенный disable для мобильной цели, а не автоматически отдавать его в первого героя, который вошёл в драку.")
    elif position == "1 Carry" and enemy.get("Pusher", 0) >= 2:
        lines.append("Керри против сильного пуша нельзя бесконечно ждать идеального слота: заранее определите первый предметный тайминг, на котором готовы защищать объекты.")

    return lines


def _hero_names_for_ids(data: DotaData, hero_ids: Iterable[int] | None) -> set[str]:
    if not hero_ids:
        return set()
    wanted = {int(hero_id) for hero_id in hero_ids}
    names: set[str] = set()
    mapping = getattr(data, "heroes_by_id", None)
    if isinstance(mapping, dict):
        names.update(hero.name for hero_id, hero in mapping.items() if hero_id in wanted)
    for hero in getattr(data, "heroes", {}).values():
        if hero.id in wanted:
            names.add(hero.name)
    return names


def _load_matchups_fail_fast(data: DotaData, enemies: list[Hero], warnings: list[str]) -> None:
    """Load optional matchup rows without letting a degraded endpoint stall MVP UX.

    The default HTTP client intentionally has a larger timeout/retry budget for
    canonical Valve/OpenDota roster/meta refreshes. Matchups are only a weak
    pro/league signal, so temporarily tighten that budget and stop the batch
    after the first source failure. The client's normal policy is restored even
    if a loader raises unexpectedly, and a later coach call may retry because
    DotaData does not cache transient matchup failures.
    """
    matchup_loader = getattr(data, "load_enemy_matchups", None)
    if not enemies or not callable(matchup_loader):
        return

    client = getattr(data, "client", None)
    old_timeout = getattr(client, "timeout", None)
    old_attempts = getattr(client, "attempts", None)
    changed_timeout = isinstance(old_timeout, (int, float))
    changed_attempts = isinstance(old_attempts, int)

    if changed_timeout:
        client.timeout = min(float(old_timeout), OPTIONAL_MATCHUP_TIMEOUT_SECONDS)
    if changed_attempts:
        client.attempts = min(int(old_attempts), OPTIONAL_MATCHUP_ATTEMPTS)

    try:
        for index, enemy in enumerate(enemies):
            matchup_loader([enemy.id])
            status = data.source_status.get(f"OpenDota matchups:{enemy.id}", "")
            if not status.startswith("error:"):
                continue

            warnings.append(
                f"matchup-данные для {enemy.name} недоступны; использованы только состав и мета"
            )
            remaining = len(enemies) - index - 1
            if remaining > 0:
                warnings.append(
                    f"ещё {remaining} matchup-запрос(а/ов) пропущено после сбоя необязательного источника, чтобы не задерживать рекомендацию"
                )
            break
    finally:
        if changed_timeout:
            client.timeout = old_timeout
        if changed_attempts:
            client.attempts = old_attempts


def coach_draft(
    data: DotaData,
    allies: list[Hero],
    enemies: list[Hero],
    position: str,
    limit: int = 5,
    rank_tier: str | int | None = None,
    excluded_hero_ids: Iterable[int] | None = None,
) -> DraftResult:
    """High-level MVP entry point used by CLI and draft-screen ingestion.

    It centralizes optional data loading so callers cannot accidentally get a
    matchup-free ranking merely because they forgot to preload OpenDota rows.
    ``excluded_hero_ids`` is used by draft ingestion for confidently recognized
    bans; those heroes must never be returned as recommendations.
    """
    position = normalize_position(position)
    rank_tier = normalize_rank_tier(rank_tier)
    validate_draft(allies, enemies)
    limit = max(1, int(limit))
    excluded_names = _hero_names_for_ids(data, excluded_hero_ids)

    warnings: list[str] = []

    lane_loader = getattr(data, "load_lane_roles", None)
    if callable(lane_loader):
        lane_loader([1, 2, 3])
        for lane in (1, 2, 3):
            status = data.source_status.get(f"OpenDota lane role:{lane}", "")
            if status.startswith("error:"):
                warnings.append(f"lane-role {lane} недоступен; позиционный score будет менее точным")

    _load_matchups_fail_fast(data, enemies, warnings)

    # Confidence calibration is candidate-specific and can legitimately reorder
    # close raw scores. Therefore calibrate the complete available candidate pool
    # before applying the user-facing top-N cutoff; truncating first could hide a
    # better high-confidence pick just below the raw-score boundary.
    hero_count = len(getattr(data, "heroes", {}))
    pool_limit = max(limit, hero_count)
    raw = recommend(data, allies, enemies, position, limit=pool_limit, rank_tier=rank_tier)
    if excluded_names:
        raw = [pick for pick in raw if pick.hero not in excluded_names]
    picks = sorted((_calibrate_pick(pick) for pick in raw), key=lambda p: (-p.score, -p.confidence, p.hero))[:limit]

    relabeled: list[Pick] = []
    for pick in picks:
        reasons = tuple(reason.replace("aggregate-матчап", "pro/league матчап") for reason in pick.reasons)
        relabeled.append(Pick(pick.hero, pick.score, pick.confidence, reasons))

    tactics = build_strategy(allies, enemies, position)
    tactics.extend(_tactical_additions(allies, enemies, position))
    tactics = list(dict.fromkeys(tactics))[:9]

    source_notes = (
        "OpenDota heroStats: rolling public/medal meta sample used for the meta component.",
        f"OpenDota hero matchup endpoint: supplemental pro/league evidence over roughly {OPENDOTA_MATCHUP_WINDOW_DAYS} days; not bracket- or role-specific.",
        "Valve datafeed: canonical hero roster and current patch label.",
    )

    return DraftResult(
        picks=tuple(relabeled),
        tactics=tuple(tactics),
        warnings=tuple(dict.fromkeys(warnings)),
        source_notes=source_notes,
    )
