"""Corpus-level feature extractor for the meta-classifier training set.

Given a :class:`ColumnInput` plus a ground-truth entity type, runs every
engine in isolation against the column, collects the raw findings, and
produces a training row in the schema used by Phase 2 (15 features) or
E10 (20 features — adds five GLiNER-derived slots).

Isolation matters: the orchestrator normally merges findings
authority-weighted, which would hide per-engine signals. For the meta-
classifier we want the *raw* engine votes, so we call each engine
directly (bypassing :class:`Orchestrator`).

Phase 2 deliberately excluded GLiNER2 via ``DATA_CLASSIFIER_DISABLE_ML=1``.
E10 flips that — GLiNER is run as a fifth, optional engine. Its findings
are kept in a *separate* list (not merged into ``findings``) and passed
to ``extract_features`` via the ``gliner_findings`` kwarg. This keeps
the five GLiNER-derived features cleanly attributable to GLiNER while
the 15 non-ML features still see only the non-ML engine votes.

Kill switch: if GLiNER cannot be loaded (missing ``gliner`` package,
ONNX model absent, or ``DATA_CLASSIFIER_DISABLE_ML=1`` set), this module
logs once and runs with an empty GLiNER findings list — the five new
feature slots become zero, exactly as they are in Phase 3 shadow mode
when GLiNER context is unavailable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
)
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.orchestrator.meta_classifier import (
    FEATURE_DIM,
    FEATURE_NAMES,
)
from data_classifier.orchestrator.meta_classifier import (
    extract_features as _extract_features_from_findings,
)

_log = logging.getLogger(__name__)


# ── Engine registry — lazy singletons, built on first use ───────────────────


@dataclass
class _EngineBundle:
    regex: RegexEngine
    column_name: ColumnNameEngine
    heuristic: HeuristicEngine
    secret_scanner: SecretScannerEngine
    gliner: object | None  # GLiNER2Engine or None when disabled/unavailable


_engine_bundle: _EngineBundle | None = None
_gliner_load_warning_emitted = False


def _gliner_is_disabled() -> bool:
    """Return True if the env var kill switch is set."""
    return os.environ.get("DATA_CLASSIFIER_DISABLE_ML", "") == "1"


def _try_load_gliner() -> object | None:
    """Load GLiNER2Engine, or return None on any failure.

    Failure modes covered:
      * env kill switch (``DATA_CLASSIFIER_DISABLE_ML=1``)
      * ``gliner`` package not installed
      * ONNX model missing AND HuggingFace download fails
      * transformer weights absent from local cache and no network
    """
    global _gliner_load_warning_emitted

    if _gliner_is_disabled():
        if not _gliner_load_warning_emitted:
            _log.warning("GLiNER disabled via DATA_CLASSIFIER_DISABLE_ML; training rows will have zero GLiNER features")
            _gliner_load_warning_emitted = True
        return None

    try:
        from data_classifier.engines.gliner_engine import GLiNER2Engine  # type: ignore[import-not-found]

        engine = GLiNER2Engine()
        engine.startup()
    except Exception as exc:
        if not _gliner_load_warning_emitted:
            _log.warning("GLiNER engine unavailable (%s); training rows will have zero GLiNER features", exc)
            _gliner_load_warning_emitted = True
        return None

    return engine


def _get_engines() -> _EngineBundle:
    """Lazily construct and warm up all engines including GLiNER."""
    global _engine_bundle
    if _engine_bundle is None:
        bundle = _EngineBundle(
            regex=RegexEngine(),
            column_name=ColumnNameEngine(),
            heuristic=HeuristicEngine(),
            secret_scanner=SecretScannerEngine(),
            gliner=_try_load_gliner(),
        )
        for engine in (bundle.regex, bundle.column_name, bundle.heuristic, bundle.secret_scanner):
            engine.startup()
        _engine_bundle = bundle
    return _engine_bundle


# ── Training row schema ─────────────────────────────────────────────────────


@dataclass
class TrainingRow:
    """A single (features, label) training example with metadata."""

    column_id: str
    corpus: str
    mode: str
    source: str
    features: list[float]
    ground_truth: str
    #: True if at least one engine produced any finding for this column.
    has_any_signal: bool
    #: Set of distinct engines that fired (subset of
    #: {"regex", "column_name", "heuristic_stats", "secret_scanner"}).
    fired_engines: tuple[str, ...]

    def to_json_dict(self) -> dict:
        """Serialise to the on-disk JSONL schema (drops bookkeeping fields)."""
        return {
            "column_id": self.column_id,
            "corpus": self.corpus,
            "mode": self.mode,
            "source": self.source,
            "features": self.features,
            "ground_truth": self.ground_truth,
        }


# ── Heuristic column statistics (pure, no engine dependency) ────────────────


def _distinct_ratio(values: list[str]) -> float:
    """Return distinct-value ratio. 0.0 for empty input."""
    if not values:
        return 0.0
    return len(set(values)) / len(values)


def _avg_length_normalized(values: list[str]) -> float:
    """Return mean string length / 100, clipped to [0, 1]. 0.0 for empty."""
    if not values:
        return 0.0
    total = sum(len(v) for v in values)
    mean = total / len(values)
    normalized = mean / 100.0
    if normalized < 0.0:
        return 0.0
    if normalized > 1.0:
        return 1.0
    return normalized


# ── Main entry point ────────────────────────────────────────────────────────


def _run_non_ml_engines(
    column: ColumnInput,
    profile: ClassificationProfile,
) -> list[ClassificationFinding]:
    """Run every non-ML engine in isolation and return their raw findings."""
    engines = _get_engines()
    findings: list[ClassificationFinding] = []

    # Use min_confidence=0 so we capture the full signal, including
    # weak hits that the production pipeline would otherwise filter out.
    for engine in (engines.regex, engines.column_name, engines.heuristic, engines.secret_scanner):
        try:
            engine_findings = engine.classify_column(
                column,
                profile=profile,
                min_confidence=0.0,
            )
        except Exception:
            # Engines must never break feature extraction. Log-free to
            # keep extract_features pure at the meta_classifier layer.
            engine_findings = []
        findings.extend(engine_findings)

    return findings


def _run_gliner(
    column: ColumnInput,
    profile: ClassificationProfile,
) -> list[ClassificationFinding]:
    """Run GLiNER in isolation, returning its raw findings.

    Returns an empty list if the engine is unavailable or if inference
    throws — GLiNER's absence must not break feature extraction.
    """
    engines = _get_engines()
    if engines.gliner is None:
        return []
    try:
        return engines.gliner.classify_column(  # type: ignore[attr-defined]
            column,
            profile=profile,
            min_confidence=0.0,
        )
    except Exception:
        return []


def extract_training_row(
    column: ColumnInput,
    ground_truth: str,
    *,
    profile: ClassificationProfile,
    column_id: str,
    corpus: str,
    mode: str,
    source: str,
) -> TrainingRow:
    """Extract a single training row for the given labeled column."""
    findings = _run_non_ml_engines(column, profile)
    gliner_findings = _run_gliner(column, profile)

    distinct = _distinct_ratio(column.sample_values)
    avg_len = _avg_length_normalized(column.sample_values)

    features = _extract_features_from_findings(
        findings,
        heuristic_distinct_ratio=distinct,
        heuristic_avg_length=avg_len,
        gliner_findings=gliner_findings,
    )

    # fired_engines records every distinct engine that produced a finding,
    # including GLiNER. This is a training-row bookkeeping field, not an
    # input feature — ``engines_fired`` in the feature vector is still
    # computed from the non-ML findings list by extract_features.
    fired = sorted({f.engine for f in findings} | {f.engine for f in gliner_findings})

    return TrainingRow(
        column_id=column_id,
        corpus=corpus,
        mode=mode,
        source=source,
        features=features,
        ground_truth=ground_truth,
        has_any_signal=bool(findings),
        fired_engines=tuple(fired),
    )


__all__ = [
    "FEATURE_DIM",
    "FEATURE_NAMES",
    "TrainingRow",
    "extract_training_row",
]
