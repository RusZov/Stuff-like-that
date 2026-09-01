from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


class LayoutError(ValueError):
    pass


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class NormalizedRect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(isinstance(value, (int, float)) for value in values):
            raise LayoutError("normalized rectangle values must be numeric")
        if self.width <= 0 or self.height <= 0:
            raise LayoutError("normalized rectangle width/height must be positive")
        if self.x < 0 or self.y < 0 or self.x + self.width > 1 or self.y + self.height > 1:
            raise LayoutError("normalized rectangle must stay inside the frame")

    def to_pixels(self, frame_width: int, frame_height: int) -> PixelRect:
        if frame_width <= 0 or frame_height <= 0:
            raise LayoutError("frame dimensions must be positive")
        x1 = round(self.x * frame_width)
        y1 = round(self.y * frame_height)
        x2 = round((self.x + self.width) * frame_width)
        y2 = round((self.y + self.height) * frame_height)
        x1 = max(0, min(frame_width - 1, x1))
        y1 = max(0, min(frame_height - 1, y1))
        x2 = max(x1 + 1, min(frame_width, x2))
        y2 = max(y1 + 1, min(frame_height, y2))
        return PixelRect(x1, y1, x2 - x1, y2 - y1)

    def to_dict(self) -> dict[str, float]:
        return {
            "x": float(self.x),
            "y": float(self.y),
            "width": float(self.width),
            "height": float(self.height),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "NormalizedRect":
        try:
            return cls(
                x=float(value["x"]),
                y=float(value["y"]),
                width=float(value["width"]),
                height=float(value["height"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LayoutError("invalid normalized rectangle") from exc


@dataclass(frozen=True)
class SlotRegion:
    slot_id: str
    kind: str
    team: str
    rect: NormalizedRect

    def __post_init__(self) -> None:
        if not self.slot_id.strip():
            raise LayoutError("slot_id must not be empty")
        if self.kind not in {"pick", "ban"}:
            raise LayoutError("slot kind must be pick or ban")
        if self.team not in {"radiant", "dire", "unknown"}:
            raise LayoutError("slot team must be radiant, dire or unknown")

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "kind": self.kind,
            "team": self.team,
            "rect": self.rect.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SlotRegion":
        try:
            return cls(
                slot_id=str(value["slot_id"]),
                kind=str(value["kind"]),
                team=str(value.get("team", "unknown")),
                rect=NormalizedRect.from_dict(value["rect"]),
            )
        except (KeyError, TypeError) as exc:
            raise LayoutError("invalid slot region") from exc


@dataclass(frozen=True)
class DraftLayout:
    name: str
    aspect_min: float
    aspect_max: float
    slots: tuple[SlotRegion, ...]
    anchors: tuple[NormalizedRect, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise LayoutError("layout name must not be empty")
        if self.aspect_min <= 0 or self.aspect_max <= 0 or self.aspect_min > self.aspect_max:
            raise LayoutError("invalid aspect-ratio range")
        ids = [slot.slot_id for slot in self.slots]
        if len(ids) != len(set(ids)):
            raise LayoutError("slot_id values must be unique")

    @property
    def pick_slots(self) -> tuple[SlotRegion, ...]:
        return tuple(slot for slot in self.slots if slot.kind == "pick")

    @property
    def ban_slots(self) -> tuple[SlotRegion, ...]:
        return tuple(slot for slot in self.slots if slot.kind == "ban")

    def supports_frame(self, width: int, height: int, tolerance: float = 0.01) -> bool:
        if width <= 0 or height <= 0:
            return False
        aspect = width / height
        return self.aspect_min - tolerance <= aspect <= self.aspect_max + tolerance

    def pixel_slots(self, width: int, height: int) -> dict[str, PixelRect]:
        if not self.supports_frame(width, height):
            raise LayoutError(
                f"frame aspect {width / height:.4f} is outside layout range "
                f"{self.aspect_min:.4f}-{self.aspect_max:.4f}"
            )
        return {slot.slot_id: slot.rect.to_pixels(width, height) for slot in self.slots}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aspect_min": self.aspect_min,
            "aspect_max": self.aspect_max,
            "slots": [slot.to_dict() for slot in self.slots],
            "anchors": [anchor.to_dict() for anchor in self.anchors],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DraftLayout":
        try:
            slots_raw = value.get("slots", [])
            anchors_raw = value.get("anchors", [])
            if not isinstance(slots_raw, list) or not isinstance(anchors_raw, list):
                raise LayoutError("slots and anchors must be lists")
            return cls(
                name=str(value["name"]),
                aspect_min=float(value["aspect_min"]),
                aspect_max=float(value["aspect_max"]),
                slots=tuple(SlotRegion.from_dict(item) for item in slots_raw),
                anchors=tuple(NormalizedRect.from_dict(item) for item in anchors_raw),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, LayoutError):
                raise
            raise LayoutError("invalid draft layout") from exc

    @classmethod
    def from_json(cls, payload: str) -> "DraftLayout":
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise LayoutError("invalid layout JSON") from exc
        if not isinstance(value, dict):
            raise LayoutError("layout JSON must contain an object")
        return cls.from_dict(value)


def load_layout(path: str | Path) -> DraftLayout:
    return DraftLayout.from_json(Path(path).read_text(encoding="utf-8"))


def save_layout(layout: DraftLayout, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(layout.to_json() + "\n", encoding="utf-8")
    return output
