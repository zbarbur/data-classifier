"""End-to-end tests for Sprint 13 Item B free_text_heterogeneous branch."""

from __future__ import annotations

import pytest

from data_classifier import load_profile
from data_classifier.core.types import ColumnInput, SpanDetection
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.gliner_engine import GLiNER2Engine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import ColumnShapeEvent
from data_classifier.orchestrator.orchestrator import Orchestrator

PROFILE = load_profile("standard")


def _collect_events():
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))
    return emitter, events


def _orchestrator_with_gliner(emitter):
    engines = [
        RegexEngine(),
        ColumnNameEngine(),
        HeuristicEngine(),
        SecretScannerEngine(),
        GLiNER2Engine(),
    ]
    for e in engines:
        e.startup()
    return Orchestrator(engines, mode="structured", emitter=emitter)


def _heterogeneous_column():
    return ColumnInput(
        column_id="logs_column",
        column_name="event_log",
        sample_values=[f"user alice@example.com accessed resource from IP 10.0.0.{i} at 10:{i:02d}" for i in range(50)],
    )


def _structured_column():
    return ColumnInput(
        column_id="email_col",
        column_name="email",
        sample_values=[f"user{i}@example.com" for i in range(50)],
    )


def _install_stub_gliner(orchestrator, per_value_output):
    for engine in orchestrator.engines:
        if engine.name == "gliner2":
            engine.classify_per_value = lambda column, sample_size=None: (
                per_value_output,
                len(per_value_output),
            )
            return
    pytest.fail("No gliner2 engine found")


class TestHeterogeneousBranchIntegration:
    def test_per_value_findings_unioned_with_cascade(self):
        emitter, events = _collect_events()
        orchestrator = _orchestrator_with_gliner(emitter)
        org_spans = [
            [SpanDetection(text="ExampleCo", entity_type="ORGANIZATION", confidence=0.85, start=0, end=9)]
            for _ in range(40)
        ] + [[] for _ in range(10)]
        _install_stub_gliner(orchestrator, org_spans)

        result = orchestrator.classify_column(_heterogeneous_column(), PROFILE)
        types = {f.entity_type for f in result}
        assert "EMAIL" in types, "Cascade regex floor preserved"
        assert "IP_ADDRESS" in types, "Cascade regex floor preserved"
        assert "ORGANIZATION" in types, "GLiNER-only lift added"

    def test_duplicate_entity_type_keeps_higher_confidence(self):
        emitter, events = _collect_events()
        orchestrator = _orchestrator_with_gliner(emitter)
        low_conf_email = [
            [SpanDetection(text="x", entity_type="EMAIL", confidence=0.72, start=0, end=1)] for _ in range(50)
        ]
        _install_stub_gliner(orchestrator, low_conf_email)

        result = orchestrator.classify_column(_heterogeneous_column(), PROFILE)
        emails = [f for f in result if f.entity_type == "EMAIL"]
        assert len(emails) == 1
        assert emails[0].confidence >= 0.9, "Cascade's higher-confidence EMAIL should win"

    def test_gliner_failure_falls_back_to_cascade_cleanly(self):
        emitter, events = _collect_events()
        orchestrator = _orchestrator_with_gliner(emitter)
        for engine in orchestrator.engines:
            if engine.name == "gliner2":

                def _boom(column, sample_size=None):
                    raise RuntimeError("model load failed")

                engine.classify_per_value = _boom
                break

        result = orchestrator.classify_column(_heterogeneous_column(), PROFILE)
        types = {f.entity_type for f in result}
        assert "EMAIL" in types, "Cascade output preserved on GLiNER failure"

    def test_column_shape_event_populated_with_latency(self):
        emitter, events = _collect_events()
        orchestrator = _orchestrator_with_gliner(emitter)
        org_spans = [
            [SpanDetection(text="X", entity_type="ORGANIZATION", confidence=0.8, start=0, end=1)] for _ in range(50)
        ]
        _install_stub_gliner(orchestrator, org_spans)

        orchestrator.classify_column(_heterogeneous_column(), PROFILE)
        shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
        assert len(shape_events) == 1
        assert shape_events[0].shape == "free_text_heterogeneous"
        assert shape_events[0].per_value_inference_ms is not None
        assert shape_events[0].per_value_inference_ms >= 0
        assert shape_events[0].sampled_row_count == 50

    def test_structured_branch_untouched(self):
        emitter, events = _collect_events()
        orchestrator = _orchestrator_with_gliner(emitter)
        call_count = {"n": 0}
        for engine in orchestrator.engines:
            if engine.name == "gliner2":
                original_cpv = getattr(engine, "classify_per_value", None)

                def _tracked(column, sample_size=None, _orig=original_cpv):
                    call_count["n"] += 1
                    if _orig is not None:
                        return _orig(column, sample_size=sample_size)
                    return [], 0

                engine.classify_per_value = _tracked

        orchestrator.classify_column(_structured_column(), PROFILE)
        assert call_count["n"] == 0, "structured_single must not invoke per-value"
        shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
        if shape_events:
            assert shape_events[0].per_value_inference_ms is None
            assert shape_events[0].sampled_row_count is None
