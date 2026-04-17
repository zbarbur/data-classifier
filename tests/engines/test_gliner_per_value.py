"""Unit tests for per-value GLiNER inference (Sprint 13 Item B)."""

from __future__ import annotations

from data_classifier.engines.gliner_engine import _load_per_value_sample_size, _stable_subsample


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
