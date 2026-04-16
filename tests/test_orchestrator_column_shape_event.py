import os

import pytest

from data_classifier import load_profile
from data_classifier.core.types import ColumnInput
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from data_classifier.events.types import ColumnShapeEvent, MetaClassifierEvent
from data_classifier.orchestrator.orchestrator import Orchestrator


def _collect_events() -> tuple[EventEmitter, list]:
    events: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(events.append))
    return emitter, events


def _orchestrator(emitter: EventEmitter) -> Orchestrator:
    engines = [
        RegexEngine(),
        ColumnNameEngine(),
        HeuristicEngine(),
        SecretScannerEngine(),
    ]
    for e in engines:
        e.startup()
    return Orchestrator(engines, mode="structured", emitter=emitter)


def test_column_shape_event_emitted_for_structured_single():
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    column = ColumnInput(
        column_id="col_email",
        column_name="email",
        sample_values=["alice@ex.com", "bob@ex.org", "carol@test.io"] * 4,
    )
    orch.classify_column(column, load_profile("standard"))
    shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
    assert len(shape_events) == 1
    assert shape_events[0].shape == "structured_single"
    assert shape_events[0].per_value_inference_ms is None
    assert shape_events[0].sampled_row_count is None


def test_column_shape_event_emitted_for_heterogeneous():
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    log_line = "2026-04-16T10:15:30 INFO user alice@example.com login from 10.0.1.5"
    column = ColumnInput(
        column_id="col_log",
        column_name="log_line",
        sample_values=[log_line] * 10,
    )
    orch.classify_column(column, load_profile("standard"))
    shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
    assert len(shape_events) == 1
    assert shape_events[0].shape == "free_text_heterogeneous"


def test_column_shape_event_emitted_for_opaque():
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    column = ColumnInput(
        column_id="col_jwt",
        column_name="token",
        sample_values=[
            "eyJ1c2VyIjoiYWxpY2VAZXhhbXBsZS5jb20iLCJyb2xlIjoiYWRtaW4ifQ==",
        ]
        * 10,
    )
    orch.classify_column(column, load_profile("standard"))
    shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
    assert len(shape_events) == 1
    assert shape_events[0].shape == "opaque_tokens"


def test_meta_classifier_shadow_suppressed_on_heterogeneous():
    """Item A AC: heterogeneous columns should no longer be routed to v5 shadow."""
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    log_line = "2026-04-16T10:15:30 INFO user alice@example.com login from 10.0.1.5"
    column = ColumnInput(
        column_id="col_log",
        column_name="log_line",
        sample_values=[log_line] * 10,
    )
    orch.classify_column(column, load_profile("standard"))
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert len(meta_events) == 0, (
        "v5 meta-classifier shadow must not be emitted on free_text_heterogeneous columns (Sprint 13 Item A AC)."
    )


def test_meta_classifier_shadow_emitted_on_structured_single():
    """Structured single columns preserve Sprint 11 behavior — shadow still fires."""
    if os.environ.get("DATA_CLASSIFIER_DISABLE_META", "").lower() in ("1", "true", "yes"):
        pytest.skip("Meta-classifier disabled in CI matrix")
    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    column = ColumnInput(
        column_id="col_email",
        column_name="email",
        sample_values=["alice@ex.com", "bob@ex.org"] * 5,
    )
    orch.classify_column(column, load_profile("standard"))
    meta_events = [e for e in events if isinstance(e, MetaClassifierEvent)]
    assert len(meta_events) == 1


def test_shape_detection_failure_degrades_gracefully(monkeypatch):
    """Defensive guard: if detect_column_shape raises, orchestrator returns a
    valid classification result without emitting ColumnShapeEvent. Preserves
    Sprint 11 behavior as the safe fallback.
    """

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated shape detection failure")

    # Patch the detect_column_shape imported into the orchestrator module,
    # not the one in shape_detector (the orchestrator imports a bound name).
    monkeypatch.setattr(
        "data_classifier.orchestrator.orchestrator.detect_column_shape",
        _boom,
    )

    emitter, events = _collect_events()
    orch = _orchestrator(emitter)
    column = ColumnInput(
        column_id="col_email",
        column_name="email",
        sample_values=["alice@ex.com", "bob@ex.org"] * 5,
    )
    result = orch.classify_column(column, load_profile("standard"))

    # Classification itself must still succeed
    assert isinstance(result, list)
    # ColumnShapeEvent must NOT be emitted (shape_detection is None)
    shape_events = [e for e in events if isinstance(e, ColumnShapeEvent)]
    assert len(shape_events) == 0
