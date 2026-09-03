from __future__ import annotations

from dataclasses import dataclass

from .data import DotaData, Hero
from .draft_recognition import DraftRecognition, SlotRecognition
from .service import DraftResult, coach_draft


@dataclass(frozen=True)
class RecognizedDraftInput:
    allies: tuple[Hero, ...]
    enemies: tuple[Hero, ...]
    manual_slots: tuple[SlotRecognition, ...]
    ignored_bans: tuple[SlotRecognition, ...]


@dataclass(frozen=True)
class RecognizedCoachResult:
    recognized: RecognizedDraftInput
    coach: DraftResult


def _hero_by_id(data: DotaData, hero_id: int) -> Hero | None:
    mapping = getattr(data, "heroes_by_id", None)
    if isinstance(mapping, dict):
        hero = mapping.get(hero_id)
        if hero is not None:
            return hero
    for hero in getattr(data, "heroes", {}).values():
        if hero.id == hero_id:
            return hero
    return None


def recognition_to_draft_input(
    data: DotaData,
    recognition: DraftRecognition,
    perspective: str,
) -> RecognizedDraftInput:
    """Convert only accepted team pick slots into a legal coach input.

    Bans are never sent to coach_draft(). Unknown-team picks, unresolved slots,
    missing hero ids and stale ids stay in manual fallback instead of being
    guessed. The perspective is the user's side (radiant or dire).
    """
    perspective = perspective.strip().lower()
    if perspective not in {"radiant", "dire"}:
        raise ValueError("perspective must be radiant or dire")
    opponent = "dire" if perspective == "radiant" else "radiant"

    allies: list[Hero] = []
    enemies: list[Hero] = []
    manual: list[SlotRecognition] = []
    bans: list[SlotRecognition] = []

    for slot in recognition.slots:
        if slot.kind == "ban":
            bans.append(slot)
            continue
        if slot.kind != "pick":
            manual.append(slot)
            continue
        if slot.team not in {perspective, opponent}:
            manual.append(slot)
            continue
        if not slot.accepted or slot.hero_id is None:
            manual.append(slot)
            continue
        hero = _hero_by_id(data, slot.hero_id)
        if hero is None:
            manual.append(slot)
            continue
        if slot.team == perspective:
            allies.append(hero)
        else:
            enemies.append(hero)

    return RecognizedDraftInput(
        allies=tuple(allies),
        enemies=tuple(enemies),
        manual_slots=tuple(manual),
        ignored_bans=tuple(bans),
    )


def coach_recognized_draft(
    data: DotaData,
    recognition: DraftRecognition,
    perspective: str,
    position: str,
    limit: int = 5,
    rank_tier: str | int | None = None,
) -> RecognizedCoachResult:
    """End-to-end saved-frame MVP bridge: accepted picks -> coach_draft()."""
    recognized = recognition_to_draft_input(data, recognition, perspective)
    result = coach_draft(
        data,
        list(recognized.allies),
        list(recognized.enemies),
        position,
        limit=limit,
        rank_tier=rank_tier,
    )

    extra_warnings: list[str] = list(result.warnings)
    if recognized.manual_slots:
        extra_warnings.append(
            f"{len(recognized.manual_slots)} draft pick slot(s) remain manual/unresolved and were not used for scoring"
        )
    if not recognized.allies and not recognized.enemies:
        extra_warnings.append("no accepted pick slots were available; recommendation uses meta/role evidence only")

    if tuple(extra_warnings) != result.warnings:
        result = DraftResult(
            picks=result.picks,
            tactics=result.tactics,
            warnings=tuple(dict.fromkeys(extra_warnings)),
            source_notes=result.source_notes,
        )

    return RecognizedCoachResult(recognized=recognized, coach=result)
