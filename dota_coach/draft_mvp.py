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


def _recognition_strength(slot: SlotRecognition) -> tuple[float, float, float, str]:
    """Stable ordering for mutually exclusive/overfull recognition decisions."""
    return (slot.confidence, slot.similarity, slot.margin, slot.slot_id)


def recognition_to_draft_input(
    data: DotaData,
    recognition: DraftRecognition,
    perspective: str,
) -> RecognizedDraftInput:
    """Convert accepted pick slots into a legal coach input.

    Recognition is intentionally fail-safe here. Ambiguous duplicate heroes and
    impossible overfull teams are reduced to the strongest legal set; weaker
    slots stay visible as manual fallback instead of crashing coach_draft().
    """
    perspective = perspective.strip().lower()
    if perspective not in {"radiant", "dire"}:
        raise ValueError("perspective must be radiant or dire")
    opponent = "dire" if perspective == "radiant" else "radiant"

    accepted: list[tuple[SlotRecognition, Hero]] = []
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
        accepted.append((slot, hero))

    # De-duplicate by hero id, preserving the strongest accepted slot. This is
    # required across both teams because a hero cannot legally appear twice in
    # one Dota draft. Ties are deterministic by slot id.
    best_by_hero: dict[int, tuple[SlotRecognition, Hero]] = {}
    for slot, hero in accepted:
        previous = best_by_hero.get(hero.id)
        if previous is None or _recognition_strength(slot) > _recognition_strength(previous[0]):
            if previous is not None:
                manual.append(previous[0])
            best_by_hero[hero.id] = (slot, hero)
        else:
            manual.append(slot)

    # A legal Dota team has at most five picks. A stale/incorrect layout can
    # expose extra accepted ROIs, so cap each side to its five strongest slots
    # before handing the draft to the strict recommendation engine.
    kept: list[tuple[SlotRecognition, Hero]] = []
    for team in (perspective, opponent):
        team_entries = [entry for entry in best_by_hero.values() if entry[0].team == team]
        team_entries.sort(key=lambda entry: _recognition_strength(entry[0]), reverse=True)
        kept.extend(team_entries[:5])
        manual.extend(slot for slot, _hero in team_entries[5:])

    allies: list[Hero] = []
    enemies: list[Hero] = []
    for slot, hero in sorted(kept, key=lambda item: item[0].slot_id):
        if slot.team == perspective:
            allies.append(hero)
        else:
            enemies.append(hero)

    manual.sort(key=lambda slot: slot.slot_id)
    bans.sort(key=lambda slot: slot.slot_id)
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
