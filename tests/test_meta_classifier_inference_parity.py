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
        }
        missing = expected_kwargs - set(captured.keys())
        assert not missing, (
            f"predict_shadow omitted column-level stat kwargs: {sorted(missing)}. "
            f"The training path (tests/benchmarks/meta_classifier/extract_features.py) "
            f"threads all three; the inference path must stay in sync."
        )
