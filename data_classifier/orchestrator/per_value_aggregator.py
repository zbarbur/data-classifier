"""Per-value GLiNER span aggregator (Sprint 13 Item B).

Takes the list[list[SpanDetection]] output from GLiNER2Engine.classify_per_value
and aggregates it into column-level ClassificationFinding instances.

Aggregation rules:
  coverage(entity_type) = (# rows with >= 1 span of entity_type) / n_samples
  confidence(entity_type) = coverage * max(span.confidence for that type)

Entity type with coverage < min_coverage (default 0.1) is dropped.
"""

from __future__ import annotations

from data_classifier.core.types import ClassificationFinding, SampleAnalysis, SpanDetection

_DEFAULT_MIN_COVERAGE: float = 0.1
_MAX_EVIDENCE_SAMPLES: int = 5


def aggregate_per_value_spans(
    per_value_spans: list[list[SpanDetection]],
    *,
    n_samples: int,
    column_id: str,
    min_coverage: float = _DEFAULT_MIN_COVERAGE,
) -> list[ClassificationFinding]:
    """Convert per-value GLiNER spans into column-level findings.

    Args:
        per_value_spans: Outer list = per sampled row; inner list = spans.
        n_samples: Number of rows actually inferred (divisor of coverage).
        column_id: Column ID stamped onto emitted findings.
        min_coverage: Drop entity types with coverage below this.

    Returns:
        One ClassificationFinding per entity type meeting the coverage floor.
    """
    if not per_value_spans or n_samples <= 0:
        return []

    from data_classifier.engines.gliner_engine import _ENTITY_METADATA

    rows_with_type: dict[str, int] = {}
    max_conf: dict[str, float] = {}
    sample_texts: dict[str, list[str]] = {}

    for row_spans in per_value_spans:
        seen_this_row: set[str] = set()
        for span in row_spans:
            if span.entity_type not in seen_this_row:
                rows_with_type[span.entity_type] = rows_with_type.get(span.entity_type, 0) + 1
                seen_this_row.add(span.entity_type)
            prior_max = max_conf.get(span.entity_type, 0.0)
            if span.confidence > prior_max:
                max_conf[span.entity_type] = span.confidence
            bucket = sample_texts.setdefault(span.entity_type, [])
            if len(bucket) < _MAX_EVIDENCE_SAMPLES and span.text:
                bucket.append(span.text)

    findings: list[ClassificationFinding] = []
    for entity_type, count in rows_with_type.items():
        coverage = count / n_samples
        if coverage < min_coverage:
            continue
        confidence = min(coverage * max_conf.get(entity_type, 0.0), 1.0)
        metadata = _ENTITY_METADATA.get(entity_type, {})
        findings.append(
            ClassificationFinding(
                column_id=column_id,
                entity_type=entity_type,
                category=metadata.get("category", "PII"),
                sensitivity=metadata.get("sensitivity", "MEDIUM"),
                confidence=round(confidence, 4),
                regulatory=list(metadata.get("regulatory", [])),
                engine="gliner2",
                evidence=(
                    f"GLiNER per-value: {entity_type} detected in "
                    f"{count}/{n_samples} sampled rows "
                    f"(coverage={coverage:.2f}, max_span_conf={max_conf.get(entity_type, 0.0):.2f})"
                ),
                sample_analysis=SampleAnalysis(
                    samples_scanned=n_samples,
                    samples_matched=count,
                    samples_validated=count,
                    match_ratio=coverage,
                    sample_matches=sample_texts.get(entity_type, []),
                ),
            )
        )
    return findings
