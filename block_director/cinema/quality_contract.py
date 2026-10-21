"""Backward-compatible cinema import path for the canonical contract."""

from ..contracts.quality import (
    COMPOSITION_PASS_SCORE,
    COMPOSITION_PASS_TEXT,
    COMPOSITION_STATUSES,
    QUALITY_CONTRACT_VERSION,
    blockout_quality_report,
    composition_decision,
    serialize_quality_decision,
    validate_quality_decision,
)

__all__ = [
    "COMPOSITION_PASS_SCORE",
    "COMPOSITION_PASS_TEXT",
    "COMPOSITION_STATUSES",
    "QUALITY_CONTRACT_VERSION",
    "blockout_quality_report",
    "composition_decision",
    "serialize_quality_decision",
    "validate_quality_decision",
]
