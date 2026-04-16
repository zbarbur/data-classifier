"""Multi-label metrics for the column-shape router benchmark (M4 track).

Sprint 11's `family_accuracy_benchmark.py` reports single-label metrics
(`family_macro_f1`, `cross_family_rate`) — correct for a softmax gate
but structurally unable to measure multi-label output. Sprint 13's
column-shape router emits `list[ClassificationFinding]` per column, so
honest evaluation needs set-valued metrics.

This module ships the metric definitions as pure functions and the
aggregation helpers used by `M4e` (dual-report harness) and `M4b` (gate
vs downstream harness). No production-code dependency — the helpers
accept `list[str]` at the boundary so they work against predictions
from any source (the library's router, LLM-as-oracle, a cascade, …).

See `docs/research/multi_label_philosophy.md` §6.3 for the choice of
Jaccard as primary quality gate. See M4a spec in
`docs/experiments/meta_classifier/queue.md` for the full metric list.

Usage (from Python):

    from tests.benchmarks.meta_classifier.multi_label_metrics import (
        jaccard, aggregate_multi_label,
    )

    per_column = [
        {"pred": ["EMAIL", "PHONE"], "true": ["EMAIL", "PHONE", "PERSON"]},
        {"pred": ["EMAIL"],          "true": ["EMAIL"]},
    ]
    report = aggregate_multi_label(per_column)
    # {"jaccard_macro": ..., "micro_f1": ..., "per_class": {...}, ...}
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Per-column metrics
# --------------------------------------------------------------------------- #
#
# Design notes:
#
# - All per-column helpers accept `Iterable[str]` and convert to `set[str]`
#   internally. Duplicates in input are ignored (multi-label labels are
#   unordered unique sets by definition; a column does not carry EMAIL
#   "twice").
#
# - POLICY #1 (empty/empty): Jaccard of two empty sets is defined as 1.0
#   (matches sklearn `jaccard_score(... zero_division=1)` convention). A
#   correctly-empty prediction on a correctly-empty ground truth is a
#   perfect match, not undefined. Reason: the benchmark will contain
#   columns with no PII (negative controls); returning 0 would punish the
#   router for getting them right, returning NaN would force every caller
#   to write the same nan-skipping aggregation.
#
# - POLICY #2 (empty/nonempty or nonempty/empty): Jaccard = 0.0. The
#   denominator |A ∪ B| > 0, the numerator |A ∩ B| = 0. This is the
#   *correct* value by the Jaccard definition, not a policy choice.
#
# - POLICY #3 (per-column F1 with empty pred and empty true): defined
#   as 1.0, same rationale as POLICY #1. `_safe_divide` below encodes
#   this.


def _as_set(labels: Iterable[str]) -> set[str]:
    return set(labels)


def _safe_divide(num: float, denom: float, default: float = 1.0) -> float:
    """Return num/denom, or `default` when denom is zero.

    The `default` is 1.0 not 0.0 because all callers in this module use
    this helper for ratios that are *ill-defined* when denom is zero
    (precision, recall, F1, Jaccard on empty sets). The benchmark's
    convention is "correctly empty is a perfect match".
    """
    if denom == 0:
        return default
    return num / denom


def jaccard(pred: Iterable[str], true: Iterable[str]) -> float:
    """Jaccard similarity |pred ∩ true| / |pred ∪ true| at per-column scope.

    Returns 1.0 for empty/empty (POLICY #1 above).
    """
    p, t = _as_set(pred), _as_set(true)
    union = p | t
    inter = p & t
    return _safe_divide(len(inter), len(union), default=1.0)


def precision(pred: Iterable[str], true: Iterable[str]) -> float:
    """Per-column precision: |pred ∩ true| / |pred|. Empty pred → 1.0."""
    p, t = _as_set(pred), _as_set(true)
    return _safe_divide(len(p & t), len(p), default=1.0)


def recall(pred: Iterable[str], true: Iterable[str]) -> float:
    """Per-column recall: |pred ∩ true| / |true|. Empty true → 1.0."""
    p, t = _as_set(pred), _as_set(true)
    return _safe_divide(len(p & t), len(t), default=1.0)


def f1(pred: Iterable[str], true: Iterable[str]) -> float:
    """Per-column F1 = 2PR / (P+R). Both empty → 1.0."""
    pr = precision(pred, true)
    rc = recall(pred, true)
    return _safe_divide(2 * pr * rc, pr + rc, default=1.0)


def hamming_loss(
    pred: Iterable[str],
    true: Iterable[str],
    label_space: Iterable[str],
) -> float:
    """Fraction of labels in `label_space` where pred and true disagree.

    `label_space` is required because Hamming loss is defined over a
    fixed label universe — you cannot compute disagreement on labels
    neither side produced unless you know the universe.
    """
    p, t, u = _as_set(pred), _as_set(true), _as_set(label_space)
    if not u:
        return 0.0
    disagreements = sum(1 for label in u if (label in p) != (label in t))
    return disagreements / len(u)


def subset_accuracy(pred: Iterable[str], true: Iterable[str]) -> float:
    """Exact-set-match: 1.0 iff pred == true as sets, else 0.0.

    Expected low on heterogeneous columns — reported as a diagnostic,
    not a quality gate (per M4a spec: "tertiary").
    """
    return float(_as_set(pred) == _as_set(true))


# --------------------------------------------------------------------------- #
# Benchmark-level aggregation
# --------------------------------------------------------------------------- #


@dataclass
class ColumnResult:
    """Ground-truth + prediction pair for one column in the benchmark.

    Callers build a list of these; `aggregate_multi_label` consumes it.
    Decoupled from `ClassificationFinding` so callers can feed in
    predictions from LLM-as-oracle, cascade variants, or any source.
    """

    column_id: str
    pred: list[str]
    true: list[str]


def _micro_counts(rows: Sequence[ColumnResult]) -> tuple[int, int, int]:
    """Global (tp, fp, fn) across every (column, label) pair."""
    tp = fp = fn = 0
    for row in rows:
        p, t = _as_set(row.pred), _as_set(row.true)
        tp += len(p & t)
        fp += len(p - t)
        fn += len(t - p)
    return tp, fp, fn


def _per_class_counts(
    rows: Sequence[ColumnResult],
) -> dict[str, tuple[int, int, int]]:
    """Per-label (tp, fp, fn) across the benchmark."""
    counts: dict[str, list[int]] = {}
    for row in rows:
        p, t = _as_set(row.pred), _as_set(row.true)
        for label in p & t:
            counts.setdefault(label, [0, 0, 0])[0] += 1
        for label in p - t:
            counts.setdefault(label, [0, 0, 0])[1] += 1
        for label in t - p:
            counts.setdefault(label, [0, 0, 0])[2] += 1
    return {label: tuple(v) for label, v in counts.items()}  # type: ignore[return-value,misc]


def _micro_f1_from_counts(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """Returns (precision, recall, f1) from global tp/fp/fn."""
    p = _safe_divide(tp, tp + fp, default=1.0)
    r = _safe_divide(tp, tp + fn, default=1.0)
    f = _safe_divide(2 * p * r, p + r, default=1.0)
    return p, r, f


def aggregate_multi_label(
    rows: Sequence[ColumnResult],
    label_space: Iterable[str] | None = None,
) -> dict:
    """Compute the full M4a metric report for a benchmark.

    Args:
        rows: One entry per column in the benchmark.
        label_space: Optional explicit label universe for Hamming loss.
            If None, the union of all labels seen in pred ∪ true is used
            (which understates Hamming loss — acceptable for diagnostic
            use, but callers who want the *canonical* Hamming should pass
            the full family list explicitly).

    Returns:
        A dict with:
          - "jaccard_macro" (primary quality gate per philosophy memo §6.3)
          - "micro_precision", "micro_recall", "micro_f1"
          - "macro_precision", "macro_recall", "macro_f1"
          - "per_class": {label: {"precision", "recall", "f1", "support"}}
          - "hamming_loss" (mean across columns)
          - "subset_accuracy"
          - "n_columns"
          - "n_columns_empty_pred", "n_columns_empty_true" (diagnostic)
    """
    n = len(rows)
    if n == 0:
        return {
            "jaccard_macro": 1.0,
            "micro_precision": 1.0,
            "micro_recall": 1.0,
            "micro_f1": 1.0,
            "macro_precision": 1.0,
            "macro_recall": 1.0,
            "macro_f1": 1.0,
            "per_class": {},
            "hamming_loss": 0.0,
            "subset_accuracy": 1.0,
            "n_columns": 0,
            "n_columns_empty_pred": 0,
            "n_columns_empty_true": 0,
        }

    if label_space is None:
        seen: set[str] = set()
        for row in rows:
            seen |= _as_set(row.pred)
            seen |= _as_set(row.true)
        label_space_set = seen
    else:
        label_space_set = _as_set(label_space)

    # Macro-averaged per-column metrics.
    jaccards = [jaccard(r.pred, r.true) for r in rows]
    hammings = [hamming_loss(r.pred, r.true, label_space_set) for r in rows]
    subsets = [subset_accuracy(r.pred, r.true) for r in rows]

    # Micro = global counts → one P/R/F1 triple.
    micro_p, micro_r, micro_f = _micro_f1_from_counts(*_micro_counts(rows))

    # Per-class P/R/F1.
    per_class_counts = _per_class_counts(rows)
    per_class: dict[str, dict[str, float]] = {}
    for label, (tp, fp, fn) in per_class_counts.items():
        p, r, f = _micro_f1_from_counts(tp, fp, fn)
        per_class[label] = {
            "precision": p,
            "recall": r,
            "f1": f,
            "support": tp + fn,  # true occurrences, not pred occurrences
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    # Macro = mean of per-class P/R/F1. Classes with zero support
    # (appeared only as FP) are still included — they drag macro down,
    # which is the desired behavior ("the router invented a label that
    # was never true; penalize it").
    if per_class:
        macro_p = sum(v["precision"] for v in per_class.values()) / len(per_class)
        macro_r = sum(v["recall"] for v in per_class.values()) / len(per_class)
        macro_f = sum(v["f1"] for v in per_class.values()) / len(per_class)
    else:
        # No labels anywhere — all-negative benchmark. Treat as perfect.
        macro_p = macro_r = macro_f = 1.0

    return {
        "jaccard_macro": sum(jaccards) / n,
        "micro_precision": micro_p,
        "micro_recall": micro_r,
        "micro_f1": micro_f,
        "macro_precision": macro_p,
        "macro_recall": macro_r,
        "macro_f1": macro_f,
        "per_class": per_class,
        "hamming_loss": sum(hammings) / n,
        "subset_accuracy": sum(subsets) / n,
        "n_columns": n,
        "n_columns_empty_pred": sum(1 for r in rows if not r.pred),
        "n_columns_empty_true": sum(1 for r in rows if not r.true),
    }


# --------------------------------------------------------------------------- #
# Label-space helpers
# --------------------------------------------------------------------------- #


def collect_label_support(rows: Sequence[ColumnResult]) -> Counter:
    """How many columns carry each label in ground truth.

    Useful as a sanity check before interpreting macro-F1: a class with
    support=1 has a very high-variance per-class F1, and callers may
    want to drop low-support classes before averaging.
    """
    counter: Counter = Counter()
    for row in rows:
        for label in _as_set(row.true):
            counter[label] += 1
    return counter
