"""Presidio comparator — run Microsoft Presidio on a benchmark corpus
and translate its output into our entity-type vocabulary.

Usage:
    # Install the optional extra
    pip install '.[bench-compare]'
    python -m spacy download en_core_web_lg

    # Call from a benchmark script
    from tests.benchmarks.comparators.presidio_comparator import (
        run_presidio_on_corpus,
    )
    results = run_presidio_on_corpus(corpus, mode="strict")

Design:
- The mapping layer is a pure data-structure computation
  (``STRICT_MAPPING``, ``AGGRESSIVE_MAPPING``, ``translate_entities``)
  and can be unit-tested without having ``presidio-analyzer`` installed.
- ``run_presidio_on_column`` / ``run_presidio_on_corpus`` defer the
  ``presidio_analyzer`` import so the module can be imported even when
  the optional extra is missing.
- The mapping rationale is documented in
  ``docs/benchmarks/presidio_mapping.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from data_classifier.core.types import ColumnInput

# ── Entity type mappings ────────────────────────────────────────────────────
#
# See docs/benchmarks/presidio_mapping.md for the full rationale behind
# each entry. Keep this file in lockstep with that doc.


# Strict 1:1 mapping — same concept, no semantic drift
STRICT_MAPPING: dict[str, str] = {
    "US_SSN": "SSN",
    "CREDIT_CARD": "CREDIT_CARD",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "IP_ADDRESS": "IP_ADDRESS",
    "IBAN_CODE": "IBAN",
    "URL": "URL",
    "US_DRIVER_LICENSE": "DRIVERS_LICENSE",
    "MEDICAL_LICENSE": "DEA_NUMBER",
}

# Aggressive mapping — extends strict with looser cross-category pairs.
# These are semantically adjacent but not 1:1 (e.g. DATE_TIME covers more
# than DATE; LOCATION is broader than ADDRESS). Use when the
# goal is "maximum overlap" rather than "strict like-for-like".
AGGRESSIVE_MAPPING: dict[str, str] = {
    **STRICT_MAPPING,
    "PERSON": "PERSON_NAME",
    "LOCATION": "ADDRESS",
    "DATE_TIME": "DATE",
    "US_BANK_NUMBER": "BANK_ACCOUNT",
    "US_ITIN": "NATIONAL_ID",
    "US_PASSPORT": "NATIONAL_ID",
    "UK_NHS": "MEDICAL_ID",
}


MappingMode = Literal["strict", "aggressive"]


def _get_mapping(mode: str) -> dict[str, str]:
    if mode == "strict":
        return STRICT_MAPPING
    if mode == "aggressive":
        return AGGRESSIVE_MAPPING
    raise ValueError(f"unknown mapping mode {mode!r} — expected 'strict' or 'aggressive'")


# ── Result record ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PresidioEntity:
    """A single Presidio finding translated into our entity vocabulary.

    Carries both the mapped ``entity_type`` (ours) and the original
    ``presidio_type`` so downstream disagreement analysis can explain
    why a finding appeared.
    """

    entity_type: str
    """Our entity type (e.g. ``SSN``)."""

    presidio_type: str
    """Original Presidio entity type (e.g. ``US_SSN``)."""

    score: float
    """Presidio's recognizer confidence score (0.0–1.0)."""


def translate_entities(results: list[Any], mode: str = "strict") -> list[PresidioEntity]:
    """Translate a list of Presidio-like ``RecognizerResult`` objects.

    The input is duck-typed: any object with ``entity_type`` (str) and
    ``score`` (float) attributes works, so unit tests can pass lightweight
    stand-ins without importing ``presidio_analyzer``.

    Deduplicates by mapped entity type, keeping the maximum score per type.
    Drops Presidio entity types that have no entry in the chosen mapping.
    """
    mapping = _get_mapping(mode)

    # Dedup by our mapped type, keeping max score
    best_by_type: dict[str, PresidioEntity] = {}
    for r in results:
        presidio_type = getattr(r, "entity_type", None)
        score = getattr(r, "score", 0.0)
        if not presidio_type:
            continue
        our_type = mapping.get(presidio_type)
        if our_type is None:
            continue
        existing = best_by_type.get(our_type)
        if existing is None or score > existing.score:
            best_by_type[our_type] = PresidioEntity(
                entity_type=our_type,
                presidio_type=presidio_type,
                score=float(score),
            )
    return list(best_by_type.values())


# ── Comparison metrics ──────────────────────────────────────────────────────


@dataclass
class ColumnComparison:
    """Per-column agreement between data_classifier and Presidio.

    Produced by ``compute_column_comparison``. ``agreement`` is one of:
      - ``both_correct`` — both classified the column as expected
      - ``dc_only_correct`` — only data_classifier was correct
      - ``presidio_only_correct`` — only Presidio was correct
      - ``both_wrong`` — neither matched (may or may not be TN)
      - ``dc_only_fp`` / ``presidio_only_fp`` — negative column, false match
      - ``both_fp`` — both misclassified a negative column
    """

    column_id: str
    expected: str | None
    data_classifier_types: list[str]
    presidio_types: list[str]
    data_classifier_tp: bool
    presidio_tp: bool
    agreement: str
    details: dict[str, Any] = field(default_factory=dict)


def compute_column_comparison(
    *,
    column_id: str,
    expected: str | None,
    data_classifier_types: list[str],
    presidio_types: list[str],
) -> ColumnComparison:
    """Compute agreement flags for one column.

    A column is considered a TP for a classifier if ``expected`` is not
    None and appears in the classifier's predicted types.
    """
    if expected is None:
        # Negative column — any prediction is a false positive
        dc_has_match = bool(data_classifier_types)
        pr_has_match = bool(presidio_types)
        if not dc_has_match and not pr_has_match:
            agreement = "both_correct_negative"
        elif dc_has_match and pr_has_match:
            agreement = "both_fp"
        elif dc_has_match:
            agreement = "dc_only_fp"
        else:
            agreement = "presidio_only_fp"
        return ColumnComparison(
            column_id=column_id,
            expected=expected,
            data_classifier_types=list(data_classifier_types),
            presidio_types=list(presidio_types),
            data_classifier_tp=False,
            presidio_tp=False,
            agreement=agreement,
        )

    dc_tp = expected in data_classifier_types
    pr_tp = expected in presidio_types

    if dc_tp and pr_tp:
        agreement = "both_correct"
    elif dc_tp:
        agreement = "dc_only_correct"
    elif pr_tp:
        agreement = "presidio_only_correct"
    else:
        agreement = "both_wrong"

    return ColumnComparison(
        column_id=column_id,
        expected=expected,
        data_classifier_types=list(data_classifier_types),
        presidio_types=list(presidio_types),
        data_classifier_tp=dc_tp,
        presidio_tp=pr_tp,
        agreement=agreement,
    )


# ── Live engine integration ─────────────────────────────────────────────────


def _get_analyzer() -> Any:
    """Import and construct a Presidio ``AnalyzerEngine`` lazily.

    Raises ``RuntimeError`` with an actionable install hint if the
    ``presidio-analyzer`` extra or its spaCy model are missing.
    """
    try:
        from presidio_analyzer import AnalyzerEngine
    except ImportError as exc:  # pragma: no cover — tested via importorskip
        raise RuntimeError(
            "presidio-analyzer is not installed. Install the optional extra:\n"
            "  pip install '.[bench-compare]'\n"
            "  python -m spacy download en_core_web_lg"
        ) from exc
    return AnalyzerEngine()


def _column_text(column: ColumnInput) -> str:
    """Concatenate a column's sample values as newline-separated text.

    Presidio operates on free-text documents, not structured columns, so
    we present each column as a mini-document. Newlines are deliberate:
    they create natural context boundaries so the recognizer doesn't
    merge adjacent values into a single match.
    """
    return "\n".join(v for v in column.sample_values if v is not None)


def run_presidio_on_column(
    column: ColumnInput,
    *,
    mode: str = "strict",
    analyzer: Any = None,
    language: str = "en",
) -> list[PresidioEntity]:
    """Run Presidio on a single ColumnInput and translate results.

    If ``analyzer`` is provided, use it directly (useful for corpus-level
    calls that reuse one engine). Otherwise, construct a new one lazily.
    """
    if analyzer is None:
        analyzer = _get_analyzer()

    text = _column_text(column)
    if not text.strip():
        return []

    # Presidio's analyze() accepts `entities=None` to mean "all known"
    results = analyzer.analyze(text=text, language=language)
    return translate_entities(results, mode=mode)


def run_presidio_on_corpus(
    corpus: list[tuple[ColumnInput, str | None]],
    *,
    mode: str = "strict",
    language: str = "en",
) -> dict[str, list[PresidioEntity]]:
    """Run Presidio on every column in a corpus.

    Returns a dict mapping ``column_id -> list[PresidioEntity]``.
    Constructs one ``AnalyzerEngine`` for the whole run (the engine
    is heavy to initialize; reuse amortizes the cost).
    """
    analyzer = _get_analyzer()
    predictions: dict[str, list[PresidioEntity]] = {}
    for col, _expected in corpus:
        predictions[col.column_id] = run_presidio_on_column(col, mode=mode, analyzer=analyzer, language=language)
    return predictions


# ── Side-by-side benchmark aggregation ──────────────────────────────────────


@dataclass
class ComparatorRunResult:
    """Per-(corpus, mode) summary of running an external comparator.

    Deliberately separate from ``consolidated_report.RunResult`` so we can
    introduce/extend comparator-specific fields without touching the
    primary benchmark datastructure.
    """

    corpus: str
    blind: bool
    mapping_mode: str  # "strict" or "aggressive"
    num_columns: int
    total_tp: int
    total_fp: int
    total_fn: int
    precision: float
    recall: float
    micro_f1: float
    macro_f1: float
    per_entity_tp: dict[str, int] = field(default_factory=dict)
    per_entity_fp: dict[str, int] = field(default_factory=dict)
    per_entity_fn: dict[str, int] = field(default_factory=dict)
    disagreements: list[ColumnComparison] = field(default_factory=list)


def compute_corpus_metrics(
    corpus: list[tuple[ColumnInput, str | None]],
    data_classifier_predictions: dict[str, list[str]],
    presidio_predictions: dict[str, list[PresidioEntity]],
    *,
    corpus_name: str,
    blind: bool,
    mapping_mode: str,
) -> ComparatorRunResult:
    """Aggregate per-column comparisons into a ``ComparatorRunResult``.

    This is the pure-function pivot point: given both classifiers' outputs
    + ground truth, compute Presidio's precision/recall/F1 on the same
    corpus and list every column where the two classifiers disagree.
    """
    tp = fp = fn = 0
    per_entity_tp: dict[str, int] = {}
    per_entity_fp: dict[str, int] = {}
    per_entity_fn: dict[str, int] = {}
    disagreements: list[ColumnComparison] = []

    for col, expected in corpus:
        dc_types = data_classifier_predictions.get(col.column_id, [])
        pr_entities = presidio_predictions.get(col.column_id, [])
        pr_types = [e.entity_type for e in pr_entities]

        comparison = compute_column_comparison(
            column_id=col.column_id,
            expected=expected,
            data_classifier_types=dc_types,
            presidio_types=pr_types,
        )

        # Record all non-agreement cases for disagreement reporting
        if comparison.agreement not in ("both_correct", "both_correct_negative"):
            disagreements.append(comparison)

        # Compute Presidio TP/FP/FN against ground truth (column-level)
        if expected is not None:
            if expected in pr_types:
                tp += 1
                per_entity_tp[expected] = per_entity_tp.get(expected, 0) + 1
            else:
                fn += 1
                per_entity_fn[expected] = per_entity_fn.get(expected, 0) + 1
            for pt in pr_types:
                if pt != expected:
                    fp += 1
                    per_entity_fp[pt] = per_entity_fp.get(pt, 0) + 1
        else:
            for pt in pr_types:
                fp += 1
                per_entity_fp[pt] = per_entity_fp.get(pt, 0) + 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    micro_f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Macro F1: unweighted mean of per-entity F1 across entities with ground-truth columns
    entity_types = set(per_entity_tp) | set(per_entity_fn)
    per_entity_f1 = []
    for et in entity_types:
        etp = per_entity_tp.get(et, 0)
        efp = per_entity_fp.get(et, 0)
        efn = per_entity_fn.get(et, 0)
        ep = etp / (etp + efp) if (etp + efp) > 0 else 0.0
        er = etp / (etp + efn) if (etp + efn) > 0 else 0.0
        ef1 = 2 * ep * er / (ep + er) if (ep + er) > 0 else 0.0
        per_entity_f1.append(ef1)
    macro_f1 = sum(per_entity_f1) / len(per_entity_f1) if per_entity_f1 else 0.0

    return ComparatorRunResult(
        corpus=corpus_name,
        blind=blind,
        mapping_mode=mapping_mode,
        num_columns=len(corpus),
        total_tp=tp,
        total_fp=fp,
        total_fn=fn,
        precision=precision,
        recall=recall,
        micro_f1=micro_f1,
        macro_f1=macro_f1,
        per_entity_tp=per_entity_tp,
        per_entity_fp=per_entity_fp,
        per_entity_fn=per_entity_fn,
        disagreements=disagreements,
    )


def format_side_by_side_table(
    dc_rows: list[tuple[str, str, float, float, float]],
    comparator_rows: list[tuple[str, str, float, float, float]],
    *,
    comparator_name: str = "Presidio",
) -> str:
    """Format a text table comparing two classifiers across configs.

    Each row tuple is ``(corpus, mode, precision, recall, macro_f1)``.
    Both input lists must have the same length and align on the same
    ``(corpus, mode)`` keys — the caller builds them from parallel benchmark
    runs.
    """
    if len(dc_rows) != len(comparator_rows):
        raise ValueError(f"row count mismatch: dc={len(dc_rows)} vs {comparator_name.lower()}={len(comparator_rows)}")

    lines: list[str] = []
    header = (
        f"{'Corpus':12s}  {'Mode':6s}  "
        f"{'DC  P':>7s}  {'DC  R':>7s}  {'DC F1':>7s}  "
        f"{comparator_name + ' P':>10s}  {comparator_name + ' R':>10s}  {comparator_name + ' F1':>11s}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for (c1, m1, dp, dr, df1), (c2, m2, pp, pr, pf1) in zip(dc_rows, comparator_rows, strict=True):
        if c1 != c2 or m1 != m2:
            raise ValueError(f"row alignment mismatch: dc=({c1},{m1}) vs {comparator_name.lower()}=({c2},{m2})")
        lines.append(f"{c1:12s}  {m1:6s}  {dp:7.3f}  {dr:7.3f}  {df1:7.3f}  {pp:10.3f}  {pr:10.3f}  {pf1:11.3f}")
    return "\n".join(lines)
