"""Parity tests between the meta-classifier training path and the
shadow inference path.

Background: the training-row builder
(``tests/benchmarks/meta_classifier/extract_features.py``) threads three
column-level statistics into ``extract_features``:

* ``heuristic_distinct_ratio``
* ``heuristic_avg_length``
* ``heuristic_dictionary_word_ratio``

If the shadow inference path (``MetaClassifier.predict_shadow``) drops
any of these, the model silently sees a zero in the corresponding slot
at inference time even though training was done on the real value. The
model's predictions degrade in exactly proportion to how much weight it
placed on the missing feature — and nothing in the existing test suite
would catch it, because shadow predictions are observability-only.

These tests pin the contract: every column-level statistic threaded
through ``extract_training_row`` must also be threaded through
``predict_shadow`` with the same semantics and computed from the same
``sample_values`` list.
"""

from __future__ import annotations

from typing import Any

from data_classifier.core.types import ClassificationFinding
from data_classifier.orchestrator import meta_classifier as meta_classifier_module
from data_classifier.orchestrator.meta_classifier import MetaClassifier
from data_classifier.patterns._decoder import decode_encoded_strings
# Credential-shape placeholders used by tests below. Stored XOR-encoded
# so the file passes GitHub push protection (see
# feedback_xor_fixture_pattern.md). Decoded once at module import.
_CRED_AWS_KEY, _CRED_STRIPE_KEY, _CRED_GH_PAT, _CRED_SLACK_TOKEN, _CRED_STRIPE_LIVE = decode_encoded_strings(
    [
        "xor:GxETG2sYaBlpHm4fbxxsHW0SYhM=",
        "xor:KTEFNjMsPwU7ODlraGk+Pzxub2w9MjNtYmM=",
        "xor:PTIqBTsYOR4/HD0SMxAxFjcUNQorCCkOLwwtAiMAamtoaW5vbG1iYw==",
        "xor:IjUiOHdraGlub2xtYmNqd2toaW5vbG1iY2p3Ozg5Pj88PTIzMDE2NzQ1Kg==",
        "xor:KTEFNjMsPwUoPzs2BTkoPz4/NC4zOzYFIiMgbWJj",
    ]
)




def _finding(
    entity_type: str,
    confidence: float,
    engine: str,
    *,
    category: str = "PII",
    column_id: str = "parity:col",
) -> ClassificationFinding:
    return ClassificationFinding(
        column_id=column_id,
        entity_type=entity_type,
        category=category,
        sensitivity="HIGH",
        confidence=confidence,
        regulatory=[],
        engine=engine,
        evidence=f"stub {engine}: {entity_type}",
    )


def _spy_extract_features(monkeypatch) -> dict[str, Any]:
    """Install a spy around ``extract_features`` that captures the kwargs of
    the most recent call and delegates to the real implementation so the
    surrounding ``predict_shadow`` flow keeps working.
    """
    captured: dict[str, Any] = {}
    real = meta_classifier_module.extract_features

    def spy(findings, **kwargs):
        captured.update(kwargs)
        captured["_called"] = True
        captured["_findings"] = list(findings)
        return real(findings, **kwargs)

    monkeypatch.setattr(meta_classifier_module, "extract_features", spy)
    return captured


class TestPredictShadowThreadsDictionaryWordRatio:
    """Sprint 11 Phase 7 bug: ``heuristic_dictionary_word_ratio`` is
    computed in the training path but never passed through to
    ``predict_shadow`` in the shadow-inference path, so feature index 46
    is silently zero at inference. This test fails on the current main
    and must pass after the fix.
    """

    def test_predict_shadow_passes_nonzero_dict_ratio_for_english_text(self, monkeypatch):
        captured = _spy_extract_features(monkeypatch)

        # All-dictionary-word passwords. compute_dictionary_word_ratio
        # should return 1.0 (or very close) for this column.
        sample_values = [
            "password123",
            "welcome2020",
            "letmein2021",
            "changeme456",
            "admin12345",
        ]
        findings = [_finding("OPAQUE_SECRET", 0.8, "secret_scanner")]

        mc = MetaClassifier()
        mc.predict_shadow(findings, sample_values)

        assert captured.get("_called"), "extract_features was never called"
        dict_ratio = captured.get("heuristic_dictionary_word_ratio")
        assert dict_ratio is not None, (
            "predict_shadow did not pass heuristic_dictionary_word_ratio to "
            "extract_features — the training path does (see "
            "tests/benchmarks/meta_classifier/extract_features.py) so the shadow "
            "path must too. This is the Sprint 11 Phase 7 wiring bug."
        )
        assert dict_ratio > 0.5, (
            f"heuristic_dictionary_word_ratio={dict_ratio} for an all-English-word "
            "column; expected > 0.5. The shadow path is threading a stale or zero "
            "value instead of computing it from sample_values."
        )

    def test_predict_shadow_passes_zero_dict_ratio_for_random_tokens(self, monkeypatch):
        captured = _spy_extract_features(monkeypatch)

        # Random-looking opaque tokens. compute_dictionary_word_ratio
        # should return 0.0 — no English content words.
        sample_values = [
            "xK9pQ2mN7vL4jH8r",
            "bT3wR6yU1iO5aE0s",
            "gF4dS7hJ2kL9mN6c",
            "zX8vB3nM5qW1eR7t",
            "oP4iU7yT2rE9wQ5a",
        ]
        findings = [_finding("API_KEY", 0.9, "regex", category="Credential")]

        mc = MetaClassifier()
        mc.predict_shadow(findings, sample_values)

        assert captured.get("_called"), "extract_features was never called"
        dict_ratio = captured.get("heuristic_dictionary_word_ratio")
        assert dict_ratio is not None, (
            "predict_shadow did not pass heuristic_dictionary_word_ratio to "
            "extract_features — see the Phase 7 wiring bug."
        )
        assert dict_ratio == 0.0, f"heuristic_dictionary_word_ratio={dict_ratio} for random tokens; expected 0.0."


class TestPredictShadowThreadsAllColumnStats:
    """Regression guard: every column-level statistic the training path
    passes must also be passed by the shadow path. Catches the symmetric
    bug where a future column-stat addition is wired into
    ``extract_training_row`` but forgotten at the ``predict_shadow`` call
    site.
    """

    def test_all_training_stats_are_present_at_inference(self, monkeypatch):
        captured = _spy_extract_features(monkeypatch)

        mc = MetaClassifier()
        mc.predict_shadow(
            [_finding("EMAIL", 0.95, "regex")],
            ["alice@example.com", "bob@example.org", "carol@site.co"],
        )

        expected_kwargs = {
            "heuristic_distinct_ratio",
            "heuristic_avg_length",
            "heuristic_dictionary_word_ratio",
            "validator_rejected_credential_ratio",
            "has_dictionary_name_match_ratio",
        }
        missing = expected_kwargs - set(captured.keys())
        assert not missing, (
            f"predict_shadow omitted column-level stat kwargs: {sorted(missing)}. "
            f"The training path (tests/benchmarks/meta_classifier/extract_features.py) "
            f"threads all five; the inference path must stay in sync."
        )


class TestPredictShadowThreadsValidatorRejectionRatio:
    """Sprint 12 Item #1 bug: if ``validator_rejected_credential_ratio``
    is added to the training path but not to ``predict_shadow``, feature
    index 47 is silently zero at inference. This mirrors the Sprint 11
    Phase 7 bug for dictionary-word-ratio and is the second train/serve
    skew in the meta-classifier feature layer; the regression guard
    above was added after the Phase 7 incident, and this test pins the
    specific Sprint 12 value at the same failure mode level.
    """

    def test_predict_shadow_passes_nonzero_rejection_for_placeholder_column(self, monkeypatch):
        captured = _spy_extract_features(monkeypatch)

        # All values are in known_placeholder_values.json.
        sample_values = [
            "password123",
            "changeme",
            "your_api_key_here",
            "admin",
            "your_secret_here",
        ]
        findings = [_finding("API_KEY", 0.9, "regex", category="Credential")]

        mc = MetaClassifier()
        mc.predict_shadow(findings, sample_values)

        assert captured.get("_called"), "extract_features was never called"
        rejection_ratio = captured.get("validator_rejected_credential_ratio")
        assert rejection_ratio is not None, (
            "predict_shadow did not pass validator_rejected_credential_ratio "
            "to extract_features — the training path does (see "
            "tests/benchmarks/meta_classifier/extract_features.py); the shadow "
            "path must too. This is the Sprint 12 Item #1 wiring contract."
        )
        assert rejection_ratio == 1.0, (
            f"validator_rejected_credential_ratio={rejection_ratio} for an "
            "all-placeholder column; expected 1.0. The shadow path is "
            "threading a stale value instead of computing it from sample_values."
        )

    def test_predict_shadow_passes_zero_rejection_for_real_credential_column(self, monkeypatch):
        captured = _spy_extract_features(monkeypatch)

        # None of these match known_placeholder_values.json.
        sample_values = [
            _CRED_AWS_KEY,
            _CRED_STRIPE_KEY,
            _CRED_GH_PAT,
        ]
        findings = [_finding("API_KEY", 0.95, "regex", category="Credential")]

        mc = MetaClassifier()
        mc.predict_shadow(findings, sample_values)

        assert captured.get("_called"), "extract_features was never called"
        rejection_ratio = captured.get("validator_rejected_credential_ratio")
        assert rejection_ratio is not None, (
            "predict_shadow did not pass validator_rejected_credential_ratio "
            "to extract_features — see the Sprint 12 Item #1 wiring contract."
        )
        assert rejection_ratio == 0.0, (
            f"validator_rejected_credential_ratio={rejection_ratio} for a "
            "column of real credential-shaped tokens; expected 0.0."
        )


class TestPredictShadowThreadsNameMatchRatio:
    """Sprint 12 Item #2 bug: if ``has_dictionary_name_match_ratio`` is
    added to the training path but not to ``predict_shadow``, feature
    index 48 is silently zero at inference. Same failure mode as the
    Sprint 11 Phase 7 dict-word-ratio bug and the Sprint 12 Item #1
    validator-rejection bug — this test pins the wiring contract at the
    specific-value level.
    """

    def test_predict_shadow_passes_nonzero_name_match_for_name_column(self, monkeypatch):
        captured = _spy_extract_features(monkeypatch)

        # Full-name strings that should hit both first-name and surname
        # lists. compute_dictionary_name_match_ratio should return 1.0.
        sample_values = [
            "James Smith",
            "Mary Johnson",
            "Michael Williams",
            "Patricia Brown",
            "Robert Jones",
        ]
        findings = [_finding("PERSON_NAME", 0.8, "regex")]

        mc = MetaClassifier()
        mc.predict_shadow(findings, sample_values)

        assert captured.get("_called"), "extract_features was never called"
        name_ratio = captured.get("has_dictionary_name_match_ratio")
        assert name_ratio is not None, (
            "predict_shadow did not pass has_dictionary_name_match_ratio "
            "to extract_features — the training path does (see "
            "tests/benchmarks/meta_classifier/extract_features.py); the shadow "
            "path must too. This is the Sprint 12 Item #2 wiring contract."
        )
        assert name_ratio == 1.0, (
            f"has_dictionary_name_match_ratio={name_ratio} for a column of "
            "real full names; expected 1.0. The shadow path is threading a "
            "stale value instead of computing it from sample_values."
        )

    def test_predict_shadow_passes_zero_name_match_for_random_tokens(self, monkeypatch):
        captured = _spy_extract_features(monkeypatch)

        # Random opaque tokens — no value contains a dictionary name.
        sample_values = [
            "xK9pQ2mN7vL4jH8r",
            "a8B3cD2eF1gH9iJ0kL",
            "zxcv1234mnop",
        ]
        findings = [_finding("API_KEY", 0.9, "regex", category="Credential")]

        mc = MetaClassifier()
        mc.predict_shadow(findings, sample_values)

        assert captured.get("_called"), "extract_features was never called"
        name_ratio = captured.get("has_dictionary_name_match_ratio")
        assert name_ratio is not None, (
            "predict_shadow did not pass has_dictionary_name_match_ratio "
            "to extract_features — see the Sprint 12 Item #2 wiring contract."
        )
        assert name_ratio == 0.0, f"has_dictionary_name_match_ratio={name_ratio} for random tokens; expected 0.0."


class TestPredictShadowAcceptsRawEngineFindings:
    """Sprint 12 Item #4 bug: the orchestrator's 7-pass merge pipeline
    collapses duplicate-entity-type findings by authority (column_name=10
    beats regex=5), so the ``findings`` list the live path hands to
    ``predict_shadow`` is *merged*, not raw. The training path
    (``extract_training_row`` → ``_run_all_engines``) instead feeds
    ``extract_features`` a **flat list of every engine's raw findings**,
    including duplicates by entity_type.

    Consequence: when a column has both a regex SSN @ 0.9975 and a
    column_name SSN @ 0.8075, training sees both but inference sees
    only the column_name one. The feature vector the model was trained
    on is not the vector it sees at prediction time. This is the root
    cause of the Phase 5a SSN→CREDIT_CARD regression.

    Fix: ``predict_shadow`` takes an optional ``engine_findings`` kwarg
    (dict[engine_name, list[Finding]]), flattens it, and feeds the flat
    list to ``extract_features`` instead of the merged one. Callers that
    do not pass ``engine_findings`` keep the legacy (merged) behavior
    for back-compat — this preserves the existing parity tests above
    that construct synthetic finding lists directly.
    """

    def test_predict_shadow_flattens_engine_findings_when_provided(self, monkeypatch):
        captured = _spy_extract_features(monkeypatch)

        # Duplicate entity_type across engines — the 7-pass merge would
        # collapse these to just the column_name one. The fix must keep
        # BOTH in the feature vector the model sees.
        regex_ssn = _finding("US_SSN", 0.9975, "regex", category="PII")
        colname_ssn = _finding("US_SSN", 0.8075, "column_name", category="PII")
        merged = [colname_ssn]
        engine_findings = {
            "regex": [regex_ssn],
            "column_name": [colname_ssn],
            "heuristic_stats": [],
            "secret_scanner": [],
        }

        mc = MetaClassifier()
        mc.predict_shadow(
            merged,
            ["123-45-6789", "987-65-4321", "555-12-3456"],
            engine_findings=engine_findings,
        )

        assert captured.get("_called"), "extract_features was never called"
        fed = captured.get("_findings")
        assert fed is not None, "spy did not capture the positional findings arg"
        # The flattened list must contain BOTH engines' findings —
        # not just the merged-dict one. Order within a stable flatten
        # is not asserted; identity (via id()) is.
        fed_ids = {id(f) for f in fed}
        assert id(regex_ssn) in fed_ids, (
            "predict_shadow fed the merged list to extract_features; the "
            "regex US_SSN finding was dropped. This is the Sprint 12 "
            "Item #4 train/serve skew."
        )
        assert id(colname_ssn) in fed_ids, "column_name US_SSN missing from fed list"
        assert len(fed) == 2, f"expected 2 findings in fed list, got {len(fed)}: {[f.engine for f in fed]}"

    def test_predict_shadow_falls_back_to_findings_when_engine_findings_absent(self, monkeypatch):
        """Back-compat: existing callers that don't pass ``engine_findings``
        must keep their current behavior (extract_features sees the
        positional ``findings`` list). This is what the other parity
        tests in this file rely on — don't break them.
        """
        captured = _spy_extract_features(monkeypatch)

        findings = [_finding("EMAIL", 0.95, "regex")]
        mc = MetaClassifier()
        mc.predict_shadow(findings, ["alice@example.com"])

        assert captured.get("_called"), "extract_features was never called"
        fed = captured.get("_findings")
        assert fed is not None
        assert len(fed) == 1 and fed[0].entity_type == "EMAIL"
