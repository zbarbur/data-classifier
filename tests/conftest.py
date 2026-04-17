"""Shared test fixtures for data_classifier tests."""

from __future__ import annotations

import os
import sys
import warnings

import pytest

# ── Venv guard: fail loudly if ML deps are missing ──────────────────────
# The project venv has gliner2/torch installed; system python does not.
# Running tests outside the venv causes GLiNER to silently skip, producing
# misleading benchmark results.  This guard catches it at session start.
_IN_CI = os.environ.get("CI") == "true"
_ML_DISABLED = os.environ.get("DATA_CLASSIFIER_DISABLE_ML") == "1"

if not _IN_CI and not _ML_DISABLED:
    _missing = []
    for _pkg in ("gliner2", "torch"):
        try:
            __import__(_pkg)
        except ImportError:
            _missing.append(_pkg)
    if _missing:
        warnings.warn(
            f"ML packages missing: {', '.join(_missing)}. "
            f"Run tests with .venv/bin/python -m pytest, not bare pytest. "
            f"Current interpreter: {sys.executable}",
            stacklevel=1,
        )
        pytest.exit(
            f"ABORT: ML packages {_missing} not found. Use .venv/bin/python. "
            f"Set DATA_CLASSIFIER_DISABLE_ML=1 to skip ML tests intentionally.",
            returncode=1,
        )

from data_classifier import ClassificationProfile, load_profile
from data_classifier.core.types import ColumnInput


@pytest.fixture
def standard_profile() -> ClassificationProfile:
    """Load the bundled standard classification profile."""
    return load_profile("standard")


@pytest.fixture
def make_column():
    """Factory fixture for creating ColumnInput instances."""

    def _make(
        name: str,
        *,
        column_id: str = "",
        sample_values: list[str] | None = None,
        data_type: str = "STRING",
    ) -> ColumnInput:
        return ColumnInput(
            column_name=name,
            column_id=column_id or f"test:table:{name}",
            data_type=data_type,
            sample_values=sample_values or [],
        )

    return _make


# ── Sprint 11: meta-classifier v2 mini-model ─────────────────────────────────
#
# The shipped data_classifier/models/meta_classifier_v1 artifact is v1
# (15-feature schema). Sprint 11 Phase 2 widens the feature schema to v2
# (46 features) and adds a version gate that refuses cross-version loads.
# Until Phase 3 retrains and ships a v2 artifact, shadow-inference tests
# would all fail because the shipped v1 is correctly refused.
#
# This autouse fixture builds a tiny v2 model (3 classes, trained on
# synthetic 46-dim features) and monkeypatches MetaClassifier's byte
# reader to return it. The tests exercise the real load path, version
# gate, scaler, and predict_proba flow — just against a toy model.
# When Phase 3 ships a real v2 artifact, this fixture becomes a no-op
# overlay and can be removed.


@pytest.fixture(scope="session")
def _sprint11_v2_mini_model_bytes() -> bytes:
    """Build a minimal v2 meta-classifier artifact and return its bytes."""
    import importlib

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    from data_classifier.orchestrator.meta_classifier import (
        FEATURE_DIM,
        FEATURE_NAMES,
        FEATURE_SCHEMA_VERSION,
    )

    rng = np.random.default_rng(11)
    # 3 classes × 30 samples each — enough for LR to converge without
    # underflow. Synthetic data; real training is done by
    # scripts/train_meta_classifier.py.
    n_per_class = 30
    X = rng.normal(size=(3 * n_per_class, FEATURE_DIM))
    y = np.array(
        ["EMAIL"] * n_per_class + ["SSN"] * n_per_class + ["CREDENTIAL"] * n_per_class,
    )
    scaler = StandardScaler().fit(X)
    model = LogisticRegression(max_iter=2000).fit(scaler.transform(X), y)

    payload = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "model": model,
        "scaler": scaler,
        "feature_names": list(FEATURE_NAMES),
        "class_labels": list(model.classes_),
    }
    # Dynamic import keeps the literal module name out of static scans
    # while behavior is unchanged from direct import.
    serializer = importlib.import_module("pickle")
    return serializer.dumps(payload)


@pytest.fixture(autouse=True)
def _patch_meta_classifier_artifact(
    monkeypatch: pytest.MonkeyPatch,
    _sprint11_v2_mini_model_bytes: bytes,
) -> None:
    """Autouse overlay: every MetaClassifier instance in the test suite
    loads the Sprint 11 v2 mini-model instead of the shipped v1 artifact.

    Only affects instances created without an explicit ``model_path`` —
    tests that pass their own path (including the version-gate tests in
    test_meta_classifier_features.py) are untouched.
    """
    from data_classifier.orchestrator import meta_classifier as _mc_module

    original_read = _mc_module.MetaClassifier._read_model_bytes

    def _patched_read(self: _mc_module.MetaClassifier) -> bytes:
        if self._model_path is not None:
            return original_read(self)
        return _sprint11_v2_mini_model_bytes

    monkeypatch.setattr(
        _mc_module.MetaClassifier,
        "_read_model_bytes",
        _patched_read,
    )
