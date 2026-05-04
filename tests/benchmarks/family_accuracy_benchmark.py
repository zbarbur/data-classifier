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
from data_classifier.events.emitter import CallbackHandler, EventEmitter
from tests.benchmarks.meta_classifier.build_training_data import _build_synthetic_pool
from tests.benchmarks.meta_classifier.shard_builder import build_shards, verify_required_fixtures

try:
    from data_classifier.events.types import MetaClassifierEvent
except ImportError:  # pragma: no cover — older checkouts
    MetaClassifierEvent = None  # type: ignore[assignment]

try:
    from data_classifier.events.types import ColumnShapeEvent
except ImportError:  # pragma: no cover — older checkouts
    ColumnShapeEvent = None  # type: ignore[assignment]


# ── Per-shard classification ────────────────────────────────────────────────


def _top_finding(findings):
    if not findings:
        return None
    from data_classifier.core.taxonomy import specificity_for

    # Within-family specificity: prefer more specific entity types as primary.
    # Sort by (specificity DESC, confidence DESC) — same logic as
    # _apply_findings_limit in data_classifier/__init__.py.
    return max(findings, key=lambda f: (specificity_for(f.entity_type), f.confidence))


def _run_one_shard(shard, profile) -> dict:
    # One emitter per call keeps captured events bounded to this
    # column and avoids any need to reset shared state.
    captured: list = []
    emitter = EventEmitter()
    emitter.add_handler(CallbackHandler(lambda ev: captured.append(ev)))

    findings = classify_columns(
        [shard.column],
        profile,
        min_confidence=0.5,
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

    # Collect ALL findings for multi-label scoring — each finding's
    # entity_type, confidence, engine, and derived family.
    all_findings = [
        {
            "entity_type": f.entity_type,
            "confidence": round(f.confidence, 4),
            "engine": f.engine,
            "family": family_for(f.entity_type),
            "detection_type": f.detection_type,
            "display_name": f.display_name,
        }
        for f in findings
    ]

    return {
        "column_id": shard.column_id,
        "ground_truth": shard.ground_truth,
        "ground_truth_families": (
            shard.ground_truth_families if shard.ground_truth_families else [family_for(shard.ground_truth)]
        ),
        "mode": shard.mode,
        "corpus": shard.corpus,
        "source": shard.source,
        "predicted": top.entity_type if top else ("NEGATIVE" if shard.ground_truth == "NEGATIVE" else None),
        "confidence": round(top.confidence, 4) if top else 0.0,
        "category": top.category if top else None,
        "engine": top.engine if top else None,
        "findings": all_findings,
        "fired_engines": sorted({f.engine for f in findings}),
        "n_findings": len(findings),
        "shadow_predicted": shadow_entity,
        "shadow_confidence": shadow_confidence,
        "shadow_agrees_with_live": shadow_agreement,
        "shape": shape,
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


def _compute_multilabel_family_metrics(predictions: list[dict], pred_field: str) -> dict:
    """Multi-label family metrics: treat each family independently.

    Unlike single-label scoring (winner-takes-all), multi-label scoring
    considers ALL findings emitted by the cascade for each column. For
    each family F:
      - is_present(shard) := F is in ground_truth_families (multi-label GT)
      - is_predicted(shard) := ANY finding in the shard has family F
      - TP(F) := shards where is_predicted AND is_present
      - FP(F) := shards where is_predicted AND NOT is_present
      - FN(F) := shards where is_present AND NOT is_predicted

    When ``ground_truth_families`` is available on the prediction record
    (populated by the shard builder's structural presence scanner), the
    ground truth is multi-label — e.g. a CREDENTIAL shard that also
    contains URLs will have ``ground_truth_families = ["CREDENTIAL", "URL"]``.
    Predicting URL on such a shard is a TP for URL, not an FP.

    Falls back to single-label ground truth when ``ground_truth_families``
    is absent (backwards compatibility with older prediction files).
    """
    # Determine which families are predicted per shard from findings
    # For the "predicted" field, use the findings list directly.
    # For the "shadow_predicted" field, fall back to the single prediction
    # (shadow doesn't have a findings list).
    use_findings = pred_field == "predicted"

    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    support: dict[str, int] = defaultdict(int)

    for p in predictions:
        # Multi-label ground truth: use ground_truth_families when
        # available, fall back to single-label family_for(ground_truth).
        gt_families_raw = p.get("ground_truth_families")
        if gt_families_raw:
            gt_families = set(gt_families_raw)
        else:
            gt_fam = family_for(p["ground_truth"])
            if not gt_fam:
                continue
            gt_families = {gt_fam}

        if not gt_families:
            continue

        # Collect predicted families for this shard.
        # When no findings are emitted on a shard whose ground truth
        # includes NEGATIVE, treat silence as an implicit NEGATIVE TP.
        # On non-NEGATIVE shards, silence is a miss for that family
        # (already scored as FN) — it should NOT also count as a
        # NEGATIVE FP (double-penalizing).
        if use_findings and "findings" in p:
            predicted_families = {f["family"] for f in p["findings"] if f.get("family")}
            if not predicted_families and "NEGATIVE" in gt_families:
                predicted_families = {"NEGATIVE"}
        else:
            pr_sub = p.get(pred_field) or ""
            pr_fam = family_for(pr_sub) if pr_sub else ""
            predicted_families = {pr_fam} if pr_fam else set()

        # Score each family independently
        all_families = gt_families | predicted_families
        for fam in all_families:
            is_present = fam in gt_families
            is_predicted = fam in predicted_families

            if is_present:
                support[fam] += 1

            if is_predicted and is_present:
                tp[fam] += 1
            elif is_predicted and not is_present:
                fp[fam] += 1
            elif not is_predicted and is_present:
                fn[fam] += 1

    per_family: dict[str, dict] = {}
    f1_sum = 0.0
    f1_count = 0
    for fam in sorted(set(support) | set(fp)):
        if not fam:
            continue
        p_val = tp[fam] / (tp[fam] + fp[fam]) if (tp[fam] + fp[fam]) else 0.0
        r_val = tp[fam] / (tp[fam] + fn[fam]) if (tp[fam] + fn[fam]) else 0.0
        f_val = 2 * p_val * r_val / (p_val + r_val) if (p_val + r_val) else 0.0
        per_family[fam] = {
            "precision": round(p_val, 4),
            "recall": round(r_val, 4),
            "f1": round(f_val, 4),
            "support": support[fam],
            "tp": tp[fam],
            "fp": fp[fam],
            "fn": fn[fam],
        }
        if support[fam] > 0:
            f1_sum += f_val
            f1_count += 1

    return {
        "multilabel_macro_f1": round(f1_sum / f1_count, 4) if f1_count else 0.0,
        "per_family_multilabel": per_family,
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


def _compute_joint_miss_metrics(predictions: list[dict]) -> dict:
    """System-level joint miss metric — the honest sprint quality gate.

    A "joint miss" is a shard where neither path's predicted family lands
    in the multi-label ground truth. Per the Sprint 17 router-suppression
    decomposition memo (``docs/research/meta_classifier/
    sprint17_router_suppression_decomposition.md``), this is the metric
    that should drive the sprint completion gate, replacing
    ``shadow.overall.family.cross_family_rate`` which mostly tracks
    router-suppression policy rather than system quality.

    Logic per shard:
      * SHADOW is "right" iff the meta-classifier emitted (router did NOT
        suppress) AND ``family_for(shadow_predicted)`` ∈ ground-truth
        families. A router-suppressed shadow is treated as "no
        prediction" — i.e. wrong on its own merits.
      * LIVE is "right" iff ``family_for(predicted)`` ∈ ground-truth
        families.
      * A shard is a joint miss iff neither is right.

    NEGATIVE-ground-truth shards are excluded from the joint miss
    numerator and denominator. For NEGATIVE, "predict nothing" is the
    correct outcome but the symmetric metric counts it as wrong; the
    Sprint 17 memo §5 documents the artifact and recommends excluding.
    """
    n_total = 0
    n_negative_excluded = 0
    joint_miss = 0
    live_only_miss = 0
    shadow_only_miss = 0
    both_correct = 0
    joint_miss_by_family: dict[str, int] = defaultdict(int)
    joint_miss_by_shape: dict[str, int] = defaultdict(int)

    for p in predictions:
        gt = p.get("ground_truth") or ""
        if gt == "NEGATIVE":
            n_negative_excluded += 1
            continue
        n_total += 1

        gt_fams = set(p.get("ground_truth_families") or [family_for(gt)])
        gt_fams.discard("")

        live_pred = p.get("predicted") or ""
        live_fam = family_for(live_pred) if live_pred else ""
        live_right = bool(live_fam) and live_fam in gt_fams

        if p.get("shadow_suppressed_by_router", False):
            shadow_right = False
        else:
            shadow_pred = p.get("shadow_predicted") or ""
            shadow_fam = family_for(shadow_pred) if shadow_pred else ""
            shadow_right = bool(shadow_fam) and shadow_fam in gt_fams

        if live_right and shadow_right:
            both_correct += 1
        elif live_right:
            shadow_only_miss += 1
        elif shadow_right:
            live_only_miss += 1
        else:
            joint_miss += 1
            joint_miss_by_family[family_for(gt)] += 1
            shape = p.get("shape")
            if shape:
                joint_miss_by_shape[shape] += 1

    return {
        "joint_miss_count": joint_miss,
        "joint_miss_rate": round(joint_miss / n_total, 4) if n_total else 0.0,
        "n_shards_excluding_negative": n_total,
        "n_negative_excluded": n_negative_excluded,
        "live_only_miss_count": live_only_miss,
        "shadow_only_miss_count": shadow_only_miss,
        "both_correct_count": both_correct,
        "joint_miss_by_family": dict(joint_miss_by_family),
        "joint_miss_by_shape": dict(joint_miss_by_shape),
    }


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

    # System-level joint miss delta — the headline gate metric.
    cur_sys = current.get("system", {}).get("overall", {})
    prev_sys = previous.get("system", {}).get("overall", {})
    if cur_sys and prev_sys:
        deltas["system"] = {
            "overall": {
                "joint_miss_rate": round(
                    cur_sys.get("joint_miss_rate", 0) - prev_sys.get("joint_miss_rate", 0),
                    4,
                ),
                "joint_miss_count": cur_sys.get("joint_miss_count", 0) - prev_sys.get("joint_miss_count", 0),
            }
        }
    return deltas


# ── Entry point ─────────────────────────────────────────────────────────────


def _print_report(summary: dict) -> None:
    live_overall = summary["live"]["overall"]["family"]
    live_ml = summary["live"]["overall"]["family_multilabel"]
    shadow_overall = summary["shadow"]["overall"]["family"]
    shadow_ml = summary["shadow"]["overall"]["family_multilabel"]
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
    print(f"  family_macro_f1:          {live_overall['family_macro_f1']:.4f}  (single-label)", file=sys.stderr)  # noqa: T201
    print(f"  multilabel_macro_f1:      {live_ml['multilabel_macro_f1']:.4f}  (multi-label)", file=sys.stderr)  # noqa: T201
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
    print(f"  family_macro_f1:          {shadow_overall['family_macro_f1']:.4f}  (single-label)", file=sys.stderr)  # noqa: T201
    print(f"  multilabel_macro_f1:      {shadow_ml['multilabel_macro_f1']:.4f}  (multi-label)", file=sys.stderr)  # noqa: T201
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

    # ── SYSTEM-level joint miss (sprint gate metric) ─────────────────────
    system_overall = summary.get("system", {}).get("overall", {})
    if system_overall:
        print("SYSTEM (joint miss across LIVE + SHADOW, NEGATIVE excluded):", file=sys.stderr)  # noqa: T201
        print(  # noqa: T201
            f"  joint_miss_rate:    {system_overall['joint_miss_rate']:.4f}  "
            f"({system_overall['joint_miss_count']}/{system_overall['n_shards_excluding_negative']} shards)",
            file=sys.stderr,
        )
        print(  # noqa: T201
            f"  live_only_miss:     {system_overall['live_only_miss_count']}  (LIVE wrong, SHADOW caught it)",
            file=sys.stderr,
        )
        print(  # noqa: T201
            f"  shadow_only_miss:   {system_overall['shadow_only_miss_count']}  "
            f"(SHADOW wrong/suppressed, LIVE caught it)",
            file=sys.stderr,
        )
        if system_overall.get("joint_miss_by_family"):
            by_fam = ", ".join(
                f"{k}={v}" for k, v in sorted(system_overall["joint_miss_by_family"].items(), key=lambda kv: -kv[1])
            )
            print(f"  joint miss by family: {by_fam}", file=sys.stderr)  # noqa: T201
        if system_overall.get("joint_miss_by_shape"):
            by_shape = ", ".join(
                f"{k}={v}" for k, v in sorted(system_overall["joint_miss_by_shape"].items(), key=lambda kv: -kv[1])
            )
            print(f"  joint miss by shape:  {by_shape}", file=sys.stderr)  # noqa: T201
        print("", file=sys.stderr)  # noqa: T201

    # ── Per-family comparison table: single-label vs multi-label ──────
    print(  # noqa: T201
        "Per-family F1 — single-label vs multi-label (live, sorted ascending):",
        file=sys.stderr,
    )
    sl_fam = live_overall["per_family"]
    ml_fam = live_ml["per_family_multilabel"]
    all_fams = sorted(set(sl_fam) | set(ml_fam))
    # Sort by single-label F1 ascending
    all_fams.sort(key=lambda f: sl_fam.get(f, {}).get("f1", 0.0))
    print(  # noqa: T201
        f"  {'Family':15s} {'N':>5s}  {'SL-P':>5s} {'SL-R':>5s} {'SL-F1':>5s}  "
        f"{'ML-P':>5s} {'ML-R':>5s} {'ML-F1':>5s}  {'delta':>6s}",
        file=sys.stderr,
    )
    for fam in all_fams:
        sl = sl_fam.get(fam, {})
        ml = ml_fam.get(fam, {})
        sl_f1 = sl.get("f1", 0.0)
        ml_f1 = ml.get("f1", 0.0)
        delta = ml_f1 - sl_f1
        print(  # noqa: T201
            f"  {fam:15s} N={sl.get('support', 0):>5d}  "
            f"{sl.get('precision', 0.0):.3f} {sl.get('recall', 0.0):.3f} {sl_f1:.3f}  "
            f"{ml.get('precision', 0.0):.3f} {ml.get('recall', 0.0):.3f} {ml_f1:.3f}  "
            f"{delta:+.3f}",
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

    verify_required_fixtures()
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
            "family_multilabel": _compute_multilabel_family_metrics(preds, field),
            "subtype": _compute_subtype_metrics(preds, field),
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
        "system": {
            "overall": _compute_joint_miss_metrics(predictions),
        },
    }
    for mode in ("named", "blind"):
        subset = [p for p in predictions if p["mode"] == mode]
        if subset:
            summary["live"][mode] = _build_tiered(subset, "predicted")
            summary["shadow"][mode] = _build_tiered(subset, "shadow_predicted")
            summary["system"][mode] = _compute_joint_miss_metrics(subset)

    if args.compare_to is not None:
        summary["delta_vs_previous"] = _compare_to(summary, args.compare_to)

    args.summary.write_text(json.dumps(summary, indent=2))
    _print_report(summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
