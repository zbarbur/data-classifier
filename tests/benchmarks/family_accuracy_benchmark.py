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
from tests.benchmarks.meta_classifier.shard_builder import build_shards

try:
    from data_classifier.events.types import MetaClassifierEvent
except ImportError:  # pragma: no cover — older checkouts
    MetaClassifierEvent = None  # type: ignore[assignment]


# ── Per-shard classification ────────────────────────────────────────────────


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
    }


# ── Metric computation ──────────────────────────────────────────────────────


def _compute_family_metrics(predictions: list[dict], pred_field: str) -> dict:
    """Family-level Tier 1 metrics: cross-family rate + macro P/R/F1."""
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

    return {
        "cross_family_errors": cross_family,
        "cross_family_rate": round(cross_family / len(predictions), 4) if predictions else 0.0,
        "within_family_mislabels": within_family_mislabel,
        "n_shards": len(predictions),
        "family_macro_f1": round(f1_sum / f1_count, 4) if f1_count else 0.0,
        "per_family": per_family,
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
                }
    return deltas


# ── Entry point ─────────────────────────────────────────────────────────────


def _print_report(summary: dict) -> None:
    live_overall = summary["live"]["overall"]["family"]
    shadow_overall = summary["shadow"]["overall"]["family"]
    print(f"\n{'=' * 72}", file=sys.stderr)
    print("FAMILY-LEVEL ACCURACY BENCHMARK", file=sys.stderr)
    print(f"{'=' * 72}", file=sys.stderr)
    print(f"N shards:             {summary['n_shards']}", file=sys.stderr)
    print("", file=sys.stderr)
    print("LIVE path:", file=sys.stderr)
    print(
        f"  cross_family_rate:  {live_overall['cross_family_rate']:.4f}  "
        f"({live_overall['cross_family_errors']}/{live_overall['n_shards']})",
        file=sys.stderr,
    )
    print(f"  family_macro_f1:    {live_overall['family_macro_f1']:.4f}", file=sys.stderr)
    print(
        f"  within_family_mislabels: {live_overall['within_family_mislabels']}",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("SHADOW path (meta-classifier):", file=sys.stderr)
    print(
        f"  cross_family_rate:  {shadow_overall['cross_family_rate']:.4f}  "
        f"({shadow_overall['cross_family_errors']}/{shadow_overall['n_shards']})",
        file=sys.stderr,
    )
    print(f"  family_macro_f1:    {shadow_overall['family_macro_f1']:.4f}", file=sys.stderr)
    print(
        f"  within_family_mislabels: {shadow_overall['within_family_mislabels']}",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("Per-family F1 (shadow, sorted ascending — lowest is the constraint):", file=sys.stderr)
    per_fam = shadow_overall["per_family"]
    rows = sorted(per_fam.items(), key=lambda kv: kv[1]["f1"])
    for name, m in rows:
        print(
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

    print(f"Building synthetic pool and shards (seed={args.seed})...", file=sys.stderr)
    profile = load_profile("standard")
    synthetic_pool = _build_synthetic_pool()
    shards = build_shards(synthetic_pool=synthetic_pool, seed=args.seed)
    if args.limit:
        shards = shards[: args.limit]
    print(f"Classifying {len(shards)} shards...", file=sys.stderr)

    t_start = time.monotonic()
    predictions = []
    with args.out.open("w") as handle:
        for i, shard in enumerate(shards):
            rec = _run_one_shard(shard, profile)
            handle.write(json.dumps(rec) + "\n")
            predictions.append(rec)
            if (i + 1) % 500 == 0:
                elapsed = time.monotonic() - t_start
                print(f"  {i + 1}/{len(shards)} ({elapsed:.1f}s)", file=sys.stderr)

    elapsed = time.monotonic() - t_start
    print(f"Finished {len(shards)} shards in {elapsed:.1f}s", file=sys.stderr)

    def _build_tiered(preds: list[dict], field: str) -> dict:
        return {
            "family": _compute_family_metrics(preds, field),
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
