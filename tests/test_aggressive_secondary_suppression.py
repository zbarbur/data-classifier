"""Tests for aggressive secondary-match suppression (Sprint 6).

When ``classify_columns(aggressive_secondary_suppression=True)`` is set
and the top finding for a column has confidence > 0.80, the effective
confidence-gap threshold tightens from the default 0.30 to 0.15 — dropping
more low-confidence secondaries in the "primary-dominant" regime.

Default behavior (aggressive=False) is preserved exactly — tested here as
a regression guard against accidental behavior change.
"""

from __future__ import annotations

from data_classifier import _apply_findings_limit
from data_classifier.core.types import ClassificationFinding


def _make_finding(entity_type: str, confidence: float) -> ClassificationFinding:
    return ClassificationFinding(
        column_id="c1",
        entity_type=entity_type,
        category="PII",
        sensitivity="HIGH",
        confidence=confidence,
        regulatory=[],
        engine="test",
        evidence=f"test finding {entity_type}",
    )


class TestDefaultBehaviorUnchanged:
    """Regression guard: aggressive=False preserves Sprint 5 gap semantics."""

    def test_default_keeps_within_030_gap(self) -> None:
        findings = [
            _make_finding("A", 0.95),
            _make_finding("B", 0.70),  # gap 0.25 — kept
            _make_finding("C", 0.50),  # gap 0.45 — dropped
        ]
        result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=False)
        kept_types = {f.entity_type for f in result}
        assert kept_types == {"A", "B"}

    def test_default_drops_below_030_gap(self) -> None:
        findings = [
            _make_finding("A", 0.90),
            _make_finding("B", 0.55),  # gap 0.35 — dropped
        ]
        result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=False)
        assert len(result) == 1
        assert result[0].entity_type == "A"

    def test_default_with_primary_below_080(self) -> None:
        """When primary <= 0.80, aggressive mode is inactive — same as default."""
        findings = [
            _make_finding("A", 0.75),  # primary not high enough to trigger aggressive
            _make_finding("B", 0.50),  # gap 0.25 — kept even with aggressive=True
        ]
        result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=True)
        assert len(result) == 2


class TestAggressiveModeTightensGap:
    """When primary > 0.80 and aggressive=True, gap tightens from 0.30 to 0.15."""

    def test_aggressive_drops_secondary_within_030_but_beyond_015(self) -> None:
        findings = [
            _make_finding("A", 0.95),  # primary dominant
            _make_finding("B", 0.75),  # gap 0.20 — kept by default, dropped by aggressive
        ]
        result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=True)
        kept_types = {f.entity_type for f in result}
        assert kept_types == {"A"}

    def test_aggressive_keeps_very_close_secondary(self) -> None:
        findings = [
            _make_finding("A", 0.95),
            _make_finding("B", 0.85),  # gap 0.10 — within aggressive threshold
        ]
        result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=True)
        kept_types = {f.entity_type for f in result}
        assert kept_types == {"A", "B"}

    def test_aggressive_primary_threshold_boundary(self) -> None:
        """At primary=0.80 exactly, aggressive mode is NOT triggered — the
        threshold comparison is strict greater-than."""
        findings = [
            _make_finding("A", 0.80),  # boundary — NOT > 0.80
            _make_finding("B", 0.55),  # gap 0.25 — kept under default 0.30
        ]
        result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=True)
        assert len(result) == 2

    def test_aggressive_does_not_loosen_user_threshold(self) -> None:
        """If user sets a tighter-than-aggressive gap (e.g. 0.05), aggressive
        mode must not LOOSEN it to 0.15. Must take the min of the two."""
        findings = [
            _make_finding("A", 0.95),
            _make_finding("B", 0.87),  # gap 0.08 — dropped under user threshold 0.05
        ]
        result = _apply_findings_limit(findings, None, 0.05, aggressive_secondary_suppression=True)
        assert len(result) == 1
        assert result[0].entity_type == "A"


class TestAggressiveModeFpReduction:
    """Document the Sprint 5 FP patterns this mode would kill.

    These exercise the "many entity types from different engines, one
    dominant with high confidence, several near-threshold noise" scenario
    that showed up in Nemotron blind-mode failures.
    """

    def test_dominant_email_crowds_out_regex_noise(self) -> None:
        findings = [
            _make_finding("EMAIL", 0.92),  # dominant primary
            _make_finding("PHONE", 0.65),  # ambiguous secondary
            _make_finding("DATE_OF_BIRTH", 0.60),  # ambiguous secondary
        ]
        default_result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=False)
        aggressive_result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=True)
        # Default: keeps EMAIL + PHONE (0.92-0.65=0.27 within 0.30 gap), drops DOB
        assert {f.entity_type for f in default_result} == {"EMAIL", "PHONE"}
        # Aggressive: primary 0.92 > 0.80, tightens gap to 0.15 → only EMAIL survives
        assert {f.entity_type for f in aggressive_result} == {"EMAIL"}

    def test_mid_confidence_primary_not_affected(self) -> None:
        """Primary below the 0.80 bar means aggressive mode should be a no-op —
        we don't want to crowd out secondaries when we aren't sure about the
        primary either."""
        findings = [
            _make_finding("EMAIL", 0.78),  # below aggressive trigger
            _make_finding("PHONE", 0.55),  # gap 0.23 — within default
        ]
        default_result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=False)
        aggressive_result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=True)
        assert [f.entity_type for f in default_result] == [f.entity_type for f in aggressive_result]


class TestEmptyAndSingleton:
    """Edge cases: empty findings list and single-finding list."""

    def test_empty_findings_returns_empty(self) -> None:
        result = _apply_findings_limit([], None, 0.30, aggressive_secondary_suppression=True)
        assert result == []

    def test_single_finding_always_kept(self) -> None:
        findings = [_make_finding("A", 0.50)]  # below aggressive trigger
        result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=True)
        assert result == findings

    def test_single_high_confidence_finding(self) -> None:
        findings = [_make_finding("A", 0.95)]  # above aggressive trigger
        result = _apply_findings_limit(findings, None, 0.30, aggressive_secondary_suppression=True)
        assert result == findings
