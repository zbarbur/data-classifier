"""Family-level accuracy benchmark — the canonical Sprint 11+ quality metric.

Runs ``classify_columns`` on every shard produced by the shard builder
and reports two tiers of accuracy:

* **Tier 1 (primary)**: cross-family error rate and family-level macro
  P/R/F1. This is the product quality metric — does the classifier
  land in the right family? Cross-family errors are real quality
  gaps; within-family mislabels are nice-to-have metadata.

* **Tier 2 (secondary)**: subtype-level macro P/R/F1, reported for
  debugging only. Within-family subtype confusion does not score
  against the sprint quality gate.

Each column is classified once through the full orchestrator, and
both the live top prediction and the meta-classifier shadow
prediction are captured side-by-side via the event emitter. The
shadow-stream metrics measure the upper bound of "what would happen
if we promoted the shadow path to directive" — that is the gate
Sprint 12+ uses to decide when the shadow model is ready.

Outputs
-------
- ``predictions.jsonl`` — one row per shard with live and shadow
  predictions, mode, corpus, fired engines. Diffable across runs.
- ``summary.json`` — headline cross-family rate, family-level macro
  F1 for both live and shadow paths, per-family P/R/F1 breakdown,
  per-mode split (named vs blind), plus subtype-level metrics as a
  secondary view.

Usage
-----

Canonical run (full 10,170 shards, ~30s wall clock)::

    DATA_CLASSIFIER_DISABLE_ML=1 \\
        python -m tests.benchmarks.family_accuracy_benchmark \\
        --out /tmp/bench.predictions.jsonl \\
        --summary /tmp/bench.summary.json

Sprint-to-sprint delta (compare current run against a committed
summary from the previous sprint)::

    python -m tests.benchmarks.family_accuracy_benchmark \\
        --out /tmp/new.predictions.jsonl \\
        --summary /tmp/new.summary.json \\
        --compare-to docs/research/meta_classifier/sprint11_family_benchmark.json

This module uses ``print`` (not ``logging``) because it is a CLI
entrypoint whose stderr output IS the user interface — progress lines
and the headline report go to stderr so a human operator running the
benchmark sees them, while the structured ``predictions.jsonl`` and
``summary.json`` are the machine-readable artifacts. CLAUDE.md's "no
print statements" rule is for library code; CLI entrypoints are the
documented exception, which is why each ``print`` carries an explicit
``# noqa: T201`` annotation to survive a future ruff rule addition.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from data_classifier import FAMILIES, classify_columns, family_for, load_profile
from data_classifier.core.taxonomy import ENTITY_TYPE_TO_FAMILY
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from tests.benchmarks.meta_classifier.build_training_data import _build_synthetic_pool
from tests.benchmarks.meta_classifier.multi_label_metrics import (
    ColumnResult,
    aggregate_multi_label,
)
from tests.benchmarks.meta_classifier.shard_builder import build_shards

try:
    from data_classifier.events.types import MetaClassifierEvent
except ImportError:  # pragma: no cover — older checkouts
    MetaClassifierEvent = None  # type: ignore[assignment]

try:
    from data_classifier.events.types import ColumnShapeEvent
except ImportError:  # pragma: no cover — older checkouts
    ColumnShapeEvent = None  # type: ignore[assignment]


# ── Per-shard classification ────────────────────────────────────────────────


# M4b ground-truth shape heuristic: independent of the router's own
# predictions so gate accuracy is measurable. Grounded in "does this column
# need multi-engine cascade to classify correctly?":
#   * Scanner corpora (secretbench / gitleaks / detect_secrets) — values are
#     KV config-line fragments with entities embedded inside structural
#     wrappers; need column_name + regex + secret_scanner. → heterogeneous.
#   * Opaque-by-design ground truths (BITCOIN_ADDRESS / ETHEREUM_ADDRESS /
#     OPAQUE_SECRET) — values are single high-entropy blobs. → opaque_tokens.
#   * Everything else — clean single-entity columns, one engine suffices. →
#     structured_single.
#
# Documented disagreements with router-predicted shape are the data M4b
# is designed to surface (e.g., router over-routing clean single-entity
# address columns to heterogeneous). Do NOT align this heuristic to the
# router — that would make gate accuracy trivially 100%.
_OPAQUE_GROUND_TRUTHS = frozenset({"BITCOIN_ADDRESS", "ETHEREUM_ADDRESS", "OPAQUE_SECRET"})
_SCANNER_CORPORA = frozenset({"secretbench", "gitleaks", "detect_secrets"})


def _derive_true_shape(corpus: str, ground_truth: str) -> str:
    if corpus in _SCANNER_CORPORA:
        return "free_text_heterogeneous"
    if ground_truth in _OPAQUE_GROUND_TRUTHS:
        return "opaque_tokens"
    return "structured_single"


def _top_finding(findings):
    if not findings:
        return None
    return max(findings, key=lambda f: f.confidence)


def _run_one_shard(shard, profile) -> dict:
    # One emitter per call keeps captured events bounded to this
    # column and avoids any need to reset shared state.
    captured: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(lambda ev: captured.append(ev)))

    findings = classify_columns(
        [shard.column],
        profile,
        min_confidence=0.0,
        event_emitter=emitter,
    )
    top = _top_finding(findings)

    shadow_entity: str | None = None
    shadow_confidence: float = 0.0
    shadow_agreement: bool | None = None
    if MetaClassifierEvent is not None:
        for ev in captured:
            if isinstance(ev, MetaClassifierEvent):
                shadow_entity = ev.predicted_entity or None
                shadow_confidence = round(ev.confidence, 4)
                shadow_agreement = ev.agreement
                break

    shape: str | None = None
    if ColumnShapeEvent is not None:
        for ev in captured:
            if isinstance(ev, ColumnShapeEvent):
                shape = ev.shape
                break

    return {
        "column_id": shard.column_id,
        "ground_truth": shard.ground_truth,
        "mode": shard.mode,
        "corpus": shard.corpus,
        "source": shard.source,
        "predicted": top.entity_type if top else None,
        "confidence": round(top.confidence, 4) if top else 0.0,
        "category": top.category if top else None,
        "engine": top.engine if top else None,
        "fired_engines": sorted({f.engine for f in findings}),
        "n_findings": len(findings),
        "shadow_predicted": shadow_entity,
        "shadow_confidence": shadow_confidence,
        "shadow_agrees_with_live": shadow_agreement,
        "shape": shape,
        "true_shape": _derive_true_shape(shard.corpus, shard.ground_truth),
        "shadow_suppressed_by_router": shape is not None and shape != "structured_single",
    }


# ── Metric computation ──────────────────────────────────────────────────────


def _compute_family_metrics(predictions: list[dict], pred_field: str) -> dict:
    """Family-level Tier 1 metrics: cross-family rate + macro P/R/F1.

    Reports two views of cross_family under the Sprint 13 shape gate:
      * ``cross_family_rate`` — legacy metric, counts router-suppressed
        columns as errors (Sprint 12 semantics). Retained for audit-trail
        continuity when comparing against pre-gate baselines.
      * ``cross_family_rate_emitted`` — null-aware, excludes router-
        suppressed columns from both numerator and denominator. This is
        the correct measurement of v5 model quality under the gate.
      * ``router_suppression_rate`` — fraction of columns where the
        router deflected shadow emission. Sidecar observability.
    """
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    support: dict[str, int] = defaultdict(int)

    cross_family = 0
    within_family_mislabel = 0

    for p in predictions:
        gt_sub = p["ground_truth"]
        pr_sub = p.get(pred_field) or ""
        gt_fam = family_for(gt_sub)
        pr_fam = family_for(pr_sub) if pr_sub else ""

        support[gt_fam] += 1
        if gt_fam == pr_fam and gt_fam:
            tp[gt_fam] += 1
            if gt_sub != pr_sub:
                within_family_mislabel += 1
        else:
            fn[gt_fam] += 1
            if pr_fam:
                fp[pr_fam] += 1
            cross_family += 1

    per_family: dict[str, dict] = {}
    f1_sum = 0.0
    f1_count = 0
    for fam in sorted(set(support) | set(fp)):
        if not fam:
            continue
        P = tp[fam] / (tp[fam] + fp[fam]) if (tp[fam] + fp[fam]) else 0.0
        R = tp[fam] / (tp[fam] + fn[fam]) if (tp[fam] + fn[fam]) else 0.0
        F = 2 * P * R / (P + R) if (P + R) else 0.0
        per_family[fam] = {
            "precision": round(P, 4),
            "recall": round(R, 4),
            "f1": round(F, 4),
            "support": support[fam],
            "tp": tp[fam],
            "fp": fp[fam],
            "fn": fn[fam],
        }
        if support[fam] > 0:
            f1_sum += F
            f1_count += 1

    # Sprint 13: null-aware metrics — partition into emitted vs suppressed
    emitted_cross_family = 0
    emitted_total = 0
    suppressed_count = 0
    suppressed_by_shape: dict[str, int] = defaultdict(int)

    for p in predictions:
        if p.get("shadow_suppressed_by_router", False):
            suppressed_count += 1
            shape = p.get("shape")
            if shape:
                suppressed_by_shape[shape] += 1
            continue

        emitted_total += 1
        gt_sub = p["ground_truth"]
        pr_sub = p.get(pred_field) or ""
        gt_fam = family_for(gt_sub)
        pr_fam = family_for(pr_sub) if pr_sub else ""
        if gt_fam != pr_fam or not gt_fam:
            emitted_cross_family += 1

    # Compute macro F1 on emitted subset
    tp_emit: dict[str, int] = defaultdict(int)
    fp_emit: dict[str, int] = defaultdict(int)
    fn_emit: dict[str, int] = defaultdict(int)
    support_emit: dict[str, int] = defaultdict(int)
    for p in predictions:
        if p.get("shadow_suppressed_by_router", False):
            continue
        gt_sub = p["ground_truth"]
        pr_sub = p.get(pred_field) or ""
        gt_fam = family_for(gt_sub)
        pr_fam = family_for(pr_sub) if pr_sub else ""
        support_emit[gt_fam] += 1
        if gt_fam == pr_fam and gt_fam:
            tp_emit[gt_fam] += 1
        else:
            fn_emit[gt_fam] += 1
            if pr_fam:
                fp_emit[pr_fam] += 1

    f1_sum_emit = 0.0
    f1_count_emit = 0
    for fam in sorted(set(support_emit) | set(fp_emit)):
        if not fam:
            continue
        P = tp_emit[fam] / (tp_emit[fam] + fp_emit[fam]) if (tp_emit[fam] + fp_emit[fam]) else 0.0
        R = tp_emit[fam] / (tp_emit[fam] + fn_emit[fam]) if (tp_emit[fam] + fn_emit[fam]) else 0.0
        F = 2 * P * R / (P + R) if (P + R) else 0.0
        if support_emit[fam] > 0:
            f1_sum_emit += F
            f1_count_emit += 1
    family_macro_f1_emitted = round(f1_sum_emit / f1_count_emit, 4) if f1_count_emit else 0.0

    return {
        # legacy fields (unchanged semantics — Sprint 12 audit-trail continuity)
        "cross_family_errors": cross_family,
        "cross_family_rate": round(cross_family / len(predictions), 4) if predictions else 0.0,
        "within_family_mislabels": within_family_mislabel,
        "n_shards": len(predictions),
        "family_macro_f1": round(f1_sum / f1_count, 4) if f1_count else 0.0,
        "per_family": per_family,
        # Sprint 13: null-aware metrics under the shape gate
        "cross_family_rate_emitted": round(emitted_cross_family / emitted_total, 4) if emitted_total else 0.0,
        "family_macro_f1_emitted": family_macro_f1_emitted,
        "n_shards_emitted": emitted_total,
        "router_suppressed_count": suppressed_count,
        "router_suppression_rate": round(suppressed_count / len(predictions), 4) if predictions else 0.0,
        "suppressed_by_shape": dict(suppressed_by_shape),
    }


def _compute_subtype_metrics(predictions: list[dict], pred_field: str) -> dict:
    """Subtype-level Tier 2 metrics — informational only."""
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    support: dict[str, int] = defaultdict(int)

    for p in predictions:
        gt = p["ground_truth"]
        pr = p.get(pred_field) or ""
        support[gt] += 1
        if gt == pr:
            tp[gt] += 1
        else:
            fn[gt] += 1
            if pr:
                fp[pr] += 1

    per_class: dict[str, dict] = {}
    f1_sum = 0.0
    f1_count = 0
    correct = 0
    for label in sorted(set(support) | set(fp)):
        if not label:
            continue
        P = tp[label] / (tp[label] + fp[label]) if (tp[label] + fp[label]) else 0.0
        R = tp[label] / (tp[label] + fn[label]) if (tp[label] + fn[label]) else 0.0
        F = 2 * P * R / (P + R) if (P + R) else 0.0
        per_class[label] = {
            "precision": round(P, 4),
            "recall": round(R, 4),
            "f1": round(F, 4),
            "support": support[label],
        }
        if support[label] > 0:
            f1_sum += F
            f1_count += 1
        correct += tp[label]

    return {
        "accuracy": round(correct / len(predictions), 4) if predictions else 0.0,
        "macro_f1": round(f1_sum / f1_count, 4) if f1_count else 0.0,
        "per_class": per_class,
    }


# ── Multi-label view (M4e dual-report harness) ──────────────────────────────


def _project_to_multi_label_rows(
    predictions: list[dict],
    field: str,
    scope: str,
) -> list[ColumnResult]:
    """Project single-label benchmark predictions to K=1 multi-label rows.

    Sprint 11 predictions are one-string-per-column; the multi-label
    metric helper consumes ``list[str]`` pairs. The projection is the
    identity that makes the two representations comparable:

    - ``scope='subtype'``: `true=[ground_truth]`, `pred=[predicted]`
      (entity-type granularity, ~25 labels)
    - ``scope='family'``: `true=[family_for(ground_truth)]`,
      `pred=[family_for(predicted)]` (family granularity, 13 labels)

    Empty predictions map to ``[]``; empty ground truth never happens
    in this benchmark (every shard carries a label) but the helper
    handles it correctly either way.

    Post-Sprint-13 the classifier will emit ``list[Finding]`` per
    column; at that point the pred list grows past K=1 and the
    multi-label metrics start to diverge from the single-label ones.
    Today, K=1 projections give the baseline against which future
    multi-label gains are measured.
    """
    rows: list[ColumnResult] = []
    for p in predictions:
        gt = p["ground_truth"] or ""
        pr = p.get(field) or ""
        if scope == "family":
            true_labels = [family_for(gt)] if gt else []
            pred_labels = [family_for(pr)] if pr else []
        elif scope == "subtype":
            true_labels = [gt] if gt else []
            pred_labels = [pr] if pr else []
        else:
            raise ValueError(f"unknown scope: {scope!r}")
        rows.append(
            ColumnResult(
                column_id=p["column_id"],
                pred=pred_labels,
                true=true_labels,
            )
        )
    return rows


def _compute_multi_label_metrics(predictions: list[dict], pred_field: str) -> dict:
    """Family + subtype multi-label metrics for one prediction field.

    Reported at both granularities so multi-label results stay
    apples-to-apples with the existing single-label tiers. Label spaces
    are the canonical ones from the taxonomy — using these (rather
    than "whatever labels showed up") gives stable Hamming loss across
    runs and a predictable label universe for M4d / M4b consumers.
    """
    family_rows = _project_to_multi_label_rows(predictions, pred_field, scope="family")
    subtype_rows = _project_to_multi_label_rows(predictions, pred_field, scope="subtype")
    return {
        "family": aggregate_multi_label(family_rows, label_space=FAMILIES),
        "subtype": aggregate_multi_label(subtype_rows, label_space=sorted(ENTITY_TYPE_TO_FAMILY.keys())),
    }


# ── M4b gate + per-branch surfaces ──────────────────────────────────────────


_SHAPE_LABELS: tuple[str, ...] = (
    "structured_single",
    "free_text_heterogeneous",
    "opaque_tokens",
)


def _compute_gate_accuracy(predictions: list[dict]) -> dict:
    """Router gate accuracy: confusion matrix + per-shape P/R/F1.

    Measures whether the shape router's predicted ``shape`` matches the
    ground-truth ``true_shape`` (derived from the M4b heuristic). This
    is the first of the three M4b surfaces — does the router route
    columns to the correct branch? Orthogonal to whether the downstream
    cascade then classifies the column correctly.

    Columns where the router emitted no shape (``shape is None``) are
    counted under a synthetic ``"no_shape"`` predicted class so the total
    always balances against ``n_shards``.
    """
    confusion: dict[str, dict[str, int]] = {
        true: {pred: 0 for pred in (*_SHAPE_LABELS, "no_shape")} for true in _SHAPE_LABELS
    }
    per_true: dict[str, int] = {true: 0 for true in _SHAPE_LABELS}
    per_pred: dict[str, int] = {pred: 0 for pred in (*_SHAPE_LABELS, "no_shape")}

    for p in predictions:
        true = p.get("true_shape")
        pred = p.get("shape") or "no_shape"
        if true not in _SHAPE_LABELS:
            continue
        if pred not in confusion[true]:
            continue
        confusion[true][pred] += 1
        per_true[true] += 1
        per_pred[pred] += 1

    per_shape: dict[str, dict] = {}
    for shape in _SHAPE_LABELS:
        tp = confusion[shape][shape]
        fn = per_true[shape] - tp
        fp = per_pred[shape] - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_shape[shape] = {
            "support_true": per_true[shape],
            "support_pred": per_pred[shape],
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    total_matched = sum(confusion[s][s] for s in _SHAPE_LABELS)
    total_rows = sum(per_true[s] for s in _SHAPE_LABELS)
    overall_accuracy = total_matched / total_rows if total_rows > 0 else 0.0

    return {
        "overall_accuracy": round(overall_accuracy, 4),
        "n_rows_scored": total_rows,
        "n_rows_no_shape": per_pred["no_shape"],
        "confusion": confusion,
        "per_shape": per_shape,
    }


def _compute_per_branch_accuracy(predictions: list[dict], pred_field: str) -> dict:
    """Per-branch downstream accuracy (oracle-routed by true_shape).

    For each shape, select shards whose ground-truth shape is that
    branch, then score the cascade's output with a branch-appropriate
    metric:

      * ``structured_single``: family-level cross-family rate + macro F1
        (same as the tier 1 metric for this subset — one engine suffices).
      * ``free_text_heterogeneous``: multi-label family metric — since
        the benchmark corpus's heterogeneous shards are scanner corpus
        shards with a single ground_truth, micro-F1 and accuracy are
        equivalent here; the multi-label surface is the shape the metric
        will take at scale when per-value GLiNER lands.
      * ``opaque_tokens``: binary "did the cascade correctly classify
        the column's entity family" (OPAQUE_SECRET / CRYPTO families
        are the expected predictions).

    The oracle routing is the distinguishing design choice — we score
    per-branch IGNORING router errors. A low per-branch number means
    the branch's cascade logic is weak; a high per-branch number with a
    low end-to-end number means the router is the bottleneck.
    """
    branches: dict[str, dict] = {}

    for shape in _SHAPE_LABELS:
        subset = [p for p in predictions if p.get("true_shape") == shape]
        if not subset:
            branches[shape] = {"n_shards": 0, "note": "no shards with this true_shape in the corpus"}
            continue

        # Shared Tier 1 family metric — applies cleanly for structured_single,
        # informative for the others as a baseline reading.
        family_metric = _compute_family_metrics(subset, pred_field)

        branches[shape] = {
            "n_shards": len(subset),
            "family": {
                "cross_family_rate": family_metric.get("cross_family_rate"),
                "cross_family_rate_emitted": family_metric.get("cross_family_rate_emitted"),
                "family_macro_f1": family_metric.get("family_macro_f1"),
                "n_shards_emitted": family_metric.get("n_shards_emitted"),
            },
        }

    return branches


def _compare_to(current: dict, previous_path: Path) -> dict:
    """Produce a delta summary against a previously-saved summary JSON."""
    try:
        previous = json.loads(previous_path.read_text())
    except FileNotFoundError:
        return {"error": f"previous summary not found: {previous_path}"}
    except json.JSONDecodeError as e:
        return {"error": f"previous summary not valid JSON: {e}"}

    deltas: dict = {}
    for tier in ("live", "shadow"):
        deltas[tier] = {}
        for split in ("overall", "named", "blind"):
            cur_tier1 = current.get(tier, {}).get(split, {}).get("family", {})
            prev_tier1 = previous.get(tier, {}).get(split, {}).get("family", {})
            if cur_tier1 and prev_tier1:
                deltas[tier][split] = {
                    "cross_family_rate": round(
                        cur_tier1.get("cross_family_rate", 0) - prev_tier1.get("cross_family_rate", 0),
                        4,
                    ),
                    "family_macro_f1": round(
                        cur_tier1.get("family_macro_f1", 0) - prev_tier1.get("family_macro_f1", 0),
                        4,
                    ),
                    "cross_family_rate_emitted": round(
                        cur_tier1.get("cross_family_rate_emitted", 0) - prev_tier1.get("cross_family_rate_emitted", 0),
                        4,
                    ),
                    "router_suppression_rate": round(
                        cur_tier1.get("router_suppression_rate", 0) - prev_tier1.get("router_suppression_rate", 0),
                        4,
                    ),
                }
    return deltas


# ── Entry point ─────────────────────────────────────────────────────────────


def _print_report(summary: dict) -> None:
    live_overall = summary["live"]["overall"]["family"]
    shadow_overall = summary["shadow"]["overall"]["family"]
    print(f"\n{'=' * 72}", file=sys.stderr)  # noqa: T201
    print("FAMILY-LEVEL ACCURACY BENCHMARK", file=sys.stderr)  # noqa: T201
    print(f"{'=' * 72}", file=sys.stderr)  # noqa: T201
    print(f"N shards:             {summary['n_shards']}", file=sys.stderr)  # noqa: T201
    print("", file=sys.stderr)  # noqa: T201
    print("LIVE path:", file=sys.stderr)  # noqa: T201
    print(  # noqa: T201
        f"  cross_family_rate:  {live_overall['cross_family_rate']:.4f}  "
        f"({live_overall['cross_family_errors']}/{live_overall['n_shards']})",
        file=sys.stderr,
    )
    print(f"  family_macro_f1:    {live_overall['family_macro_f1']:.4f}", file=sys.stderr)  # noqa: T201
    print(  # noqa: T201
        f"  within_family_mislabels: {live_overall['within_family_mislabels']}",
        file=sys.stderr,
    )
    print("", file=sys.stderr)  # noqa: T201
    print("SHADOW path (meta-classifier):", file=sys.stderr)  # noqa: T201
    print(  # noqa: T201
        f"  cross_family_rate:  {shadow_overall['cross_family_rate']:.4f}  "
        f"({shadow_overall['cross_family_errors']}/{shadow_overall['n_shards']})",
        file=sys.stderr,
    )
    print(f"  family_macro_f1:    {shadow_overall['family_macro_f1']:.4f}", file=sys.stderr)  # noqa: T201
    print(  # noqa: T201
        f"  within_family_mislabels: {shadow_overall['within_family_mislabels']}",
        file=sys.stderr,
    )
    print(  # noqa: T201
        f"  cross_family_rate_emitted:  {shadow_overall['cross_family_rate_emitted']:.4f}  "
        f"(v5 accuracy excl. router-suppressed; {shadow_overall['n_shards_emitted']} shards)",
        file=sys.stderr,
    )
    print(  # noqa: T201
        f"  family_macro_f1_emitted:    {shadow_overall['family_macro_f1_emitted']:.4f}",
        file=sys.stderr,
    )
    print(  # noqa: T201
        f"  router_suppression_rate:    {shadow_overall['router_suppression_rate']:.4f}  "
        f"({shadow_overall['router_suppressed_count']}/{shadow_overall['n_shards']} shards)",
        file=sys.stderr,
    )
    if shadow_overall.get("suppressed_by_shape"):
        by_shape = ", ".join(f"{k}={v}" for k, v in sorted(shadow_overall["suppressed_by_shape"].items()))
        print(f"  suppressed by shape:  {by_shape}", file=sys.stderr)  # noqa: T201
    print("", file=sys.stderr)  # noqa: T201
    print(  # noqa: T201
        "Per-family F1 (shadow, sorted ascending — lowest is the constraint):",
        file=sys.stderr,
    )
    per_fam = shadow_overall["per_family"]
    rows = sorted(per_fam.items(), key=lambda kv: kv[1]["f1"])
    for name, m in rows:
        print(  # noqa: T201
            f"  {name:15s} N={m['support']:>5d}  P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="predictions.jsonl output path")
    parser.add_argument("--summary", type=Path, required=True, help="summary.json output path")
    parser.add_argument("--limit", type=int, default=0, help="Limit shards (0 = all)")
    parser.add_argument("--seed", type=int, default=20260412, help="Shard builder RNG seed")
    parser.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="Optional previous summary.json to diff against; produces a deltas section in the new summary.",
    )
    args = parser.parse_args(argv)

    print(f"Building synthetic pool and shards (seed={args.seed})...", file=sys.stderr)  # noqa: T201
    profile = load_profile("standard")
    synthetic_pool = _build_synthetic_pool()
    shards = build_shards(synthetic_pool=synthetic_pool, seed=args.seed)
    if args.limit:
        shards = shards[: args.limit]
    print(f"Classifying {len(shards)} shards...", file=sys.stderr)  # noqa: T201

    t_start = time.monotonic()
    predictions = []
    with args.out.open("w") as handle:
        for i, shard in enumerate(shards):
            rec = _run_one_shard(shard, profile)
            handle.write(json.dumps(rec) + "\n")
            predictions.append(rec)
            if (i + 1) % 500 == 0:
                elapsed = time.monotonic() - t_start
                print(f"  {i + 1}/{len(shards)} ({elapsed:.1f}s)", file=sys.stderr)  # noqa: T201

    elapsed = time.monotonic() - t_start
    print(f"Finished {len(shards)} shards in {elapsed:.1f}s", file=sys.stderr)  # noqa: T201

    def _build_tiered(preds: list[dict], field: str) -> dict:
        return {
            "family": _compute_family_metrics(preds, field),
            "subtype": _compute_subtype_metrics(preds, field),
            # M4e dual-report: multi-label view of the same predictions
            # at both family and subtype scopes. For today's K=1
            # projection the multi-label subset_accuracy converges to
            # the single-label accuracy; the divergence is where
            # Sprint 13's router earns its keep.
            "multi_label": _compute_multi_label_metrics(preds, field),
        }

    def _split(preds: list[dict]) -> dict:
        out: dict[str, dict] = {
            "overall": {
                "live": _build_tiered(preds, "predicted"),
                "shadow": _build_tiered(preds, "shadow_predicted"),
            }
        }
        for mode in ("named", "blind"):
            subset = [p for p in preds if p["mode"] == mode]
            if subset:
                out[f"{mode}_live"] = _build_tiered(subset, "predicted")
                out[f"{mode}_shadow"] = _build_tiered(subset, "shadow_predicted")
        return out

    # Compose the summary with the shape expected by the report
    # printer and by downstream diff consumers.
    summary: dict = {
        "n_shards": len(predictions),
        "n_families": len(FAMILIES),
        "live": {
            "overall": _build_tiered(predictions, "predicted"),
        },
        "shadow": {
            "overall": _build_tiered(predictions, "shadow_predicted"),
        },
        # M4b: router gate accuracy + per-branch downstream accuracy.
        # gate_accuracy measures whether shape routing is correct;
        # per_branch_accuracy measures whether each branch's cascade
        # classifies correctly IGNORING router errors (oracle routing
        # by true_shape). Mismatch between the two decomposes end-to-end
        # errors into routing vs downstream failure modes.
        "gate_accuracy": _compute_gate_accuracy(predictions),
        "per_branch_accuracy": {
            "live": _compute_per_branch_accuracy(predictions, "predicted"),
            "shadow": _compute_per_branch_accuracy(predictions, "shadow_predicted"),
        },
    }
    for mode in ("named", "blind"):
        subset = [p for p in predictions if p["mode"] == mode]
        if subset:
            summary["live"][mode] = _build_tiered(subset, "predicted")
            summary["shadow"][mode] = _build_tiered(subset, "shadow_predicted")

    if args.compare_to is not None:
        summary["delta_vs_previous"] = _compare_to(summary, args.compare_to)

    args.summary.write_text(json.dumps(summary, indent=2))
    _print_report(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
