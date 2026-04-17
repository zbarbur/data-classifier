"""Tests for Sprint 14 — meta-classifier directive flip on structured_single.

Covers:
  1. Structured_single columns use meta-classifier prediction as live output
  2. Non-structured columns still use cascade (shadow only)
  3. The disable flag (meta_classifier_directive=False) reverts to shadow-only
  4. MetaClassifierEvent.directive field reflects directive vs shadow mode
  5. Agreement case: when meta-classifier agrees with cascade, no change
  6. Promotion case: existing cascade finding for predicted entity_type is promoted
  7. New finding case: meta-classifier predicts entity_type absent from cascade
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from data_classifier import ColumnInput, classify_columns, load_profile
from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    SampleAnalysis,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import MetaClassifierEvent
from data_classifier.orchestrator.meta_classifier import (
    MetaClassifier,
    MetaClassifierPrediction,
)
from data_classifier.orchestrator.orchestrator import Orchestrator

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_finding(
    entity_type: str,
    confidence: float,
    engine: str,
    *,
    category: str = "PII",
    sensitivity: str = "HIGH",
    column_id: str = "test:col",
    sample_analysis: SampleAnalysis | None = None,
) -> ClassificationFinding:
    return ClassificationFinding(
        column_id=column_id,
        entity_type=entity_type,
        category=category,
        sensitivity=sensitivity,
        confidence=confidence,
        regulatory=[],
        engine=engine,
        evidence=f"Stub {engine}: {entity_type}",
        sample_analysis=sample_analysis,
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
    """Keep GLiNER2 out of directive tests — it's slow and not relevant here."""
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_ML", "1")


@pytest.fixture
def capture_events() -> tuple[EventEmitter, list]:
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(lambda ev: events.append(ev)))
    return emitter, events


# ── 1. Structured_single uses meta-classifier directive ────────────────────


def test_directive_replaces_cascade_on_structured_single(
    standard_profile: ClassificationProfile,
) -> None:
    """On structured_single, meta-classifier prediction becomes the live output."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    col = ColumnInput(
        column_id="col_email",
        column_name="user_email",
        sample_values=["alice@example.com", "bob@example.org", "carol@test.io"] * 4,
    )

    # Clear env to ensure meta is enabled
    prior_meta = os.environ.pop("DATA_CLASSIFIER_DISABLE_META", None)
    prior_directive = os.environ.pop("DATA_CLASSIFIER_DISABLE_META_DIRECTIVE", None)
    try:
        result = classify_columns([col], standard_profile, event_emitter=emitter)
        meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
        assert len(meta_events) == 1
        ev = meta_events[0]

        # For an email column, meta-classifier should agree with cascade
        # so directive_applied will be False (agreement = no replacement needed)
        # but the directive field reflects that the system was in directive mode
        if ev.agreement:
            # When agreement, directive is not applied (no change needed)
            assert ev.directive is False
            # Result should still have EMAIL as top finding
            assert any(f.entity_type == "EMAIL" for f in result)
        else:
            # When disagreement, directive IS applied
            assert ev.directive is True
            top = max(result, key=lambda f: f.confidence)
            assert top.entity_type == ev.predicted_entity
    finally:
        if prior_meta is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META"] = prior_meta
        if prior_directive is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META_DIRECTIVE"] = prior_directive


# ── 2. Non-structured columns still use cascade (shadow only) ──────────────


def test_non_structured_columns_use_shadow_only(
    standard_profile: ClassificationProfile,
) -> None:
    """Heterogeneous columns must not get directive — shadow only."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    log_line = "2026-04-16T10:15:30 INFO user alice@example.com login from 10.0.1.5"
    col = ColumnInput(
        column_id="col_log",
        column_name="log_line",
        sample_values=[log_line] * 10,
    )

    prior = os.environ.pop("DATA_CLASSIFIER_DISABLE_META", None)
    try:
        classify_columns([col], standard_profile, event_emitter=emitter)
        meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
        # Heterogeneous columns should not emit meta events at all (Sprint 13)
        assert len(meta_events) == 0
    finally:
        if prior is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META"] = prior


# ── 3. Disable flag reverts to shadow-only ─────────────────────────────────


def test_disable_directive_flag_reverts_to_shadow(
    standard_profile: ClassificationProfile,
) -> None:
    """meta_classifier_directive=False keeps shadow-only behavior."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    stub = _StubEngine(
        name="regex",
        order=10,
        authority=5,
        findings=[_make_finding("EMAIL", 0.95, "regex")],
    )

    prior = os.environ.pop("DATA_CLASSIFIER_DISABLE_META", None)
    try:
        orch = Orchestrator(
            [stub],
            mode="structured",
            emitter=emitter,
            meta_classifier_directive=False,
        )
        result = orch.classify_column(
            ColumnInput(
                column_id="col_email",
                column_name="email",
                sample_values=["alice@ex.com", "bob@ex.org"] * 5,
            ),
            standard_profile,
        )
        meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
        assert len(meta_events) == 1
        # Directive should never be True when disabled
        assert meta_events[0].directive is False
        # Result should be from cascade, not meta-classifier
        assert all(f.engine != "meta_classifier" for f in result)
    finally:
        if prior is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META"] = prior


def test_disable_directive_via_env_var(
    standard_profile: ClassificationProfile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DATA_CLASSIFIER_DISABLE_META_DIRECTIVE=1 disables directive."""
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_META_DIRECTIVE", "1")
    monkeypatch.delenv("DATA_CLASSIFIER_DISABLE_META", raising=False)

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
    orch.classify_column(
        ColumnInput(
            column_id="col_email",
            column_name="email",
            sample_values=["alice@ex.com"] * 5,
        ),
        standard_profile,
    )
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert len(meta_events) == 1
    assert meta_events[0].directive is False


# ── 4. MetaClassifierEvent.directive field ─────────────────────────────────


def test_meta_event_directive_field_when_applied(
    standard_profile: ClassificationProfile,
) -> None:
    """When meta-classifier disagrees with cascade and applies directive,
    the event must have directive=True."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    # Cascade says SSN with low confidence, mock meta-classifier to predict CREDIT_CARD
    stub = _StubEngine(
        name="regex",
        order=10,
        authority=5,
        findings=[
            _make_finding("SSN", 0.65, "regex", category="PII"),
        ],
    )

    mc = MetaClassifier()

    def _mock_predict(findings, sample_values=None, *, engine_findings=None):
        return MetaClassifierPrediction(
            column_id="col_ssn",
            predicted_entity="CREDIT_CARD",
            confidence=0.95,
            live_entity="SSN",
            agreement=False,
        )

    prior = os.environ.pop("DATA_CLASSIFIER_DISABLE_META", None)
    try:
        orch = Orchestrator(
            [stub],
            mode="structured",
            emitter=emitter,
            meta_classifier_directive=True,
        )
        orch._meta_classifier = mc
        with mock.patch.object(mc, "predict_shadow", side_effect=_mock_predict):
            result = orch.classify_column(
                ColumnInput(
                    column_id="col_ssn",
                    column_name="ssn_number",
                    sample_values=["123-45-6789"] * 5,
                ),
                standard_profile,
            )

        meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
        assert len(meta_events) == 1
        assert meta_events[0].directive is True
        assert meta_events[0].predicted_entity == "CREDIT_CARD"

        # Top finding should be CREDIT_CARD from meta_classifier
        top = max(result, key=lambda f: f.confidence)
        assert top.entity_type == "CREDIT_CARD"
        assert top.engine == "meta_classifier"

        # SSN finding should still be present as supporting evidence
        assert any(f.entity_type == "SSN" for f in result)
    finally:
        if prior is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META"] = prior


# ── 5. Agreement case: no change to result ─────────────────────────────────


def test_directive_agreement_no_change(
    standard_profile: ClassificationProfile,
) -> None:
    """When meta-classifier agrees with cascade, result is unchanged."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    stub = _StubEngine(
        name="regex",
        order=10,
        authority=5,
        findings=[_make_finding("EMAIL", 0.95, "regex")],
    )

    mc = MetaClassifier()

    def _mock_predict(findings, sample_values=None, *, engine_findings=None):
        return MetaClassifierPrediction(
            column_id="col_email",
            predicted_entity="EMAIL",
            confidence=0.97,
            live_entity="EMAIL",
            agreement=True,
        )

    prior = os.environ.pop("DATA_CLASSIFIER_DISABLE_META", None)
    try:
        orch = Orchestrator(
            [stub],
            mode="structured",
            emitter=emitter,
            meta_classifier_directive=True,
        )
        orch._meta_classifier = mc
        with mock.patch.object(mc, "predict_shadow", side_effect=_mock_predict):
            result = orch.classify_column(
                ColumnInput(
                    column_id="col_email",
                    column_name="email",
                    sample_values=["alice@ex.com"] * 5,
                ),
                standard_profile,
            )

        # Result should be from cascade (no meta_classifier engine)
        assert all(f.engine != "meta_classifier" for f in result)
        top = max(result, key=lambda f: f.confidence)
        assert top.entity_type == "EMAIL"

        meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
        assert len(meta_events) == 1
        assert meta_events[0].directive is False  # Agreement = no directive applied
    finally:
        if prior is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META"] = prior


# ── 6. Promotion case: existing finding promoted ──────────────────────────


def test_directive_promotes_existing_cascade_finding(
    standard_profile: ClassificationProfile,
) -> None:
    """When meta-classifier predicts an entity_type already in cascade,
    that finding is promoted to top.

    Uses a single-entity cascade (SSN) so the shape detector routes to
    structured_single (n_cascade_entities=1), then patches the meta-classifier
    to predict a different entity. The _apply_meta_directive method is tested
    directly here to verify the promotion logic independently of shape routing.
    """
    # Test the static method directly to avoid shape-routing complications
    cascade_result = [
        _make_finding("SSN", 0.70, "regex", category="PII", column_id="col_x"),
        _make_finding("CREDIT_CARD", 0.60, "regex", category="Financial", column_id="col_x"),
    ]
    prediction = MetaClassifierPrediction(
        column_id="col_x",
        predicted_entity="CREDIT_CARD",
        confidence=0.95,
        live_entity="SSN",
        agreement=False,
    )
    col = ColumnInput(column_id="col_x", column_name="card_num", sample_values=["4111111111111111"] * 5)

    result = Orchestrator._apply_meta_directive(prediction, cascade_result, col, standard_profile)
    assert result is not None

    # CREDIT_CARD should now be top
    top = max(result, key=lambda f: f.confidence)
    assert top.entity_type == "CREDIT_CARD"
    assert top.engine == "meta_classifier"
    assert top.confidence > 0.70  # Promoted above SSN's 0.70

    # SSN should still be present
    ssn_findings = [f for f in result if f.entity_type == "SSN"]
    assert len(ssn_findings) == 1


# ── 7. New finding case: entity absent from cascade ────────────────────────


def test_directive_creates_new_finding_from_profile(
    standard_profile: ClassificationProfile,
) -> None:
    """When meta-classifier predicts an entity_type not in cascade,
    a new finding is constructed from profile metadata."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    stub = _StubEngine(
        name="regex",
        order=10,
        authority=5,
        findings=[_make_finding("SSN", 0.65, "regex", category="PII")],
    )

    mc = MetaClassifier()

    def _mock_predict(findings, sample_values=None, *, engine_findings=None):
        return MetaClassifierPrediction(
            column_id="col_x",
            predicted_entity="EMAIL",
            confidence=0.92,
            live_entity="SSN",
            agreement=False,
        )

    prior = os.environ.pop("DATA_CLASSIFIER_DISABLE_META", None)
    try:
        orch = Orchestrator(
            [stub],
            mode="structured",
            emitter=emitter,
            meta_classifier_directive=True,
        )
        orch._meta_classifier = mc
        with mock.patch.object(mc, "predict_shadow", side_effect=_mock_predict):
            result = orch.classify_column(
                ColumnInput(
                    column_id="col_x",
                    column_name="contact",
                    sample_values=["test@example.com"] * 5,
                ),
                standard_profile,
            )

        # EMAIL should be the top finding, from meta_classifier
        top = max(result, key=lambda f: f.confidence)
        assert top.entity_type == "EMAIL"
        assert top.engine == "meta_classifier"
        assert top.category == "PII"  # From profile

        # SSN cascade finding preserved
        assert any(f.entity_type == "SSN" for f in result)
    finally:
        if prior is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META"] = prior


# ── 8. NEGATIVE prediction does not apply directive ────────────────────────


def test_directive_skips_negative_prediction(
    standard_profile: ClassificationProfile,
) -> None:
    """NEGATIVE predictions should not override cascade findings."""
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    stub = _StubEngine(
        name="regex",
        order=10,
        authority=5,
        findings=[_make_finding("SSN", 0.90, "regex")],
    )

    mc = MetaClassifier()

    def _mock_predict(findings, sample_values=None, *, engine_findings=None):
        return MetaClassifierPrediction(
            column_id="col_x",
            predicted_entity="NEGATIVE",
            confidence=0.95,
            live_entity="SSN",
            agreement=False,
        )

    prior = os.environ.pop("DATA_CLASSIFIER_DISABLE_META", None)
    try:
        orch = Orchestrator(
            [stub],
            mode="structured",
            emitter=emitter,
            meta_classifier_directive=True,
        )
        orch._meta_classifier = mc
        with mock.patch.object(mc, "predict_shadow", side_effect=_mock_predict):
            result = orch.classify_column(
                ColumnInput(
                    column_id="col_x",
                    column_name="ssn",
                    sample_values=["123-45-6789"] * 5,
                ),
                standard_profile,
            )

        # SSN should remain as top finding
        top = max(result, key=lambda f: f.confidence)
        assert top.entity_type == "SSN"

        meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
        assert len(meta_events) == 1
        assert meta_events[0].directive is False  # NEGATIVE = no directive
    finally:
        if prior is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META"] = prior


# ── 9. Directive default is enabled ────────────────────────────────────────


def test_directive_enabled_by_default() -> None:
    """Orchestrator should have directive enabled by default."""
    prior = os.environ.pop("DATA_CLASSIFIER_DISABLE_META_DIRECTIVE", None)
    try:
        stub = _StubEngine(
            name="regex",
            order=10,
            authority=5,
            findings=[],
        )
        orch = Orchestrator([stub], mode="structured")
        assert orch._meta_directive is True
    finally:
        if prior is not None:
            os.environ["DATA_CLASSIFIER_DISABLE_META_DIRECTIVE"] = prior


# ── 10. Integration test with real engines ─────────────────────────────────


def test_directive_integration_email_column(
    standard_profile: ClassificationProfile,
) -> None:
    """Full integration: email column with real engines, directive enabled."""
    from data_classifier.engines.column_name_engine import ColumnNameEngine
    from data_classifier.engines.heuristic_engine import HeuristicEngine
    from data_classifier.engines.regex_engine import RegexEngine
    from data_classifier.engines.secret_scanner import SecretScannerEngine

    if os.environ.get("DATA_CLASSIFIER_DISABLE_META", "").lower() in ("1", "true", "yes"):
        pytest.skip("Meta-classifier disabled")

    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))

    engines = [RegexEngine(), ColumnNameEngine(), HeuristicEngine(), SecretScannerEngine()]
    for e in engines:
        e.startup()
    orch = Orchestrator(engines, mode="structured", emitter=emitter, meta_classifier_directive=True)

    col = ColumnInput(
        column_id="col_email",
        column_name="user_email",
        sample_values=["alice@example.com", "bob@example.org", "carol@test.io"] * 4,
    )
    result = orch.classify_column(col, standard_profile)

    # Should have EMAIL in the result
    assert any(f.entity_type == "EMAIL" for f in result)

    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert len(meta_events) == 1
    # Email column: cascade and meta-classifier should agree
    # so directive=False (agreement case)
    ev = meta_events[0]
    assert isinstance(ev.directive, bool)
