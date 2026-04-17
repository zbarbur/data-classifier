"""Unit tests for per-value GLiNER inference (Sprint 13 Item B)."""

from __future__ import annotations

from data_classifier.engines.gliner_engine import _load_per_value_sample_size


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
