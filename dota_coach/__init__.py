"""Dota Coach MVP package."""

from .data import DotaData, Hero
from .draft_layout import DraftLayout, NormalizedRect, SlotRegion
from .draft_mvp import (
    RecognizedCoachResult,
    RecognizedDraftInput,
    coach_recognized_draft,
    recognition_to_draft_input,
)
from .draft_recognition import DraftRecognition, SlotRecognition, recognize_draft_slots
from .draft_validation import (
    AnchorEvidence,
    DraftAnchorProfile,
    DraftFrameValidation,
    calibrate_anchor_profile,
    validate_draft_frame,
)
from .engine import Pick, build_strategy, recommend
from .portrait import PortraitIndex, PortraitMatch
from .service import DraftResult, coach_draft

__all__ = [
    "DotaData",
    "Hero",
    "Pick",
    "DraftResult",
    "DraftLayout",
    "NormalizedRect",
    "SlotRegion",
    "PortraitIndex",
    "PortraitMatch",
    "DraftRecognition",
    "SlotRecognition",
    "DraftAnchorProfile",
    "AnchorEvidence",
    "DraftFrameValidation",
    "RecognizedDraftInput",
    "RecognizedCoachResult",
    "recommend",
    "build_strategy",
    "coach_draft",
    "recognize_draft_slots",
    "calibrate_anchor_profile",
    "validate_draft_frame",
    "recognition_to_draft_input",
    "coach_recognized_draft",
]
