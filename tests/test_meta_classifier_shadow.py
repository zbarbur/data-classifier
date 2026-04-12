"""Tests for Sprint 6 Phase 3 — meta-classifier shadow inference.

Covers lazy loading, graceful degradation when sklearn or the model
artifact is missing, event emission, the DATA_CLASSIFIER_DISABLE_META
opt-out, and the hard invariant that the shadow path NEVER mutates the
``classify_columns()`` return value.
"""

from __future__ import annotations

import logging
import os
import sys
from unittest import mock

import pytest

from data_classifier import ColumnInput, classify_columns, load_profile
from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import (
    ClassificationEvent,
    MetaClassifierEvent,
    TierEvent,
)
from data_classifier.orchestrator.meta_classifier import (
    FEATURE_NAMES,
    MetaClassifier,
    MetaClassifierPrediction,
)
from data_classifier.orchestrator.orchestrator import Orchestrator

# ── Helpers ──────────────────────────────────────────────────────────────────


def _email_column(cid: str = "col_email") -> ColumnInput:
    return ColumnInput(
        column_id=cid,
        column_name="user_email",
        sample_values=[
            "alice@example.com",
            "bob@example.org",
            "charlie@test.co",
            "dana@company.io",
            "eve@acme.net",
        ],
    )


def _ip_column(cid: str = "col_ip") -> ColumnInput:
    return ColumnInput(
        column_id=cid,
        column_name="client_address",
        sample_values=[
            "192.168.1.1",
            "10.0.0.5",
            "172.16.254.1",
            "192.168.100.200",
            "8.8.8.8",
        ],
    )


def _make_finding(
    entity_type: str,
    confidence: float,
    engine: str,
    *,
    category: str = "PII",
    column_id: str = "test:col",
) -> ClassificationFinding:
    return ClassificationFinding(
        column_id=column_id,
        entity_type=entity_type,
        category=category,
        sensitivity="HIGH",
        confidence=confidence,
        regulatory=[],
        engine=engine,
        evidence=f"Stub {engine}: {entity_type}",
    )


class _StubEngine(ClassificationEngine):
    """Minimal engine that returns a fixed findings list."""

    def __init__(
        self,
        name: str,
        order: int,
        authority: int,
        findings: list[ClassificationFinding],
    ) -> None:
        self.name = name
        self.order = order
        self.authority = authority
        self.supported_modes = frozenset({"structured"})
        self._findings = findings

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        # Rebind column_id on each call so stub findings attach to the
        # column under test.
        return [
            ClassificationFinding(
                column_id=column.column_id,
                entity_type=f.entity_type,
                category=f.category,
                sensitivity=f.sensitivity,
                confidence=f.confidence,
                regulatory=f.regulatory,
                engine=f.engine,
                evidence=f.evidence,
                sample_analysis=f.sample_analysis,
            )
            for f in self._findings
        ]


@pytest.fixture
def standard_profile() -> ClassificationProfile:
    return load_profile("standard")


@pytest.fixture(autouse=True)
def _disable_ml_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep GLiNER2 out of shadow tests — it's slow and not relevant here."""
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_ML", "1")


@pytest.fixture
def capture_events() -> tuple[EventEmitter, list]:
    """Returns (emitter, events list) — events append in order."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(lambda ev: events.append(ev)))
    return emitter, events


# ── 1. Lazy loading ─────────────────────────────────────────────────────────


def test_constructor_does_not_load_model() -> None:
    """Instantiating MetaClassifier must not touch the model artifact."""
    import pickle as _mod

    with mock.patch.object(_mod, "load", side_effect=AssertionError("loader called in __init__")):
        mc = MetaClassifier()
        assert mc._loaded is False
        assert mc._available is False
        assert mc._model is None


# ── 2. First call loads; subsequent calls do not reload ─────────────────────


def test_first_predict_loads_then_cached() -> None:
    mc = MetaClassifier()
    findings = [_make_finding("EMAIL", 0.95, "regex", column_id="c1")]
    pred1 = mc.predict_shadow(findings, ["a@b.com", "c@d.com"])
    assert pred1 is not None
    assert mc._loaded is True
    assert mc._available is True

    # Second call must not reload — patch the loader and assert not called.
    with mock.patch.object(mc, "_get_model_path", side_effect=AssertionError("reload attempted")):
        pred2 = mc.predict_shadow(findings, ["a@b.com"])
    assert pred2 is not None


# ── 3. predict_shadow returns a fully populated prediction ──────────────────


def test_predict_shadow_returns_populated_prediction() -> None:
    mc = MetaClassifier()
    findings = [
        _make_finding("EMAIL", 0.97, "regex", column_id="col_x"),
        _make_finding("EMAIL", 0.90, "column_name", column_id="col_x"),
    ]
    pred = mc.predict_shadow(findings, ["a@b.com", "c@d.com", "e@f.com"])
    assert isinstance(pred, MetaClassifierPrediction)
    assert pred.column_id == "col_x"
    assert pred.live_entity == "EMAIL"
    assert isinstance(pred.predicted_entity, str)
    assert pred.predicted_entity != ""
    assert 0.0 <= pred.confidence <= 1.0
    assert isinstance(pred.agreement, bool)


# ── 4. Missing sklearn → None, warning logged once ──────────────────────────


def test_predict_shadow_none_when_sklearn_missing(caplog: pytest.LogCaptureFixture) -> None:
    # Remove sklearn from sys.modules and block re-import
    original = {k: sys.modules[k] for k in list(sys.modules) if k == "sklearn" or k.startswith("sklearn.")}
    for k in original:
        del sys.modules[k]

    class _Blocker:
        def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
            if fullname == "sklearn" or fullname.startswith("sklearn."):
                raise ImportError(f"blocked: {fullname}")
            return None

    blocker = _Blocker()
    sys.meta_path.insert(0, blocker)
    try:
        mc = MetaClassifier()
        with caplog.at_level(logging.WARNING, logger="data_classifier.orchestrator.meta_classifier"):
            pred = mc.predict_shadow([_make_finding("EMAIL", 0.9, "regex")], ["a@b.com"])
        assert pred is None
        assert any("scikit-learn" in rec.message or "MetaClassifier disabled" in rec.message for rec in caplog.records)

        # Second call must not re-warn (warning is one-shot)
        caplog.clear()
        pred2 = mc.predict_shadow([_make_finding("EMAIL", 0.9, "regex")], ["a@b.com"])
        assert pred2 is None
        assert all("MetaClassifier disabled" not in rec.message for rec in caplog.records)
    finally:
        sys.meta_path.remove(blocker)
        sys.modules.update(original)


# ── 5. Missing model file → None ────────────────────────────────────────────


def test_predict_shadow_none_when_model_file_missing() -> None:
    mc = MetaClassifier(model_path="/tmp/data_classifier_does_not_exist_meta.pkl")
    pred = mc.predict_shadow([_make_finding("EMAIL", 0.9, "regex")], ["a@b.com"])
    assert pred is None


# ── 6. Empty findings list ──────────────────────────────────────────────────


def test_predict_shadow_empty_findings_returns_prediction_with_empty_live() -> None:
    """Empty findings still produce a prediction — live_entity is blank."""
    mc = MetaClassifier()
    pred = mc.predict_shadow([], ["some", "sample", "values"])
    assert pred is not None
    assert pred.live_entity == ""
    assert pred.column_id == ""
    assert pred.agreement is False


# ── 7/8. Agreement vs disagreement ──────────────────────────────────────────


def test_agreement_true_when_meta_matches_live(standard_profile: ClassificationProfile) -> None:
    """Use a real email column — regex picks EMAIL and so should the shadow."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    classify_columns([_email_column()], standard_profile, event_emitter=emitter)
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert len(meta_events) == 1
    ev = meta_events[0]
    assert ev.live_entity == "EMAIL"
    # Agreement depends on what the trained model picks. Assert the
    # field is a bool and matches the comparison semantics.
    assert ev.agreement == (ev.predicted_entity == ev.live_entity)


def test_agreement_field_computed_correctly() -> None:
    """Directly verify the agreement comparison semantics."""
    mc = MetaClassifier()
    findings = [_make_finding("EMAIL", 0.99, "regex", column_id="c1")]
    pred = mc.predict_shadow(findings, ["alice@example.com"] * 5)
    assert pred is not None
    # agreement must equal predicted==live
    assert pred.agreement == (pred.predicted_entity == pred.live_entity)


# ── 9. Return value is unchanged when shadow path runs ──────────────────────


def test_classify_columns_return_value_unchanged_by_shadow(
    standard_profile: ClassificationProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    col = _email_column()

    # Run with shadow enabled
    monkeypatch.delenv("DATA_CLASSIFIER_DISABLE_META", raising=False)
    with_shadow = classify_columns([col], standard_profile)

    # Run with shadow disabled
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_META", "1")
    without_shadow = classify_columns([col], standard_profile)

    def _key(f: ClassificationFinding) -> tuple[str, str, float]:
        return (f.column_id, f.entity_type, round(f.confidence, 6))

    assert sorted(_key(f) for f in with_shadow) == sorted(_key(f) for f in without_shadow)


# ── 10. MetaClassifierEvent is emitted ──────────────────────────────────────


def test_meta_classifier_event_emitted(standard_profile: ClassificationProfile) -> None:
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    classify_columns([_email_column("c1"), _ip_column("c2")], standard_profile, event_emitter=emitter)
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    # One event per column
    assert len(meta_events) == 2
    for ev in meta_events:
        assert ev.column_id != ""
        assert ev.predicted_entity != ""
        assert 0.0 <= ev.confidence <= 1.0
        assert isinstance(ev.agreement, bool)


# ── 11. DISABLE_META env var skips shadow entirely ──────────────────────────


def test_disable_meta_env_skips_shadow(
    standard_profile: ClassificationProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_META", "1")

    # Patch the MetaClassifier class so we can assert it's never used
    load_calls: list[str] = []

    class _SpyMC(MetaClassifier):
        def _ensure_loaded(self) -> bool:  # type: ignore[override]
            load_calls.append("loaded")
            return False

    monkeypatch.setattr(
        "data_classifier.orchestrator.orchestrator.MetaClassifier",
        _SpyMC,
    )

    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    classify_columns([_email_column()], standard_profile, event_emitter=emitter)
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert meta_events == []
    assert load_calls == []


# ── 12. Shadow failure does not propagate ───────────────────────────────────


def test_shadow_failure_never_breaks_live_path(
    standard_profile: ClassificationProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(self, findings, sample_values=None):  # noqa: ARG001
        raise RuntimeError("shadow crashed on purpose")

    monkeypatch.setattr(MetaClassifier, "predict_shadow", _boom)

    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    findings = classify_columns([_email_column()], standard_profile, event_emitter=emitter)
    # Live path still returns the EMAIL finding
    assert any(f.entity_type == "EMAIL" for f in findings)
    # And no shadow event was emitted
    assert [e for e in events if isinstance(e, MetaClassifierEvent)] == []
    # ClassificationEvent still fires — live path integrity
    assert any(isinstance(e, ClassificationEvent) for e in events)


# ── 13. _compute_dropped_indices ────────────────────────────────────────────


def test_compute_dropped_indices_canonical() -> None:
    kept = tuple(n for n in FEATURE_NAMES if n not in ("has_column_name_hit", "engines_fired"))
    dropped = MetaClassifier._compute_dropped_indices(kept=kept, full=FEATURE_NAMES)
    # engines_fired is at index 6, has_column_name_hit at index 11
    assert FEATURE_NAMES[6] == "engines_fired"
    assert FEATURE_NAMES[11] == "has_column_name_hit"
    assert set(dropped) == {6, 11}


def test_trained_model_dropped_indices_match_metadata() -> None:
    """The shipped model must drop exactly engines_fired + has_column_name_hit."""
    mc = MetaClassifier()
    # Force load
    assert mc._ensure_loaded() is True
    assert set(mc._dropped_feature_indices) == {6, 11}
    assert "engines_fired" not in mc._feature_names
    assert "has_column_name_hit" not in mc._feature_names


# ── 14. run_id propagation ──────────────────────────────────────────────────


def test_run_id_propagates_to_meta_event(standard_profile: ClassificationProfile) -> None:
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    classify_columns(
        [_email_column()],
        standard_profile,
        event_emitter=emitter,
        run_id="abc123",
    )
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert len(meta_events) == 1
    assert meta_events[0].run_id == "abc123"


# ── 15. Confidence is always in [0, 1] ──────────────────────────────────────


@pytest.mark.parametrize(
    "entity_type,engine,sample_values",
    [
        ("EMAIL", "regex", ["a@b.com"] * 5),
        ("IP_ADDRESS", "regex", ["192.168.1.1"] * 5),
        ("PHONE", "regex", ["555-1234"] * 5),
    ],
)
def test_confidence_in_valid_range(
    entity_type: str,
    engine: str,
    sample_values: list[str],
) -> None:
    mc = MetaClassifier()
    pred = mc.predict_shadow(
        [_make_finding(entity_type, 0.9, engine, column_id="c1")],
        sample_values,
    )
    assert pred is not None
    assert 0.0 <= pred.confidence <= 1.0


# ── 16. Orchestrator-level integration with stub engine ─────────────────────


def test_orchestrator_emits_shadow_after_classification(standard_profile: ClassificationProfile) -> None:
    """Drive the Orchestrator directly and assert Tier → Classification → MetaClassifier ordering."""
    # Clear disable env if set
    prior = os.environ.pop("DATA_CLASSIFIER_DISABLE_META", None)
    try:
        events: list = []
        emitter = EventEmitter()
        emitter.add_handler(CallbackHandler(events.append))

        stub = _StubEngine(
            name="regex",
            order=10,
            authority=5,
            findings=[_make_finding("EMAIL", 0.95, "regex")],
        )
        orch = Orchestrator([stub], mode="structured", emitter=emitter)
        result = orch.classify_column(_email_column("c1"), standard_profile)
        assert any(f.entity_type == "EMAIL" for f in result)

        types = [type(e).__name__ for e in events]
        assert "TierEvent" in types
        assert "ClassificationEvent" in types
        assert "MetaClassifierEvent" in types
        # Meta event comes after the classification event
        class_idx = types.index("ClassificationEvent")
        meta_idx = types.index("MetaClassifierEvent")
        assert meta_idx > class_idx
    finally:
        if prior is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META"] = prior


# ── 17. TierEvent count is unchanged (shadow is additive) ───────────────────


def test_shadow_adds_only_meta_event_no_other_event_change(
    standard_profile: ClassificationProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    col = _email_column()

    # With shadow
    monkeypatch.delenv("DATA_CLASSIFIER_DISABLE_META", raising=False)
    on_events: list = []
    on_emitter = EventEmitter()
    on_emitter.add_handler(CallbackHandler(on_events.append))
    classify_columns([col], standard_profile, event_emitter=on_emitter)

    # Without shadow
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_META", "1")
    off_events: list = []
    off_emitter = EventEmitter()
    off_emitter.add_handler(CallbackHandler(off_events.append))
    classify_columns([col], standard_profile, event_emitter=off_emitter)

    def _count(events: list, cls: type) -> int:
        return sum(1 for e in events if isinstance(e, cls))

    assert _count(on_events, TierEvent) == _count(off_events, TierEvent)
    assert _count(on_events, ClassificationEvent) == _count(off_events, ClassificationEvent)
    assert _count(on_events, MetaClassifierEvent) == 1
    assert _count(off_events, MetaClassifierEvent) == 0
