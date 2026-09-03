from __future__ import annotations

from dataclasses import dataclass
import json
from math import ceil
from pathlib import Path
from typing import Any

from .draft_layout import DraftLayout, LayoutError, PixelRect
from .portrait import PortraitIndexError, _as_rgb_image, portrait_embedding


class DraftValidationError(RuntimeError):
    """Raised when a draft anchor profile cannot be calibrated or applied safely."""


@dataclass(frozen=True)
class AnchorReference:
    index: int
    rect: PixelRect
    feature: tuple[float, ...]


@dataclass(frozen=True)
class AnchorEvidence:
    index: int
    rect: PixelRect
    similarity: float
    passed: bool
    reason: str


@dataclass(frozen=True)
class DraftAnchorProfile:
    layout_name: str
    reference_width: int
    reference_height: int
    features: tuple[tuple[float, ...], ...]
    min_similarity: float = 0.78
    min_pass_fraction: float = 0.75

    def __post_init__(self) -> None:
        if not self.layout_name.strip():
            raise DraftValidationError("anchor profile layout_name must not be empty")
        if self.reference_width <= 0 or self.reference_height <= 0:
            raise DraftValidationError("anchor profile reference dimensions must be positive")
        if len(self.features) < 2:
            raise DraftValidationError("at least two calibrated anchors are required")
        if not 0.0 <= self.min_similarity <= 1.0:
            raise DraftValidationError("min_similarity must be between 0 and 1")
        if not 0.0 < self.min_pass_fraction <= 1.0:
            raise DraftValidationError("min_pass_fraction must be in (0, 1]")
        lengths = {len(feature) for feature in self.features}
        if len(lengths) != 1 or not lengths or next(iter(lengths)) == 0:
            raise DraftValidationError("anchor feature vectors must have one non-zero common length")

    def to_dict(self) -> dict[str, Any]:
        return {
            "layout_name": self.layout_name,
            "reference_width": self.reference_width,
            "reference_height": self.reference_height,
            "features": [[round(float(value), 7) for value in feature] for feature in self.features],
            "min_similarity": self.min_similarity,
            "min_pass_fraction": self.min_pass_fraction,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DraftAnchorProfile":
        try:
            raw_features = value["features"]
            if not isinstance(raw_features, list):
                raise DraftValidationError("anchor profile features must be a list")
            features = tuple(tuple(float(item) for item in feature) for feature in raw_features)
            return cls(
                layout_name=str(value["layout_name"]),
                reference_width=int(value["reference_width"]),
                reference_height=int(value["reference_height"]),
                features=features,
                min_similarity=float(value.get("min_similarity", 0.78)),
                min_pass_fraction=float(value.get("min_pass_fraction", 0.75)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, DraftValidationError):
                raise
            raise DraftValidationError("invalid draft anchor profile") from exc

    @classmethod
    def from_json(cls, payload: str) -> "DraftAnchorProfile":
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DraftValidationError("invalid anchor profile JSON") from exc
        if not isinstance(value, dict):
            raise DraftValidationError("anchor profile JSON must contain an object")
        return cls.from_dict(value)


@dataclass(frozen=True)
class DraftFrameValidation:
    layout_name: str
    accepted: bool
    passed_anchors: int
    required_anchors: int
    evidence: tuple[AnchorEvidence, ...]
    reason: str


def _anchor_crop(image: Any, layout: DraftLayout, anchor_index: int) -> tuple[Any, PixelRect]:
    width, height = image.size
    rect = layout.anchors[anchor_index].to_pixels(width, height)
    crop = image.crop((rect.x, rect.y, rect.x + rect.width, rect.y + rect.height))
    return crop, rect


def calibrate_anchor_profile(
    frame: Any,
    layout: DraftLayout,
    *,
    min_similarity: float = 0.78,
    min_pass_fraction: float = 0.75,
) -> DraftAnchorProfile:
    """Build a fixed-ROI draft HUD signature from one measured reference frame.

    No sliding search is performed. The caller first measures stable UI anchor
    rectangles into DraftLayout; calibration stores one normalized visual
    descriptor for each of those exact rectangles.
    """
    image = _as_rgb_image(frame)
    width, height = image.size
    if not layout.supports_frame(width, height):
        raise LayoutError("reference frame aspect does not match the selected DraftLayout")
    if len(layout.anchors) < 2:
        raise DraftValidationError("DraftLayout must contain at least two measured anchors")

    features: list[tuple[float, ...]] = []
    for index in range(len(layout.anchors)):
        crop, _rect = _anchor_crop(image, layout, index)
        try:
            feature = portrait_embedding(crop)
        except PortraitIndexError as exc:
            raise DraftValidationError(f"anchor {index} has no stable visual structure: {exc}") from exc
        features.append(tuple(float(value) for value in feature.tolist()))

    return DraftAnchorProfile(
        layout_name=layout.name,
        reference_width=width,
        reference_height=height,
        features=tuple(features),
        min_similarity=min_similarity,
        min_pass_fraction=min_pass_fraction,
    )


def validate_draft_frame(
    frame: Any,
    layout: DraftLayout,
    profile: DraftAnchorProfile,
) -> DraftFrameValidation:
    """Fail closed unless enough calibrated HUD anchors match at fixed ROIs."""
    if profile.layout_name != layout.name:
        raise DraftValidationError(
            f"anchor profile is for {profile.layout_name!r}, not layout {layout.name!r}"
        )
    if len(profile.features) != len(layout.anchors):
        raise DraftValidationError("anchor profile count does not match DraftLayout anchors")

    image = _as_rgb_image(frame)
    width, height = image.size
    required = max(2, ceil(len(profile.features) * profile.min_pass_fraction))
    if not layout.supports_frame(width, height):
        return DraftFrameValidation(
            layout_name=layout.name,
            accepted=False,
            passed_anchors=0,
            required_anchors=required,
            evidence=(),
            reason="frame aspect does not match calibrated draft layout",
        )

    import numpy as np

    evidence: list[AnchorEvidence] = []
    for index, reference in enumerate(profile.features):
        crop, rect = _anchor_crop(image, layout, index)
        try:
            feature = portrait_embedding(crop)
            ref = np.asarray(reference, dtype=np.float32)
            if feature.shape != ref.shape:
                raise DraftValidationError(f"anchor {index} descriptor size mismatch")
            similarity = float(np.dot(feature, ref))
            similarity = max(-1.0, min(1.0, similarity))
            passed = similarity >= profile.min_similarity
            reason = "matched" if passed else "below calibrated anchor similarity"
        except PortraitIndexError as exc:
            similarity = -1.0
            passed = False
            reason = str(exc)
        evidence.append(
            AnchorEvidence(
                index=index,
                rect=rect,
                similarity=round(similarity, 4),
                passed=passed,
                reason=reason,
            )
        )

    passed_count = sum(item.passed for item in evidence)
    accepted = passed_count >= required
    return DraftFrameValidation(
        layout_name=layout.name,
        accepted=accepted,
        passed_anchors=passed_count,
        required_anchors=required,
        evidence=tuple(evidence),
        reason="accepted" if accepted else f"only {passed_count}/{required} required anchors matched",
    )


def load_anchor_profile(path: str | Path) -> DraftAnchorProfile:
    return DraftAnchorProfile.from_json(Path(path).read_text(encoding="utf-8"))


def save_anchor_profile(profile: DraftAnchorProfile, path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(profile.to_json() + "\n", encoding="utf-8")
    return output
