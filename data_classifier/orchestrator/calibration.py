"""Confidence calibration — normalize engine scores to a common scale.

Each engine produces confidence scores on different scales.  The regex engine
produces high-confidence scores (0.7-0.95) even for ambiguous patterns, while
the column name engine caps at 0.85 for subsequence matches.  This module
provides monotonic calibration functions that remap raw engine confidence to
a unified scale, ensuring cross-engine comparability.

Calibration is applied in the orchestrator BEFORE merging findings from
different engines, so that "highest confidence wins" deduplication operates
on comparable scores.

Design:
  - Each engine has a named calibration function
  - All functions are monotonic: if raw_a > raw_b then calibrated_a >= calibrated_b
  - ML engine slot is pre-defined (identity function) for future integration
  - Calibration parameters are constants — future work can learn them from data
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from data_classifier.core.types import ClassificationFinding

logger = logging.getLogger(__name__)


def calibrate_regex(finding: ClassificationFinding) -> float:
    """Calibrate regex engine confidence.

    The regex engine tends to produce high confidence even with few matches.
    Apply a slight dampening for sample-only findings (no column name signal)
    to let column-name matches compete fairly.

    Monotonic: preserves ordering of raw confidence values.
    """
    raw = finding.confidence
    # Sample-only findings (from content patterns) get slight dampening
    # to let column-name engine compete when both produce the same entity type
    if finding.sample_analysis is not None:
        # Dampening is stronger for low match counts
        match_count = finding.sample_analysis.samples_matched
        if match_count <= 2:
            return raw * 0.90
        elif match_count <= 5:
            return raw * 0.95
    return raw


def calibrate_column_name(finding: ClassificationFinding) -> float:
    """Calibrate column name engine confidence.

    The column name engine produces conservative scores (0.60-0.95).
    Boost strong matches (direct lookup with high raw confidence) to be
    competitive with regex engine column-name pattern matching.

    Monotonic: preserves ordering of raw confidence values.
    """
    raw = finding.confidence
    # Strong column name matches (direct lookup) deserve a small boost
    # to compete with regex engine's profile-based column name matching
    if raw >= 0.85:
        return min(1.0, raw + 0.05)
    elif raw >= 0.70:
        return min(1.0, raw + 0.03)
    return raw


def calibrate_heuristic(finding: ClassificationFinding) -> float:
    """Calibrate heuristic engine confidence.

    Heuristic findings are statistical signals — apply a small penalty
    so they don't override more specific pattern-based matches.

    Monotonic: preserves ordering of raw confidence values.
    """
    raw = finding.confidence
    return raw * 0.95


def calibrate_secret_scanner(finding: ClassificationFinding) -> float:
    """Calibrate secret scanner engine confidence.

    Secret scanner uses entropy + key-name matching.  Scores are already
    well-calibrated.  Pass through with minimal adjustment.

    Monotonic: identity function.
    """
    return finding.confidence


def calibrate_ml(finding: ClassificationFinding) -> float:
    """Calibrate ML engine confidence.

    Integration point for future ML-based classification engine.
    Identity function until ML engine is implemented and calibration
    parameters are learned from evaluation data.

    Monotonic: identity function.
    """
    return finding.confidence


# ── Registry ─────────────────────────────────────────────────────────────────

# Maps engine name → calibration function.
# New engines register here.  Unknown engines use identity (no-op).
CALIBRATION_FUNCTIONS: dict[str, Callable[[ClassificationFinding], float]] = {
    "regex": calibrate_regex,
    "column_name": calibrate_column_name,
    "heuristic_stats": calibrate_heuristic,
    "secret_scanner": calibrate_secret_scanner,
    "gliner2": calibrate_ml,
}


def calibrate_finding(finding: ClassificationFinding) -> ClassificationFinding:
    """Apply engine-specific calibration to a finding's confidence.

    Returns a NEW finding with calibrated confidence.  The original finding
    is not modified.

    If the engine has no registered calibration function, the finding is
    returned unchanged.
    """
    calibrate_fn = CALIBRATION_FUNCTIONS.get(finding.engine)
    if calibrate_fn is None:
        return finding

    calibrated_confidence = calibrate_fn(finding)
    calibrated_confidence = max(0.0, min(1.0, calibrated_confidence))

    if calibrated_confidence == finding.confidence:
        return finding

    logger.debug(
        "Calibrated %s finding for %s: %.3f → %.3f (engine=%s)",
        finding.entity_type,
        finding.column_id,
        finding.confidence,
        calibrated_confidence,
        finding.engine,
    )

    # Return new finding with calibrated confidence
    return ClassificationFinding(
        column_id=finding.column_id,
        entity_type=finding.entity_type,
        category=finding.category,
        sensitivity=finding.sensitivity,
        confidence=calibrated_confidence,
        regulatory=finding.regulatory,
        engine=finding.engine,
        evidence=finding.evidence,
        sample_analysis=finding.sample_analysis,
    )
