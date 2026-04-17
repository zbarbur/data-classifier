"""Unit tests for the per-value aggregator helper (Sprint 13 Item B)."""

from __future__ import annotations

import pytest

from data_classifier.core.types import SpanDetection
from data_classifier.orchestrator.per_value_aggregator import aggregate_per_value_spans


def _span(entity_type: str, confidence: float) -> SpanDetection:
    return SpanDetection(text="x", entity_type=entity_type, confidence=confidence, start=0, end=1)


class TestAggregatePerValueSpans:
    def test_empty_input_returns_empty(self):
        assert aggregate_per_value_spans([], n_samples=0, column_id="c0") == []

    def test_single_entity_type_across_all_rows(self):
        per_value = [[_span("EMAIL", 0.9)] for _ in range(10)]
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert len(findings) == 1
        assert findings[0].entity_type == "EMAIL"
        assert findings[0].column_id == "c0"
        assert findings[0].confidence == pytest.approx(0.9)

    def test_coverage_below_min_is_dropped(self):
        per_value: list[list[SpanDetection]] = [[] for _ in range(20)]
        per_value[0] = [_span("EMAIL", 0.95)]
        findings = aggregate_per_value_spans(per_value, n_samples=20, column_id="c0")
        assert findings == []

    def test_two_entity_types_independently_aggregated(self):
        per_value: list[list[SpanDetection]] = []
        for _ in range(10):
            per_value.append([_span("EMAIL", 0.9), _span("IP_ADDRESS", 0.8)])
        for _ in range(10):
            per_value.append([_span("IP_ADDRESS", 0.85)])
        findings = aggregate_per_value_spans(per_value, n_samples=20, column_id="c0")
        by_type = {f.entity_type: f for f in findings}
        assert set(by_type) == {"EMAIL", "IP_ADDRESS"}
        assert by_type["EMAIL"].confidence == pytest.approx(0.45)
        assert by_type["IP_ADDRESS"].confidence == pytest.approx(0.85)

    def test_multiple_spans_same_type_same_row_count_row_once(self):
        per_value = [[_span("EMAIL", 0.9), _span("EMAIL", 0.7)]] * 10
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert len(findings) == 1
        assert findings[0].confidence == pytest.approx(0.9)

    def test_engine_attribution_is_gliner2(self):
        per_value = [[_span("EMAIL", 0.9)] for _ in range(10)]
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert findings[0].engine == "gliner2"

    def test_evidence_mentions_coverage(self):
        per_value = [[_span("EMAIL", 0.9)] for _ in range(8)] + [[] for _ in range(2)]
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert "8/10" in findings[0].evidence

    def test_custom_min_coverage(self):
        per_value: list[list[SpanDetection]] = [[] for _ in range(20)]
        for i in range(3):
            per_value[i] = [_span("EMAIL", 0.9)]
        assert len(aggregate_per_value_spans(per_value, n_samples=20, column_id="c0")) == 1
        assert aggregate_per_value_spans(per_value, n_samples=20, column_id="c0", min_coverage=0.2) == []

    def test_entity_metadata_populated_from_gliner_engine(self):
        per_value = [[_span("SSN", 0.9)] for _ in range(10)]
        findings = aggregate_per_value_spans(per_value, n_samples=10, column_id="c0")
        assert len(findings) == 1
        assert findings[0].sensitivity == "HIGH"
        assert "HIPAA" in findings[0].regulatory
