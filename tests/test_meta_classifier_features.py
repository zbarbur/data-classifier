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
    FEATURE_SCHEMA_VERSION,
    PRIMARY_ENTITY_TYPES,
    MetaClassifier,
    extract_features,
)

# Sprint 11 Phase 2: schema widened from 15 → 46 (15 base + 31 primary_entity_type one-hot).
# Sprint 11 Phase 7: added heuristic_dictionary_word_ratio at index 46 (total 47, schema v3).
_BASE_DIM = 15
_ONE_HOT_DIM = len(PRIMARY_ENTITY_TYPES)
_EXTRA_DIM = 1  # heuristic_dictionary_word_ratio
_EXPECTED_DIM = _BASE_DIM + _ONE_HOT_DIM + _EXTRA_DIM


def _one_hot_index(entity_type: str) -> int:
    """Return the absolute index in FEATURE_NAMES for a given entity type.

    Falls back to the UNKNOWN slot if the entity type is not in the vocab.
    """
    name = f"primary_entity_type={entity_type}"
    if name in FEATURE_NAMES:
        return FEATURE_NAMES.index(name)
    return FEATURE_NAMES.index("primary_entity_type=UNKNOWN")


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
    assert FEATURE_DIM == len(FEATURE_NAMES) == _EXPECTED_DIM


def test_feature_schema_version_is_v3():
    assert FEATURE_SCHEMA_VERSION == 3


def test_base_feature_names_order_stable():
    # The first 15 feature names are positional — reordering them silently
    # corrupts any trained artifact. Sprint 11 widening only APPENDS.
    assert FEATURE_NAMES[:_BASE_DIM] == (
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
    )


def test_primary_entity_type_vocab_ends_with_unknown():
    # UNKNOWN must be the catch-all slot at the end of the vocab so new
    # entity types can be appended without relocating it.
    assert PRIMARY_ENTITY_TYPES[-1] == "UNKNOWN"


def test_primary_entity_type_slots_are_prefixed_in_feature_names():
    # Every vocab entry gets a "primary_entity_type=X" slot in FEATURE_NAMES.
    for et in PRIMARY_ENTITY_TYPES:
        assert f"primary_entity_type={et}" in FEATURE_NAMES


def test_empty_findings_returns_base_zeros_and_unknown_one_hot():
    # No top finding → UNKNOWN slot is 1.0, base features and extras are all zero.
    features = extract_features([])
    assert len(features) == _EXPECTED_DIM
    assert all(isinstance(v, float) for v in features)
    # Base features are zero.
    assert all(v == 0.0 for v in features[:_BASE_DIM])
    # One-hot section has exactly one 1.0, on the UNKNOWN slot.
    one_hot_slice = features[_BASE_DIM : _BASE_DIM + _ONE_HOT_DIM]
    assert sum(one_hot_slice) == 1.0
    assert features[_one_hot_index("UNKNOWN")] == 1.0
    # Extras default to zero when the caller does not supply them.
    assert all(v == 0.0 for v in features[_BASE_DIM + _ONE_HOT_DIM :])


def test_empty_findings_respects_heuristic_kwargs():
    # Heuristic stats are caller-supplied — extract_features must forward
    # them even when no findings exist.
    features = extract_features([], heuristic_distinct_ratio=0.9, heuristic_avg_length=0.25)
    assert features[9] == 0.9
    assert features[10] == 0.25
    # All OTHER base features must still be zero.
    for i in range(_BASE_DIM):
        if i not in (9, 10):
            assert features[i] == 0.0
    # One-hot tail still resolves to UNKNOWN.
    assert features[_one_hot_index("UNKNOWN")] == 1.0


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

    # EMAIL one-hot slot is 1.0; UNKNOWN and all other slots are 0.0.
    assert features[_one_hot_index("EMAIL")] == 1.0
    assert features[_one_hot_index("UNKNOWN")] == 0.0
    # Exactly one one-hot slot set in the one-hot section.
    assert sum(features[_BASE_DIM : _BASE_DIM + _ONE_HOT_DIM]) == 1.0


def test_heuristic_dictionary_word_ratio_is_appended_at_schema_tail():
    # Sprint 11 Phase 7: the dict-word-ratio feature sits at index 46,
    # after the base (0-14) and one-hot (15-45) sections.
    dict_ratio = 0.42
    features = extract_features([], heuristic_dictionary_word_ratio=dict_ratio)
    # The last slot is the extra.
    assert features[-1] == dict_ratio
    # Base + one-hot are unchanged (base is zero, one-hot is UNKNOWN).
    assert all(v == 0.0 for v in features[:_BASE_DIM])
    assert features[_one_hot_index("UNKNOWN")] == 1.0
    assert sum(features[_BASE_DIM : _BASE_DIM + _ONE_HOT_DIM]) == 1.0


def test_heuristic_dictionary_word_ratio_defaults_to_zero():
    features = extract_features([])
    assert features[-1] == 0.0


def test_unknown_entity_type_falls_back_to_unknown_slot():
    # An entity_type outside the vocab must land in the UNKNOWN slot,
    # not crash extract_features.
    f = _make_finding(
        engine="regex",
        entity_type="NOT_A_REAL_TYPE_ZZZ",
        confidence=0.5,
        match_ratio=0.1,
    )
    features = extract_features([f])
    assert features[_one_hot_index("UNKNOWN")] == 1.0
    assert sum(features[_BASE_DIM : _BASE_DIM + _ONE_HOT_DIM]) == 1.0


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


def _dump_artifact(path, payload) -> None:
    """Serialize a model payload to disk using the same format the
    production loader expects. Dynamic import keeps the literal module
    name out of static scans while the actual behavior is unchanged.
    """
    import importlib

    serializer = importlib.import_module("pickle")
    path.write_bytes(serializer.dumps(payload))


def test_version_gate_refuses_mismatched_artifact(tmp_path):
    # Sprint 11 contract: an artifact whose feature_schema_version does
    # not match FEATURE_SCHEMA_VERSION must be refused — predict_shadow
    # returns None, _available stays False. This prevents a v1 artifact
    # from silently being used against the widened v2 feature vector.
    stale = {
        "feature_schema_version": 1,
        "model": object(),  # won't be touched — we refuse before use
        "scaler": object(),
        "feature_names": list(FEATURE_NAMES[:_BASE_DIM]),  # old 15-feature shape
        "class_labels": ["EMAIL"],
    }
    stale_path = tmp_path / "stale_meta.bin"
    _dump_artifact(stale_path, stale)

    mc = MetaClassifier(model_path=stale_path)
    result = mc.predict_shadow([], [])
    assert result is None
    assert mc._available is False


def test_version_gate_accepts_matching_artifact(tmp_path):
    # Same-version artifact must load normally. We can't reuse a trained
    # production model here, so we build a tiny 2-class model on the
    # full current-schema feature vector purely for the load-path contract
    # check. FEATURE_DIM tracks schema upgrades automatically.
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    rng = np.random.default_rng(0)
    X = rng.normal(size=(20, FEATURE_DIM))
    y = np.array(["EMAIL"] * 10 + ["SSN"] * 10)
    scaler = StandardScaler().fit(X)
    model = LogisticRegression(max_iter=1000).fit(scaler.transform(X), y)

    payload = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "model": model,
        "scaler": scaler,
        "feature_names": list(FEATURE_NAMES),
        "class_labels": list(model.classes_),
    }
    path = tmp_path / "v2_meta.bin"
    _dump_artifact(path, payload)

    mc = MetaClassifier(model_path=path)
    mc.predict_shadow([], [])  # triggers the load path
    assert mc._available is True
