"""Tests for confidence calibration module.

Tests cover:
  - Per-engine calibration functions are monotonic
  - Calibration registry has entries for all known engines
  - ML engine integration point defined (identity function)
  - Calibrated findings have correct confidence values
  - Unknown engines pass through unchanged
  - Column name engine confidence competitive with regex for strong matches
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import ClassificationFinding, SampleAnalysis
from data_classifier.orchestrator.calibration import (
    CALIBRATION_FUNCTIONS,
    calibrate_column_name,
    calibrate_finding,
    calibrate_heuristic,
    calibrate_ml,
    calibrate_regex,
    calibrate_secret_scanner,
)


def _make_finding(
    engine: str,
    confidence: float,
    entity_type: str = "SSN",
    sample_analysis: SampleAnalysis | None = None,
) -> ClassificationFinding:
    """Helper to create a ClassificationFinding for testing."""
    return ClassificationFinding(
        column_id="test:col",
        entity_type=entity_type,
        category="PII",
        sensitivity="CRITICAL",
        confidence=confidence,
        regulatory=[],
        engine=engine,
        evidence="test",
        sample_analysis=sample_analysis,
    )


class TestMonotonicity:
    """All calibration functions must be monotonic: higher raw → higher calibrated."""

    @pytest.mark.parametrize("engine", ["regex", "column_name", "heuristic_stats", "secret_scanner", "gliner2"])
    def test_monotonic(self, engine: str) -> None:
        """Calibration is monotonic for engine."""
        fn = CALIBRATION_FUNCTIONS[engine]
        prev_calibrated = -1.0
        for raw_conf in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0]:
            finding = _make_finding(engine, raw_conf)
            calibrated = fn(finding)
            assert calibrated >= prev_calibrated, (
                f"Monotonicity violated for {engine}: "
                f"calibrate({raw_conf})={calibrated} < calibrate(prev)={prev_calibrated}"
            )
            prev_calibrated = calibrated


class TestRegexCalibration:
    """Regex engine calibration specifics."""

    def test_sample_only_low_matches_dampened(self) -> None:
        """Sample-only findings with few matches get dampened."""
        sa = SampleAnalysis(samples_scanned=100, samples_matched=1, samples_validated=1, match_ratio=0.01)
        finding = _make_finding("regex", 0.80, sample_analysis=sa)
        calibrated = calibrate_regex(finding)
        assert calibrated < 0.80

    def test_sample_only_many_matches_less_dampened(self) -> None:
        """Sample-only findings with many matches get less dampening."""
        sa = SampleAnalysis(samples_scanned=100, samples_matched=10, samples_validated=10, match_ratio=0.10)
        finding = _make_finding("regex", 0.80, sample_analysis=sa)
        calibrated = calibrate_regex(finding)
        assert calibrated == 0.80  # No dampening for 10+ matches

    def test_column_name_match_not_dampened(self) -> None:
        """Column name match (no sample_analysis) is not dampened."""
        finding = _make_finding("regex", 0.90)
        calibrated = calibrate_regex(finding)
        assert calibrated == 0.90


class TestColumnNameCalibration:
    """Column name engine calibration specifics."""

    def test_strong_match_boosted(self) -> None:
        """Strong column name matches (>=0.85) get boosted."""
        finding = _make_finding("column_name", 0.90)
        calibrated = calibrate_column_name(finding)
        assert calibrated == pytest.approx(0.95, abs=1e-9)

    def test_medium_match_boosted(self) -> None:
        """Medium column name matches (0.70-0.85) get smaller boost."""
        finding = _make_finding("column_name", 0.75)
        calibrated = calibrate_column_name(finding)
        assert calibrated == 0.78

    def test_weak_match_no_boost(self) -> None:
        """Weak column name matches (<0.70) are not boosted."""
        finding = _make_finding("column_name", 0.50)
        calibrated = calibrate_column_name(finding)
        assert calibrated == 0.50

    def test_capped_at_1(self) -> None:
        """Calibrated confidence never exceeds 1.0."""
        finding = _make_finding("column_name", 0.98)
        calibrated = calibrate_column_name(finding)
        assert calibrated <= 1.0

    def test_competitive_with_regex(self) -> None:
        """Strong column name match is competitive with regex column-name match."""
        cn_finding = _make_finding("column_name", 0.90)
        regex_finding = _make_finding("regex", 0.90)

        cn_calibrated = calibrate_column_name(cn_finding)
        regex_calibrated = calibrate_regex(regex_finding)

        # Column name engine with strong match should be >= regex
        assert cn_calibrated >= regex_calibrated


class TestHeuristicCalibration:
    """Heuristic engine calibration specifics."""

    def test_dampened(self) -> None:
        """Heuristic findings get slight dampening."""
        finding = _make_finding("heuristic_stats", 0.80)
        calibrated = calibrate_heuristic(finding)
        assert calibrated == pytest.approx(0.76, abs=0.01)


class TestSecretScannerCalibration:
    """Secret scanner engine calibration specifics."""

    def test_passthrough(self) -> None:
        """Secret scanner calibration is identity."""
        finding = _make_finding("secret_scanner", 0.85)
        calibrated = calibrate_secret_scanner(finding)
        assert calibrated == 0.85


class TestMLCalibration:
    """ML engine calibration — integration point."""

    def test_identity(self) -> None:
        """ML calibration is identity function (placeholder)."""
        finding = _make_finding("gliner2", 0.75)
        calibrated = calibrate_ml(finding)
        assert calibrated == 0.75


class TestCalibrateRegistry:
    """Calibration function registry."""

    def test_all_engines_registered(self) -> None:
        """All known engines have calibration functions."""
        expected = {"regex", "column_name", "heuristic_stats", "secret_scanner", "gliner2"}
        assert set(CALIBRATION_FUNCTIONS.keys()) == expected

    def test_ml_slot_exists(self) -> None:
        """ML engine integration point is defined."""
        assert "gliner2" in CALIBRATION_FUNCTIONS


class TestCalibrateFinding:
    """End-to-end calibrate_finding function."""

    def test_returns_new_finding(self) -> None:
        """calibrate_finding returns a new finding, not mutating the original."""
        original = _make_finding("column_name", 0.90)
        calibrated = calibrate_finding(original)
        # Original is unchanged
        assert original.confidence == 0.90
        # Calibrated is different (boosted)
        assert calibrated.confidence == pytest.approx(0.95, abs=1e-9)

    def test_unknown_engine_passthrough(self) -> None:
        """Unknown engine returns the same finding."""
        finding = _make_finding("unknown_engine", 0.80)
        result = calibrate_finding(finding)
        assert result is finding
        assert result.confidence == 0.80

    def test_preserves_metadata(self) -> None:
        """Calibrated finding preserves all metadata except confidence."""
        sa = SampleAnalysis(samples_scanned=10, samples_matched=1, samples_validated=1, match_ratio=0.1)
        original = _make_finding("regex", 0.80, entity_type="EMAIL", sample_analysis=sa)
        calibrated = calibrate_finding(original)
        assert calibrated.column_id == original.column_id
        assert calibrated.entity_type == original.entity_type
        assert calibrated.category == original.category
        assert calibrated.engine == original.engine
        assert calibrated.sample_analysis is original.sample_analysis

    def test_confidence_bounded(self) -> None:
        """Calibrated confidence stays in [0.0, 1.0]."""
        finding = _make_finding("column_name", 0.99)
        calibrated = calibrate_finding(finding)
        assert 0.0 <= calibrated.confidence <= 1.0
