"""Tests for primary-label mode (max_findings parameter).

Tests cover:
  - max_findings=1 returns single highest-confidence finding per column
  - max_findings=None (default) returns all findings — backward compatible
  - Confidence gap suppression removes low-gap secondary findings
  - Multiple columns handled independently
"""

from __future__ import annotations

import pytest

from data_classifier import ClassificationFinding, classify_columns, load_profile
from data_classifier.core.types import ColumnInput


@pytest.fixture
def profile():
    return load_profile("standard")


class TestMaxFindingsOne:
    """max_findings=1 returns only the highest-confidence finding per column."""

    def test_single_finding_column_returns_one(self, profile) -> None:
        """Column with one finding returns that finding."""
        columns = [ColumnInput(column_name="ssn", column_id="col1")]
        findings = classify_columns(columns, profile, max_findings=1)
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_multi_finding_column_returns_best(self, profile) -> None:
        """Column with sample values matching multiple types returns only the best."""
        columns = [
            ColumnInput(
                column_name="notes",
                column_id="col1",
                sample_values=[
                    "john@example.com",
                    "jane@test.org",
                    "555-123-4567",
                    "user@corp.net",
                ],
            )
        ]
        all_findings = classify_columns(columns, profile, max_findings=None, confidence_gap_threshold=1.0)
        limited_findings = classify_columns(columns, profile, max_findings=1)

        # With max_findings=1, we should get exactly one finding (or zero if nothing matches)
        assert len(limited_findings) <= 1
        if all_findings and limited_findings:
            # The limited finding should be the highest confidence one
            best_all = max(all_findings, key=lambda f: f.confidence)
            assert limited_findings[0].entity_type == best_all.entity_type

    def test_no_findings_returns_empty(self, profile) -> None:
        """Column with no matches returns empty list."""
        columns = [ColumnInput(column_name="record_id", column_id="col1")]
        findings = classify_columns(columns, profile, max_findings=1)
        assert len(findings) == 0

    def test_multiple_columns_each_get_one(self, profile) -> None:
        """Each column independently gets at most one finding."""
        columns = [
            ColumnInput(column_name="ssn", column_id="col1"),
            ColumnInput(column_name="email", column_id="col2"),
        ]
        findings = classify_columns(columns, profile, max_findings=1)
        # Each column should contribute at most 1 finding
        col1_findings = [f for f in findings if f.column_id == "col1"]
        col2_findings = [f for f in findings if f.column_id == "col2"]
        assert len(col1_findings) <= 1
        assert len(col2_findings) <= 1


class TestDefaultBehavior:
    """Default (max_findings=None) returns all findings — backward compatible."""

    def test_default_returns_all(self, profile) -> None:
        """Without max_findings, all findings are returned (subject to gap suppression)."""
        columns = [ColumnInput(column_name="ssn", column_id="col1")]
        findings = classify_columns(columns, profile)
        assert len(findings) >= 1

    def test_explicit_none_same_as_default(self, profile) -> None:
        """max_findings=None behaves the same as omitting it."""
        columns = [ColumnInput(column_name="email", column_id="col1")]
        default_findings = classify_columns(columns, profile)
        explicit_findings = classify_columns(columns, profile, max_findings=None)
        assert len(default_findings) == len(explicit_findings)


class TestConfidenceGapSuppression:
    """Secondary findings with large confidence gap are suppressed."""

    def test_gap_suppression_removes_weak_secondaries(self, profile) -> None:
        """Findings far below the top finding are suppressed by default."""
        from data_classifier import _apply_findings_limit

        findings = [
            ClassificationFinding(
                column_id="col1",
                entity_type="SSN",
                category="PII",
                sensitivity="CRITICAL",
                confidence=0.95,
                regulatory=[],
                engine="regex",
            ),
            ClassificationFinding(
                column_id="col1",
                entity_type="PHONE",
                category="PII",
                sensitivity="HIGH",
                confidence=0.55,
                regulatory=[],
                engine="regex",
            ),
        ]
        # gap = 0.95 - 0.55 = 0.40 > default threshold 0.30
        result = _apply_findings_limit(findings, max_findings=None, confidence_gap_threshold=0.30)
        assert len(result) == 1
        assert result[0].entity_type == "SSN"

    def test_gap_suppression_keeps_close_findings(self, profile) -> None:
        """Findings within the gap threshold are kept."""
        from data_classifier import _apply_findings_limit

        findings = [
            ClassificationFinding(
                column_id="col1",
                entity_type="SSN",
                category="PII",
                sensitivity="CRITICAL",
                confidence=0.95,
                regulatory=[],
                engine="regex",
            ),
            ClassificationFinding(
                column_id="col1",
                entity_type="CANADIAN_SIN",
                category="PII",
                sensitivity="CRITICAL",
                confidence=0.85,
                regulatory=[],
                engine="regex",
            ),
        ]
        # gap = 0.95 - 0.85 = 0.10 < threshold 0.30
        result = _apply_findings_limit(findings, max_findings=None, confidence_gap_threshold=0.30)
        assert len(result) == 2

    def test_gap_suppression_disabled_with_high_threshold(self, profile) -> None:
        """Setting threshold to 1.0 disables gap suppression."""
        from data_classifier import _apply_findings_limit

        findings = [
            ClassificationFinding(
                column_id="col1",
                entity_type="SSN",
                category="PII",
                sensitivity="CRITICAL",
                confidence=0.95,
                regulatory=[],
                engine="regex",
            ),
            ClassificationFinding(
                column_id="col1",
                entity_type="PHONE",
                category="PII",
                sensitivity="HIGH",
                confidence=0.10,
                regulatory=[],
                engine="regex",
            ),
        ]
        result = _apply_findings_limit(findings, max_findings=None, confidence_gap_threshold=1.0)
        assert len(result) == 2

    def test_empty_findings_no_error(self, profile) -> None:
        """Empty findings list does not raise."""
        from data_classifier import _apply_findings_limit

        result = _apply_findings_limit([], max_findings=1, confidence_gap_threshold=0.30)
        assert result == []

    def test_sorted_by_confidence(self, profile) -> None:
        """Results are sorted by confidence descending."""
        from data_classifier import _apply_findings_limit

        findings = [
            ClassificationFinding(
                column_id="col1",
                entity_type="PHONE",
                category="PII",
                sensitivity="HIGH",
                confidence=0.70,
                regulatory=[],
                engine="regex",
            ),
            ClassificationFinding(
                column_id="col1",
                entity_type="SSN",
                category="PII",
                sensitivity="CRITICAL",
                confidence=0.95,
                regulatory=[],
                engine="regex",
            ),
        ]
        result = _apply_findings_limit(findings, max_findings=None, confidence_gap_threshold=1.0)
        assert result[0].entity_type == "SSN"
        assert result[1].entity_type == "PHONE"
