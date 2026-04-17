"""Unit tests for per-value GLiNER inference (Sprint 13 Item B)."""

from __future__ import annotations

from unittest.mock import MagicMock

from data_classifier.core.types import ColumnInput, SpanDetection
from data_classifier.engines.gliner_engine import GLiNER2Engine, _load_per_value_sample_size, _stable_subsample


class TestPerValueSampleSizeConfig:
    def test_default_is_60_when_config_present(self):
        assert _load_per_value_sample_size() == 60

    def test_falls_back_to_60_when_config_missing(self, monkeypatch):
        import data_classifier.engines.gliner_engine as gm

        monkeypatch.setattr(gm, "load_engine_config", lambda: {})
        assert gm._load_per_value_sample_size() == 60

    def test_reads_override_from_config(self, monkeypatch):
        import data_classifier.engines.gliner_engine as gm

        monkeypatch.setattr(
            gm,
            "load_engine_config",
            lambda: {"gliner_engine": {"per_value_sample_size": 120}},
        )
        assert gm._load_per_value_sample_size() == 120


class TestStableSubsample:
    def test_identity_when_input_fits(self):
        values = ["a", "b", "c"]
        assert set(_stable_subsample(values, n=10)) == set(values)
        assert len(_stable_subsample(values, n=10)) == 3

    def test_cap_is_respected(self):
        values = [f"value_{i}" for i in range(100)]
        assert len(_stable_subsample(values, n=60)) == 60

    def test_deterministic_across_calls(self):
        values = [f"value_{i}" for i in range(100)]
        first = _stable_subsample(values, n=60)
        second = _stable_subsample(values, n=60)
        assert first == second

    def test_insertion_order_independent(self):
        values = [f"value_{i}" for i in range(100)]
        forward = _stable_subsample(values, n=60)
        reverse = _stable_subsample(list(reversed(values)), n=60)
        assert set(forward) == set(reverse)

    def test_empty_input(self):
        assert _stable_subsample([], n=60) == []

    def test_zero_cap(self):
        assert _stable_subsample(["a", "b"], n=0) == []


def _make_stub_engine(stub_model):
    """Construct a GLiNER2Engine whose _get_model returns the stub."""
    engine = GLiNER2Engine()
    engine._get_model = lambda: stub_model
    engine._registered = True
    return engine


class TestClassifyPerValue:
    def test_empty_column_returns_empty(self):
        engine = _make_stub_engine(MagicMock())
        column = ColumnInput(column_id="c0", column_name="logs", sample_values=[])
        spans, sampled = engine.classify_per_value(column)
        assert spans == []
        assert sampled == 0

    def test_non_text_data_type_skipped(self):
        engine = _make_stub_engine(MagicMock())
        column = ColumnInput(column_id="c0", column_name="id", sample_values=["1"], data_type="INTEGER")
        spans, sampled = engine.classify_per_value(column)
        assert spans == []
        assert sampled == 0

    def test_runs_one_inference_per_sampled_value(self):
        def _predict(text, _labels, **_kwargs):
            return [{"label": "email", "text": text[:10], "score": 0.9, "start": 0, "end": 10}]

        stub = MagicMock()
        stub.predict_entities.side_effect = _predict

        engine = _make_stub_engine(stub)
        column = ColumnInput(
            column_id="c0",
            column_name="logs",
            sample_values=[f"line_{i}_value" for i in range(5)],
        )
        spans, sampled = engine.classify_per_value(column, sample_size=3)

        assert stub.predict_entities.call_count == 3
        assert sampled == 3
        assert len(spans) == 3
        for row_spans in spans:
            assert len(row_spans) == 1
            assert row_spans[0].entity_type == "EMAIL"
            assert isinstance(row_spans[0], SpanDetection)

    def test_per_value_inference_error_is_isolated(self):
        call_count = {"n": 0}

        def _predict(text, _labels, **_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("OOM on row 2")
            return [{"label": "email", "text": "x", "score": 0.8, "start": 0, "end": 1}]

        stub = MagicMock()
        stub.predict_entities.side_effect = _predict

        engine = _make_stub_engine(stub)
        column = ColumnInput(
            column_id="c0",
            column_name="logs",
            sample_values=["row_one", "row_two", "row_three"],
        )
        spans, sampled = engine.classify_per_value(column, sample_size=3)
        assert sampled == 3
        assert len(spans) == 3
        non_empty = [rs for rs in spans if rs]
        assert len(non_empty) == 2

    def test_unknown_label_skipped(self):
        def _predict(text, _labels, **_kwargs):
            return [{"label": "unknown_label", "text": "x", "score": 0.9, "start": 0, "end": 1}]

        stub = MagicMock()
        stub.predict_entities.side_effect = _predict

        engine = _make_stub_engine(stub)
        column = ColumnInput(column_id="c0", column_name="x", sample_values=["a"])
        spans, _ = engine.classify_per_value(column, sample_size=1)
        assert spans == [[]]

    def test_default_sample_size_from_config(self, monkeypatch):
        import data_classifier.engines.gliner_engine as gm

        monkeypatch.setattr(gm, "_load_per_value_sample_size", lambda: 2)

        stub = MagicMock()
        stub.predict_entities.return_value = []

        engine = _make_stub_engine(stub)
        column = ColumnInput(column_id="c0", column_name="x", sample_values=["a", "b", "c", "d"])
        _, sampled = engine.classify_per_value(column)
        assert sampled == 2
        assert stub.predict_entities.call_count == 2
