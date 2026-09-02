"""Dota Coach MVP package."""

from .data import DotaData, Hero
from .draft_layout import DraftLayout, NormalizedRect, SlotRegion
from .draft_recognition import DraftRecognition, SlotRecognition, recognize_draft_slots
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
    "recommend",
    "build_strategy",
    "coach_draft",
    "recognize_draft_slots",
]
