"""Corpus-level feature extractor for the meta-classifier training set.

Given a :class:`ColumnInput` plus a ground-truth entity type, runs every
non-ML engine in isolation against the column, collects the raw findings,
and produces a training row in the schema used by Phase 1.

Isolation matters: the orchestrator normally merges findings
authority-weighted, which would hide per-engine signals. For the meta-
classifier we want the *raw* engine votes, so we call each engine
directly (bypassing :class:`Orchestrator`).

Only non-ML engines are used here (regex, column_name, heuristic_stats,
secret_scanner). GLiNER2 is intentionally disabled via the
``DATA_CLASSIFIER_DISABLE_ML=1`` environment variable at the entrypoint
of :mod:`tests.benchmarks.meta_classifier.build_training_data` — this
module never imports it.
"""

from __future__ import annotations

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

# ── Engine registry — lazy singletons, built on first use ───────────────────


@dataclass
class _EngineBundle:
    regex: RegexEngine
    column_name: ColumnNameEngine
    heuristic: HeuristicEngine
    secret_scanner: SecretScannerEngine


_engine_bundle: _EngineBundle | None = None


def _get_engines() -> _EngineBundle:
    """Lazily construct and warm up the non-ML engines."""
    global _engine_bundle
    if _engine_bundle is None:
        bundle = _EngineBundle(
            regex=RegexEngine(),
            column_name=ColumnNameEngine(),
            heuristic=HeuristicEngine(),
            secret_scanner=SecretScannerEngine(),
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
    """Return Chao-1 bias-corrected distinctness ratio. 0.0 for empty input.

    Sprint 11 Phase 8: delegates to the production helper so training
    and live shadow inference cannot drift.
    """
    from data_classifier.engines.heuristic_engine import compute_cardinality_ratio

    return compute_cardinality_ratio(values)


def _avg_length_normalized(values: list[str]) -> float:
    """Return mean string length / 100, clipped to [0, 1]. 0.0 for empty.

    Sprint 13 Item A Task 1 follow-up: delegates to the production helper so
    training and live shadow inference cannot drift.
    """
    from data_classifier.engines.heuristic_engine import compute_avg_length_normalized

    return compute_avg_length_normalized(values)


# ── Main entry point ────────────────────────────────────────────────────────


def _run_all_engines(
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
    from data_classifier.engines.heuristic_engine import (
        compute_dictionary_name_match_ratio,
        compute_dictionary_word_ratio,
        compute_placeholder_credential_rejection_ratio,
    )

    findings = _run_all_engines(column, profile)

    distinct = _distinct_ratio(column.sample_values)
    avg_len = _avg_length_normalized(column.sample_values)
    # Sprint 11 Phase 7: dictionary-word ratio is a pure column-level
    # stat (no engine dependency) so it's computed here and threaded
    # through the meta_classifier feature extractor.
    dict_ratio = compute_dictionary_word_ratio(column.sample_values)
    # Sprint 12 Item #1: placeholder-credential rejection ratio. Same
    # pattern as dict-word-ratio — a pure column-level statistic
    # computed here and threaded through so the training path and
    # predict_shadow see the same value for the same sample_values.
    rejection_ratio = compute_placeholder_credential_rejection_ratio(column.sample_values)
    # Sprint 12 Item #2: dictionary-name match ratio. Same symmetry
    # rule — computed from the same sample_values the inference path
    # sees, so training and serving stay in lockstep.
    name_ratio = compute_dictionary_name_match_ratio(column.sample_values)

    features = _extract_features_from_findings(
        findings,
        heuristic_distinct_ratio=distinct,
        heuristic_avg_length=avg_len,
        heuristic_dictionary_word_ratio=dict_ratio,
        validator_rejected_credential_ratio=rejection_ratio,
        has_dictionary_name_match_ratio=name_ratio,
    )

    fired = sorted({f.engine for f in findings})

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
