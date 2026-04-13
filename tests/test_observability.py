"""Tests for public observability helpers.

Covers the three Sprint 9 observability gap fixes:

1. ``get_active_engines()`` — introspect which engines loaded into the cascade
2. ``health_check()`` — canned startup probe with structured result dict
3. Loud ``ImportError`` fallback — silent GLiNER absence now logs ``WARNING``
"""

from __future__ import annotations

import importlib
import logging
import sys
from unittest.mock import patch

import data_classifier
from data_classifier import (
    ClassificationProfile,
    get_active_engines,
    health_check,
    load_profile,
)

# ── get_active_engines ──────────────────────────────────────────────────────


def test_get_active_engines_returns_4_or_more_in_default_install():
    """Default install should expose at least the 4 core engines (regex,
    column_name, heuristic_stats, secret_scanner). If ``[ml]`` extras are
    present, GLiNER2 brings the total to 5 — either is acceptable here."""
    engines = get_active_engines()
    assert isinstance(engines, list)
    assert len(engines) >= 4
    names = [e["name"] for e in engines]
    for required in ("column_name", "regex", "heuristic_stats", "secret_scanner"):
        assert required in names, f"missing required engine {required!r} in {names}"
    # Structural contract on each dict entry
    for entry in engines:
        assert set(entry.keys()) == {"name", "order", "class"}
        assert isinstance(entry["name"], str) and entry["name"]
        assert isinstance(entry["order"], int)
        assert isinstance(entry["class"], str) and entry["class"]


def _snapshot_dc_modules() -> dict:
    """Snapshot every data_classifier.* module currently in sys.modules.

    Used by reload-based tests so they can restore the original module
    objects verbatim on teardown — otherwise a re-import produces new class
    objects and downstream tests see ``isinstance`` mismatches against the
    originally-bound symbols at the top of this test module.
    """
    return {
        name: mod
        for name, mod in sys.modules.items()
        if name == "data_classifier" or name.startswith("data_classifier.")
    }


def _restore_dc_modules(snapshot: dict) -> None:
    current = [n for n in list(sys.modules) if n == "data_classifier" or n.startswith("data_classifier.")]
    for name in current:
        if name not in snapshot:
            del sys.modules[name]
    for name, mod in snapshot.items():
        sys.modules[name] = mod


def test_get_active_engines_excludes_gliner2_when_disable_ml_set(monkeypatch):
    """When DATA_CLASSIFIER_DISABLE_ML=1 and the module is reimported, the
    GLiNER2 engine must not appear in the cascade."""
    snapshot = _snapshot_dc_modules()
    monkeypatch.setenv("DATA_CLASSIFIER_DISABLE_ML", "1")
    # Drop cached modules so _build_default_engines re-runs under the env var.
    for mod in list(snapshot):
        del sys.modules[mod]
    try:
        reloaded = importlib.import_module("data_classifier")
        engines = reloaded.get_active_engines()
        names = [e["name"] for e in engines]
        assert "gliner2" not in names, f"gliner2 should be disabled, got {names}"
        # Core engines still present
        for required in ("column_name", "regex", "heuristic_stats", "secret_scanner"):
            assert required in names
    finally:
        _restore_dc_modules(snapshot)


# ── health_check ────────────────────────────────────────────────────────────


def test_health_check_returns_healthy_true_on_default_profile():
    result = health_check()
    assert isinstance(result, dict)
    assert result["healthy"] is True
    assert result["error"] is None
    assert isinstance(result["latency_ms"], float)
    assert result["latency_ms"] >= 0.0
    assert isinstance(result["engines_executed"], list)
    assert isinstance(result["engines_skipped"], list)
    assert isinstance(result["findings"], list)


def test_health_check_engines_executed_includes_regex_and_column_name():
    result = health_check()
    assert "regex" in result["engines_executed"]
    assert "column_name" in result["engines_executed"]


def test_health_check_detects_email_on_canned_probe():
    """The canned probe feeds ``alice@example.com`` — the cascade must
    detect EMAIL, proving end-to-end wiring is live."""
    result = health_check()
    assert result["findings"], "expected at least one finding on email probe"
    entity_types = {f["entity_type"] for f in result["findings"]}
    assert "EMAIL" in entity_types, f"expected EMAIL finding, got {entity_types}"


def test_health_check_accepts_explicit_profile():
    profile = load_profile("standard")
    result = health_check(profile=profile)
    assert result["healthy"] is True


def test_health_check_returns_healthy_false_on_forced_failure():
    """If classify_columns raises, health_check must catch and return
    ``healthy=False`` with the error text — it must never propagate."""
    boom = RuntimeError("forced failure for test")
    with patch("data_classifier.classify_columns", side_effect=boom):
        result = health_check()
    assert result["healthy"] is False
    assert result["error"] is not None
    assert "forced failure for test" in result["error"]
    assert "RuntimeError" in result["error"]
    # Latency still recorded even on failure
    assert isinstance(result["latency_ms"], float)
    assert result["latency_ms"] >= 0.0


def test_health_check_returns_healthy_false_on_broken_profile():
    """A totally empty profile with no rules still shouldn't crash the
    probe. The function must return a structured dict regardless."""
    broken = ClassificationProfile(name="broken", description="test", rules=[])
    result = health_check(profile=broken)
    assert isinstance(result, dict)
    assert set(result.keys()) == {
        "healthy",
        "engines_executed",
        "engines_skipped",
        "latency_ms",
        "findings",
        "error",
    }


# ── Loud ImportError fallback ───────────────────────────────────────────────


def test_importerror_fallback_produces_warning(monkeypatch):
    """When gliner_engine fails to import, reimporting data_classifier must
    emit a ``logging.WARNING`` instead of silently swallowing the error.

    Note: ``tests/test_meta_classifier_training.py`` unconditionally sets
    ``DATA_CLASSIFIER_DISABLE_ML=1`` at module-import time and never cleans
    up, so when the full suite runs we explicitly unset the var here to
    exercise the try/except ImportError branch we actually care about.
    """
    monkeypatch.delenv("DATA_CLASSIFIER_DISABLE_ML", raising=False)
    # Force the gliner_engine import to raise ImportError.
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "data_classifier.engines.gliner_engine":
            raise ImportError("simulated missing gliner package")
        return real_import(name, globals, locals, fromlist, level)

    # Drop cached modules so _build_default_engines re-runs through the shim.
    # Must also snapshot/evict gliner_engine itself, since other tests may
    # have already imported it into sys.modules — without eviction our
    # fake_import shim never sees the lookup.
    snapshot = _snapshot_dc_modules()
    gliner_snapshot: dict = {}
    if "data_classifier.engines.gliner_engine" in sys.modules:
        gliner_snapshot["data_classifier.engines.gliner_engine"] = sys.modules["data_classifier.engines.gliner_engine"]
    for mod in list(snapshot):
        del sys.modules[mod]
    if "data_classifier.engines.gliner_engine" in sys.modules:
        del sys.modules["data_classifier.engines.gliner_engine"]

    # Attach a direct handler to the data_classifier logger so we don't
    # depend on caplog's root-level propagation — pytest's LogCaptureHandler
    # tracking across a module reimport has proven flaky.
    captured_records: list[logging.LogRecord] = []

    class _MemoryHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_records.append(record)

    dc_logger = logging.getLogger("data_classifier")
    memory_handler = _MemoryHandler(level=logging.WARNING)
    dc_logger.addHandler(memory_handler)
    prior_level = dc_logger.level
    dc_logger.setLevel(logging.WARNING)

    try:
        with patch("builtins.__import__", side_effect=fake_import):
            reloaded = importlib.import_module("data_classifier")
            engines = reloaded.get_active_engines()

        warning_messages = [rec.getMessage() for rec in captured_records if "GLiNER2" in rec.getMessage()]
        assert warning_messages, (
            "expected a WARNING about GLiNER2 being disabled, got: "
            f"{[(r.levelname, r.getMessage()) for r in captured_records]}"
        )
        # Cascade should still work without the ML engine.
        names = [e["name"] for e in engines]
        assert "gliner2" not in names
        assert "regex" in names
    finally:
        dc_logger.removeHandler(memory_handler)
        dc_logger.setLevel(prior_level)
        _restore_dc_modules(snapshot)
        for name, mod in gliner_snapshot.items():
            sys.modules[name] = mod


# ── __all__ exports ─────────────────────────────────────────────────────────


def test_public_symbols_exported_in_all():
    assert "get_active_engines" in data_classifier.__all__
    assert "health_check" in data_classifier.__all__
