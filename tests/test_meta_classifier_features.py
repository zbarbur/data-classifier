"""Unit tests for the meta-classifier feature extraction layer.

Phase 1 scope: verify ``extract_features`` is deterministic, pure, and
handles every documented edge case on synthetic findings. No corpus
loading, no engine invocation — just hand-built ``ClassificationFinding``
fixtures.
"""

from __future__ import annotations

from data_classifier.core.types import ClassificationFinding, SampleAnalysis
from data_classifier.orchestrator.meta_classifier import (
    FEATURE_DIM,
    FEATURE_NAMES,
    MetaClassifier,
    extract_features,
)

# ── Fixture builders ─────────────────────────────────────────────────────────


def _make_finding(
    *,
    engine: str,
    entity_type: str,
    confidence: float,
    category: str = "PII",
    match_ratio: float | None = None,
) -> ClassificationFinding:
    sample_analysis = None
    if match_ratio is not None:
        sample_analysis = SampleAnalysis(
            samples_scanned=100,
            samples_matched=int(match_ratio * 100),
            samples_validated=int(match_ratio * 100),
            match_ratio=match_ratio,
        )
    return ClassificationFinding(
        column_id="test_col",
        entity_type=entity_type,
        category=category,
        sensitivity="HIGH",
        confidence=confidence,
        regulatory=[],
        engine=engine,
        sample_analysis=sample_analysis,
    )


# ── Tests ────────────────────────────────────────────────────────────────────


def test_feature_dim_matches_names():
    # E10 widened the schema from 15 → 20 by appending five GLiNER-derived
    # features. Additive-only: the original 15 names remain at indices 0..14
    # so v1.pkl still loads via _compute_dropped_indices (new slots become
    # "dropped by v1").
    assert FEATURE_DIM == len(FEATURE_NAMES) == 20


def test_feature_names_order_stable():
    # If someone reorders FEATURE_NAMES, this test pins the exact order so
    # the JSONL on disk doesn't silently become garbage. E10 appended five
    # GLiNER features — the first 15 names MUST stay in their original
    # positions so v1.pkl keeps loading.
    assert FEATURE_NAMES == (
        "top_overall_confidence",
        "regex_confidence",
        "column_name_confidence",
        "heuristic_confidence",
        "secret_scanner_confidence",
        "engines_agreed",
        "engines_fired",
        "confidence_gap",
        "regex_match_ratio",
        "heuristic_distinct_ratio",
        "heuristic_avg_length",
        "has_column_name_hit",
        "has_secret_indicators",
        "primary_is_pii",
        "primary_is_credential",
        "gliner_top_confidence",
        "gliner_top_entity_is_pii",
        "gliner_agrees_with_regex",
        "gliner_agrees_with_column",
        "gliner_confidence_gap",
    )


def test_empty_findings_returns_zero_vector():
    features = extract_features([])
    assert len(features) == 20
    assert all(v == 0.0 for v in features)
    assert all(isinstance(v, float) for v in features)


def test_gliner_features_default_to_zero_when_none_passed():
    # Backward-compat guardrail: when gliner_findings is not supplied (the
    # Phase 3 shadow-inference default), the five new slots must all be 0.0.
    # This is what lets v1.pkl's narrower 15-feature model keep working.
    f = _make_finding(engine="regex", entity_type="EMAIL", confidence=0.95, match_ratio=0.8)
    features = extract_features([f])
    assert features[15:] == [0.0, 0.0, 0.0, 0.0, 0.0]


def test_gliner_features_populated_when_findings_passed():
    # When a caller (the offline training pipeline) passes GLiNER findings,
    # the five new slots get real values.
    regex_email = _make_finding(engine="regex", entity_type="EMAIL", confidence=0.95, match_ratio=0.8)
    col_email = _make_finding(engine="column_name", entity_type="EMAIL", confidence=0.85)
    gliner_top = _make_finding(engine="gliner2", entity_type="EMAIL", confidence=0.9)
    gliner_second = _make_finding(engine="gliner2", entity_type="PERSON_NAME", confidence=0.4)

    features = extract_features(
        [regex_email, col_email],
        gliner_findings=[gliner_top, gliner_second],
    )
    assert features[15] == 0.9  # gliner_top_confidence
    assert features[16] == 1.0  # gliner_top_entity_is_pii (EMAIL category = PII)
    assert features[17] == 1.0  # gliner_agrees_with_regex (both say EMAIL)
    assert features[18] == 1.0  # gliner_agrees_with_column (both say EMAIL)
    assert abs(features[19] - 0.5) < 1e-9  # gliner_confidence_gap = 0.9 - 0.4


def test_gliner_confidence_gap_is_one_when_single_finding():
    gliner_only = _make_finding(engine="gliner2", entity_type="EMAIL", confidence=0.7)
    features = extract_features([], gliner_findings=[gliner_only])
    assert features[15] == 0.7
    assert features[19] == 1.0  # single gliner finding → no ambiguity → 1.0


def test_gliner_features_are_pure_when_gliner_findings_empty_list():
    f = _make_finding(engine="regex", entity_type="EMAIL", confidence=0.95, match_ratio=0.8)
    features = extract_features([f], gliner_findings=[])
    assert features[15:] == [0.0, 0.0, 0.0, 0.0, 0.0]


def test_empty_findings_respects_heuristic_kwargs():
    # Heuristic stats are caller-supplied — extract_features must forward
    # them even when no findings exist.
    features = extract_features([], heuristic_distinct_ratio=0.9, heuristic_avg_length=0.25)
    assert features[9] == 0.9
    assert features[10] == 0.25
    # Everything else must still be zero.
    for i, value in enumerate(features):
        if i not in (9, 10):
            assert value == 0.0


def test_single_regex_finding_fills_correct_slots():
    f = _make_finding(engine="regex", entity_type="EMAIL", confidence=0.95, match_ratio=0.8)
    features = extract_features([f])

    assert features[0] == 0.95  # top_overall_confidence
    assert features[1] == 0.95  # regex_confidence
    assert features[2] == 0.0  # column_name_confidence
    assert features[3] == 0.0  # heuristic_confidence
    assert features[4] == 0.0  # secret_scanner_confidence
    assert features[5] == 1.0  # engines_agreed (regex voted for EMAIL, which is the top)
    assert features[6] == 1.0  # engines_fired
    assert features[7] == 1.0  # confidence_gap (single finding → 1.0)
    assert features[8] == 0.8  # regex_match_ratio
    assert features[11] == 0.0  # has_column_name_hit
    assert features[12] == 0.0  # has_secret_indicators
    assert features[13] == 1.0  # primary_is_pii (EMAIL is PII)
    assert features[14] == 0.0  # primary_is_credential


def test_multi_engine_agreement_counts_correctly():
    # All four engines vote for EMAIL.
    findings = [
        _make_finding(engine="regex", entity_type="EMAIL", confidence=0.95, match_ratio=0.9),
        _make_finding(engine="column_name", entity_type="EMAIL", confidence=0.85),
        _make_finding(engine="heuristic_stats", entity_type="EMAIL", confidence=0.55),
        _make_finding(engine="secret_scanner", entity_type="EMAIL", confidence=0.50),
    ]
    features = extract_features(findings)

    assert features[5] == 4.0  # engines_agreed
    assert features[6] == 4.0  # engines_fired
    assert features[11] == 1.0  # has_column_name_hit
    assert features[12] == 1.0  # has_secret_indicators
    # confidence_gap = top − second = 0.95 − 0.85 = 0.10
    assert abs(features[7] - 0.10) < 1e-9


def test_multi_engine_disagreement_engines_agreed():
    # regex says EMAIL, column_name says PHONE (both similar confidence).
    # Top is EMAIL (0.96 > 0.92) — only regex agrees with top.
    findings = [
        _make_finding(engine="regex", entity_type="EMAIL", confidence=0.96, match_ratio=0.7),
        _make_finding(engine="column_name", entity_type="PHONE", confidence=0.92),
    ]
    features = extract_features(findings)

    assert features[0] == 0.96
    assert features[5] == 1.0  # engines_agreed — only regex voted for the top (EMAIL)
    assert features[6] == 2.0  # engines_fired
    # gap = 0.96 − 0.92 = 0.04
    assert abs(features[7] - 0.04) < 1e-9


def test_primary_is_credential_one_hot():
    f = _make_finding(
        engine="secret_scanner",
        entity_type="CREDENTIAL",
        confidence=0.8,
        category="Credential",
    )
    features = extract_features([f])

    assert features[13] == 0.0  # primary_is_pii
    assert features[14] == 1.0  # primary_is_credential
    assert features[12] == 1.0  # has_secret_indicators


def test_primary_category_flags_are_mutually_exclusive_for_non_pii():
    # Financial category — both PII and Credential should be 0.
    f = _make_finding(
        engine="regex",
        entity_type="IBAN",
        confidence=0.9,
        category="Financial",
    )
    features = extract_features([f])
    assert features[13] == 0.0
    assert features[14] == 0.0


def test_top_regex_match_ratio_uses_highest_confidence_regex():
    # Two regex findings — the higher-confidence one's match_ratio wins.
    findings = [
        _make_finding(engine="regex", entity_type="EMAIL", confidence=0.95, match_ratio=0.9),
        _make_finding(engine="regex", entity_type="PHONE", confidence=0.60, match_ratio=0.1),
    ]
    features = extract_features(findings)
    # regex_confidence must be the max, 0.95
    assert features[1] == 0.95
    # regex_match_ratio must come from the top-confidence regex finding
    assert features[8] == 0.9


def test_heuristic_kwargs_propagate_to_vector():
    f = _make_finding(engine="regex", entity_type="EMAIL", confidence=0.8, match_ratio=0.5)
    features = extract_features([f], heuristic_distinct_ratio=0.75, heuristic_avg_length=0.12)
    assert features[9] == 0.75
    assert features[10] == 0.12


def test_extract_features_is_pure():
    # Calling twice with the same input must yield identical vectors.
    findings = [
        _make_finding(engine="regex", entity_type="EMAIL", confidence=0.95, match_ratio=0.9),
        _make_finding(engine="column_name", entity_type="EMAIL", confidence=0.85),
    ]
    v1 = extract_features(findings, heuristic_distinct_ratio=0.5, heuristic_avg_length=0.3)
    v2 = extract_features(findings, heuristic_distinct_ratio=0.5, heuristic_avg_length=0.3)
    assert v1 == v2


def test_all_features_are_floats():
    findings = [
        _make_finding(engine="regex", entity_type="EMAIL", confidence=0.95, match_ratio=0.9),
        _make_finding(engine="heuristic_stats", entity_type="EMAIL", confidence=0.55),
    ]
    features = extract_features(findings)
    assert all(isinstance(v, float) for v in features)


def test_meta_classifier_predict_shadow_handles_empty_findings():
    # Phase 3 contract: predict_shadow never raises. Empty findings
    # either return None (model unavailable) or a prediction whose
    # live_entity is blank (model present). Either way, NO exception.
    mc = MetaClassifier()
    result = mc.predict_shadow([], [])
    # Model is present in the source tree so we expect a prediction,
    # but we also accept None so the test is robust in environments
    # where the [meta] extra is not installed.
    if result is not None:
        assert result.live_entity == ""
        assert result.column_id == ""
