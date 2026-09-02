from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .draft_layout import DraftLayout, PixelRect
from .portrait import PortraitIndex, PortraitIndexError, _as_rgb_image


@dataclass(frozen=True)
class SlotRecognition:
    slot_id: str
    kind: str
    team: str
    rect: PixelRect
    hero_id: int | None
    hero_name: str | None
    similarity: float
    margin: float
    confidence: float
    accepted: bool
    reason: str


@dataclass(frozen=True)
class DraftRecognition:
    layout_name: str
    slots: tuple[SlotRecognition, ...]

    @property
    def accepted_slots(self) -> tuple[SlotRecognition, ...]:
        return tuple(slot for slot in self.slots if slot.accepted)

    @property
    def unresolved_slots(self) -> tuple[SlotRecognition, ...]:
        return tuple(slot for slot in self.slots if not slot.accepted)


def _reject_duplicate_heroes(slots: list[SlotRecognition]) -> list[SlotRecognition]:
    """Fail closed if multiple slots claim the same hero.

    A legal Dota draft cannot contain the same hero twice across picks/bans.
    Keep the strongest recognition and force the weaker duplicate to manual
    review instead of silently feeding an impossible state to the coach.
    """
    by_hero: dict[int, list[int]] = {}
    for index, slot in enumerate(slots):
        if slot.accepted and slot.hero_id is not None:
            by_hero.setdefault(slot.hero_id, []).append(index)

    for hero_id, indices in by_hero.items():
        if len(indices) <= 1:
            continue
        best = max(
            indices,
            key=lambda idx: (
                slots[idx].confidence,
                slots[idx].margin,
                slots[idx].similarity,
            ),
        )
        for index in indices:
            if index == best:
                continue
            slots[index] = replace(
                slots[index],
                accepted=False,
                reason=f"duplicate hero_id={hero_id}; stronger slot kept",
            )
    return slots


def recognize_draft_slots(
    frame: Any,
    layout: DraftLayout,
    index: PortraitIndex,
    *,
    include_bans: bool = True,
    min_similarity: float = 0.78,
    min_margin: float = 0.018,
    min_confidence: float = 0.58,
) -> DraftRecognition:
    """Recognize heroes only inside calibrated draft slot rectangles.

    This function never searches the full frame. A measured DraftLayout provides
    the exact slot ROIs; each crop is classified independently and low-confidence
    results stay unresolved for manual fallback.
    """
    image = _as_rgb_image(frame)
    width, height = image.size
    pixel_slots = layout.pixel_slots(width, height)
    slot_defs = layout.slots if include_bans else layout.pick_slots
    output: list[SlotRecognition] = []

    for slot in slot_defs:
        rect = pixel_slots[slot.slot_id]
        crop = image.crop((rect.x, rect.y, rect.x + rect.width, rect.y + rect.height))
        try:
            match = index.classify(
                crop,
                min_similarity=min_similarity,
                min_margin=min_margin,
                min_confidence=min_confidence,
            )
        except PortraitIndexError as exc:
            output.append(
                SlotRecognition(
                    slot_id=slot.slot_id,
                    kind=slot.kind,
                    team=slot.team,
                    rect=rect,
                    hero_id=None,
                    hero_name=None,
                    similarity=0.0,
                    margin=0.0,
                    confidence=0.0,
                    accepted=False,
                    reason=str(exc),
                )
            )
            continue

        reason = "accepted" if match.accepted else "below portrait confidence/margin threshold"
        output.append(
            SlotRecognition(
                slot_id=slot.slot_id,
                kind=slot.kind,
                team=slot.team,
                rect=rect,
                hero_id=match.hero_id,
                hero_name=match.hero_name,
                similarity=match.similarity,
                margin=match.margin,
                confidence=match.confidence,
                accepted=match.accepted,
                reason=reason,
            )
        )

    return DraftRecognition(layout_name=layout.name, slots=tuple(_reject_duplicate_heroes(output)))
