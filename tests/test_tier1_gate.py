"""Tests for the Sprint 11 Phase 9 tier-1 credential pattern-hit gate.

The gate is wired into :meth:`Orchestrator.classify_column` as an
observability-only path that emits a :class:`GateRoutingEvent` whenever
a column carries credential signal. These tests cover the pure
``_evaluate_tier1_gate`` helper under every branch of its decision
logic, plus a lightweight integration smoke test that drives the
orchestrator with a stub engine setup and asserts the gate event
lands on the emitter.
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
    SampleAnalysis,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import GateRoutingEvent
from data_classifier.orchestrator.orchestrator import (
    Orchestrator,
    _evaluate_tier1_gate,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _finding(
    *,
    engine: str,
    entity_type: str,
    confidence: float,
    category: str = "Credential",
    match_ratio: float | None = None,
    column_id: str = "col_test",
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
        column_id=column_id,
        entity_type=entity_type,
        category=category,
        sensitivity="HIGH",
        confidence=confidence,
        regulatory=[],
        engine=engine,
        sample_analysis=sample_analysis,
    )


# ── Pure gate evaluator tests ───────────────────────────────────────────────


class TestEvaluateTier1Gate:
    def test_empty_findings_returns_none(self):
        # No findings → no credential signal → evaluator returns None so
        # the orchestrator does not emit a gate event on uninteresting
        # columns (keeps telemetry volume bounded).
        assert _evaluate_tier1_gate([], {}) is None

    def test_pii_only_column_returns_none(self):
        # A pure-PII column must not produce a gate event — the gate
        # is strictly about tier-1 credential coverage.
        f = _finding(
            engine="regex",
            entity_type="EMAIL",
            confidence=0.95,
            category="PII",
            match_ratio=0.9,
        )
        assert _evaluate_tier1_gate([f], {"regex": [f]}) is None

    def test_regex_path_fires_when_confidence_and_ratio_high(self):
        # Condition (a): primary is credential, regex confidence ≥ 0.85,
        # regex match_ratio ≥ 0.30 → gate fires with reason "regex+ratio".
        f = _finding(
            engine="regex",
            entity_type="STRIPE_SECRET_KEY",
            confidence=0.95,
            match_ratio=0.80,
        )
        decision = _evaluate_tier1_gate([f], {"regex": [f]})
        assert decision is not None
        assert decision.gate_fired is True
        assert decision.gate_reason == "regex+ratio"
        assert decision.primary_is_credential is True
        assert decision.regex_confidence == 0.95
        assert decision.regex_match_ratio == 0.80
        assert decision.secret_scanner_confidence == 0.0

    def test_regex_path_does_not_fire_when_confidence_low(self):
        # Primary is credential but regex confidence below threshold →
        # gate does not fire; reason explains which threshold missed.
        f = _finding(
            engine="regex",
            entity_type="GENERIC_API_KEY",
            confidence=0.70,
            match_ratio=0.80,
        )
        decision = _evaluate_tier1_gate([f], {"regex": [f]})
        assert decision is not None
        assert decision.gate_fired is False
        assert decision.gate_reason == "regex_confidence_low"

    def test_regex_path_does_not_fire_when_match_ratio_low(self):
        # Confidence high but sparse match_ratio → suggests prefix
        # collision or one-off hit; gate withholds firing.
        f = _finding(
            engine="regex",
            entity_type="STRIPE_SECRET_KEY",
            confidence=0.95,
            match_ratio=0.10,
        )
        decision = _evaluate_tier1_gate([f], {"regex": [f]})
        assert decision is not None
        assert decision.gate_fired is False
        assert decision.gate_reason == "regex_match_ratio_low"

    def test_secret_scanner_path_fires_at_threshold(self):
        # Condition (b): secret scanner alone with confidence ≥ 0.50.
        # Primary is still a credential (the scanner finding) but
        # reason points at the secret-scanner path for observability.
        f = _finding(
            engine="secret_scanner",
            entity_type="OPAQUE_SECRET",
            confidence=0.50,
        )
        decision = _evaluate_tier1_gate([f], {"secret_scanner": [f]})
        assert decision is not None
        assert decision.gate_fired is True
        assert decision.gate_reason == "secret_scanner"
        assert decision.secret_scanner_confidence == 0.50

    def test_both_paths_fire_uses_combined_reason(self):
        # When regex AND secret scanner both qualify, the reason is
        # tagged as combined so downstream can distinguish
        # "corroborated" columns from single-source fires.
        regex_f = _finding(
            engine="regex",
            entity_type="STRIPE_SECRET_KEY",
            confidence=0.95,
            match_ratio=0.60,
        )
        secret_f = _finding(
            engine="secret_scanner",
            entity_type="STRIPE_SECRET_KEY",
            confidence=0.90,
        )
        result = [regex_f, secret_f]
        engine_findings = {"regex": [regex_f], "secret_scanner": [secret_f]}
        decision = _evaluate_tier1_gate(result, engine_findings)
        assert decision is not None
        assert decision.gate_fired is True
        assert decision.gate_reason == "regex+ratio+secret_scanner"

    def test_regex_top_confidence_wins_over_lower_regex_hits(self):
        # Multiple regex findings — gate sees the max-confidence one
        # for both confidence and match_ratio (mirrors feature
        # extraction in meta_classifier.extract_features).
        top = _finding(
            engine="regex",
            entity_type="STRIPE_SECRET_KEY",
            confidence=0.95,
            match_ratio=0.70,
        )
        weak = _finding(
            engine="regex",
            entity_type="GENERIC_API_KEY",
            confidence=0.60,
            match_ratio=0.10,
        )
        decision = _evaluate_tier1_gate([top], {"regex": [top, weak]})
        assert decision is not None
        assert decision.gate_fired is True
        assert decision.regex_confidence == 0.95
        assert decision.regex_match_ratio == 0.70

    def test_regex_match_ratio_defaults_to_zero_without_sample_analysis(self):
        # If a regex finding somehow arrives without sample_analysis,
        # the evaluator treats match_ratio as 0.0 and the gate will
        # not fire on the regex path — safer than assuming high
        # prevalence.
        f = _finding(
            engine="regex",
            entity_type="STRIPE_SECRET_KEY",
            confidence=0.95,
            match_ratio=None,
        )
        decision = _evaluate_tier1_gate([f], {"regex": [f]})
        assert decision is not None
        assert decision.gate_fired is False
        assert decision.regex_match_ratio == 0.0
        assert decision.gate_reason == "regex_match_ratio_low"


# ── Orchestrator integration smoke test ─────────────────────────────────────


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


@pytest.fixture(autouse=True)
def _disable_ml_and_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the meta-classifier and GLiNER2 out of the orchestrator — we
    # only want to exercise the gate wiring here.
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_ML", "1")
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_META", "1")


@pytest.fixture
def profile() -> ClassificationProfile:
    from data_classifier import load_profile

    return load_profile("standard")


def _capture_emitter() -> tuple[EventEmitter, list]:
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(lambda ev: events.append(ev)))
    return emitter, events


def test_orchestrator_emits_gate_event_on_credential_column(
    profile: ClassificationProfile,
) -> None:
    # A regex engine that finds a strong Stripe key → the gate should
    # fire and emit a GateRoutingEvent with the "regex+ratio" reason.
    regex_hit = _finding(
        engine="regex",
        entity_type="STRIPE_SECRET_KEY",
        confidence=0.95,
        match_ratio=0.80,
    )
    emitter, events = _capture_emitter()
    orchestrator = Orchestrator(
        engines=[_StubEngine("regex", order=1, authority=5, findings=[regex_hit])],
        mode="structured",
        emitter=emitter,
    )
    column = ColumnInput(
        column_id="col_key",
        column_name="api_key",
        sample_values=["sk_test_" + "a" * 24] * 5,
    )

    orchestrator.classify_column(column, profile=profile)

    gate_events = [e for e in events if isinstance(e, GateRoutingEvent)]
    assert len(gate_events) == 1
    evt = gate_events[0]
    assert evt.column_id == "col_key"
    assert evt.gate_fired is True
    assert evt.gate_reason == "regex+ratio"
    assert evt.primary_is_credential is True
    assert evt.regex_confidence == 0.95
    assert evt.regex_match_ratio == 0.80


def test_orchestrator_skips_gate_event_on_pure_pii_column(
    profile: ClassificationProfile,
) -> None:
    # An EMAIL (PII) column must not emit a GateRoutingEvent — the
    # gate is applicability-guarded to credential-signal columns so
    # telemetry volume stays bounded.
    email_hit = _finding(
        engine="regex",
        entity_type="EMAIL",
        confidence=0.95,
        category="PII",
        match_ratio=0.90,
    )
    emitter, events = _capture_emitter()
    orchestrator = Orchestrator(
        engines=[_StubEngine("regex", order=1, authority=5, findings=[email_hit])],
        mode="structured",
        emitter=emitter,
    )
    column = ColumnInput(
        column_id="col_email",
        column_name="user_email",
        sample_values=["alice@example.com"] * 5,
    )

    orchestrator.classify_column(column, profile=profile)

    assert not [e for e in events if isinstance(e, GateRoutingEvent)]


def test_gate_event_does_not_mutate_result(
    profile: ClassificationProfile,
) -> None:
    # The tier-1 gate is observability-only in Sprint 11 — firing it
    # must not add, remove, or mutate findings.
    regex_hit = _finding(
        engine="regex",
        entity_type="STRIPE_SECRET_KEY",
        confidence=0.95,
        match_ratio=0.80,
    )
    orchestrator = Orchestrator(
        engines=[_StubEngine("regex", order=1, authority=5, findings=[regex_hit])],
        mode="structured",
    )
    column = ColumnInput(
        column_id="col_key",
        column_name="api_key",
        sample_values=["sk_test_" + "a" * 24] * 5,
    )

    result = orchestrator.classify_column(column, profile=profile)
    # Exactly one finding, unchanged from the engine's output.
    assert len(result) == 1
    assert result[0].entity_type == "STRIPE_SECRET_KEY"
    assert result[0].confidence == 0.95
