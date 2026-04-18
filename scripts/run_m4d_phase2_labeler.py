"""Driver for M4d Phase 2 — router-labeler vs M4c human gold set.

Runs ``llm_labeler_router.label_gold_set_via_router()``, scores predictions
via M4a's ``aggregate_multi_label`` both overall and per-shape, writes
per-column predictions + a markdown result memo.

Usage::

    export ANTHROPIC_API_KEY=...
    python scripts/run_m4d_phase2_labeler.py

    # Smoke-test on 3 rows first:
    python scripts/run_m4d_phase2_labeler.py --limit 3

    # Compare against Phase 1 baseline predictions (per-row Jaccard delta):
    python scripts/run_m4d_phase2_labeler.py \\
        --compare-to docs/experiments/meta_classifier/runs/20260417-m4d-phase1-labeler-validation/predictions.jsonl

Writes:
  <out_dir>/result.md          — per-branch + overall Jaccard, gate verdict,
                                 Phase 1 regression check, verbatim per-branch prompts
  <out_dir>/predictions.jsonl  — per-column predictions + telemetry (same schema as Phase 1)

Gate (from queue.md M4d Phase 2 spec):
  * Combined macro Jaccard ≥ 0.8 on M4c gold set
  * Per-branch Jaccard ≥ 0.7 on each of the three branches
  * Zero regression on rows Phase 1 matched perfectly (29/50)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from tests.benchmarks.meta_classifier.llm_labeler import GOLD_SET_PATH, MODEL
from tests.benchmarks.meta_classifier.llm_labeler_router import (
    HETEROGENEOUS_INSTRUCTIONS,
    OPAQUE_TOKENS_INSTRUCTIONS,
    STRUCTURED_SINGLE_INSTRUCTIONS,
    VALID_SHAPES,
    LabelerCall,
    build_system_prompt_for_shape,
    label_gold_set_via_router,
)
from tests.benchmarks.meta_classifier.multi_label_metrics import (
    ColumnResult,
    aggregate_multi_label,
)

DEFAULT_OUT_DIR = (
    Path(__file__).resolve().parent.parent / "docs/experiments/meta_classifier/runs/20260418-m4d-phase2-router"
)


def _fmt_labels(labels: list[str]) -> str:
    return "[" + ", ".join(labels) + "]" if labels else "[]"


def _jaccard(pred: list[str], true: list[str]) -> float:
    p, t = set(pred), set(true)
    if not p and not t:
        return 1.0
    union = p | t
    return len(p & t) / len(union) if union else 1.0


def _shape_for_column(column_id: str, gold_rows: dict[str, dict]) -> str | None:
    row = gold_rows.get(column_id)
    return row.get("true_shape") if row else None


def _per_column_disagreement_rows(
    calls: list[LabelerCall],
    gold_rows: dict[str, dict],
) -> list[tuple[str, str, list[str], list[str], list[str], list[str], float]]:
    rows = []
    for call in calls:
        pred_set, true_set = set(call.pred), set(call.true)
        if pred_set == true_set:
            continue
        fp = sorted(pred_set - true_set)
        fn = sorted(true_set - pred_set)
        shape = _shape_for_column(call.column_id, gold_rows) or "unknown"
        rows.append((call.column_id, shape, call.pred, call.true, fp, fn, _jaccard(call.pred, call.true)))
    rows.sort(key=lambda r: r[6])
    return rows


def _per_shape_metrics(
    calls: list[LabelerCall],
    gold_rows: dict[str, dict],
) -> dict[str, dict]:
    by_shape: dict[str, list[ColumnResult]] = defaultdict(list)
    for call in calls:
        shape = _shape_for_column(call.column_id, gold_rows) or "unknown"
        by_shape[shape].append(call.to_column_result())
    return {shape: aggregate_multi_label(results) for shape, results in by_shape.items()}


def _load_phase1_baseline(path: Path) -> dict[str, list[str]]:
    preds = {}
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            preds[obj["column_id"]] = obj.get("pred", [])
    return preds


def _phase1_regressions(
    calls: list[LabelerCall],
    phase1_preds: dict[str, list[str]],
) -> list[tuple[str, list[str], list[str], list[str]]]:
    """Rows Phase 1 matched perfectly but Phase 2 breaks."""
    regressions = []
    for call in calls:
        true_set = set(call.true)
        p1 = phase1_preds.get(call.column_id)
        if p1 is None:
            continue
        if set(p1) == true_set and set(call.pred) != true_set:
            regressions.append((call.column_id, p1, call.pred, call.true))
    return regressions


def _write_predictions_jsonl(out_path: Path, calls: list[LabelerCall]) -> None:
    with out_path.open("w") as f:
        for call in calls:
            f.write(json.dumps(call.to_jsonl_dict(), ensure_ascii=False) + "\n")


def _write_memo(
    out_path: Path,
    calls: list[LabelerCall],
    overall_metrics: dict,
    per_shape_metrics: dict[str, dict],
    gold_rows: dict[str, dict],
    run_meta: dict,
    phase1_preds: dict[str, list[str]] | None,
) -> None:
    disagreements = _per_column_disagreement_rows(calls, gold_rows)
    total_in = sum(c.input_tokens for c in calls)
    total_out = sum(c.output_tokens for c in calls)
    total_cache_read = sum(c.cache_read_input_tokens for c in calls)
    total_cache_create = sum(c.cache_creation_input_tokens for c in calls)
    errors = [c for c in calls if c.error]
    unknowns = [(c.column_id, c.unknown_labels) for c in calls if c.unknown_labels]

    lines: list[str] = []
    lines.append("# M4d Phase 2 — router-labeler validation vs M4c gold set\n")
    lines.append(f"**Run date:** {run_meta['timestamp']}\n")
    lines.append(f"**Model:** `{run_meta['model']}`\n")
    lines.append(f"**Gold-set rows scored:** {len(calls)} (human_reviewed only)\n")
    lines.append(f"**API errors:** {len(errors)}\n")
    lines.append(f"**Invalid-label responses:** {len(unknowns)} columns emitted unknown label strings\n\n")

    # Gate evaluation
    overall_jaccard = overall_metrics.get("jaccard_macro", 0.0)
    per_shape_jaccards = {s: m.get("jaccard_macro", 0.0) for s, m in per_shape_metrics.items()}
    combined_pass = overall_jaccard >= 0.8
    per_branch_pass = all(j >= 0.7 for j in per_shape_jaccards.values())

    lines.append("## Quality gates\n")
    lines.append(f"- **Combined macro Jaccard:** `{overall_jaccard:.4f}` (gate: ≥ 0.8) → ")
    lines.append("✅ PASS\n" if combined_pass else "❌ FAIL\n")
    lines.append(f"- **Per-branch ≥ 0.7:** → {'✅ PASS' if per_branch_pass else '❌ FAIL'}\n")
    for shape in sorted(per_shape_jaccards.keys()):
        j = per_shape_jaccards[shape]
        verdict = "✅" if j >= 0.7 else "❌"
        n = per_shape_metrics[shape].get("n_columns", 0)
        lines.append(f"  - `{shape}` (n={n}): `{j:.4f}` {verdict}\n")

    # Phase 1 regression check
    if phase1_preds is not None:
        regressions = _phase1_regressions(calls, phase1_preds)
        reg_pass = len(regressions) == 0
        lines.append(f"- **Zero regression on Phase 1 perfect rows:** → {'✅ PASS' if reg_pass else '❌ FAIL'}\n")
        if regressions:
            lines.append(f"  - {len(regressions)} rows that Phase 1 matched perfectly now fail:\n")
            for cid, p1, p2, true in regressions:
                lines.append(
                    f"    - `{cid}`: phase1={_fmt_labels(p1)} → phase2={_fmt_labels(p2)} (true={_fmt_labels(true)})\n"
                )
    lines.append("\n")

    # Per-shape metrics
    lines.append("## Per-branch metrics\n")
    lines.append("| Shape | n | Jaccard | micro F1 | macro F1 | subset_acc |\n")
    lines.append("|---|---|---|---|---|---|\n")
    for shape in sorted(per_shape_metrics.keys()):
        m = per_shape_metrics[shape]
        lines.append(
            f"| `{shape}` | {m.get('n_columns', 0)} | "
            f"`{m.get('jaccard_macro', 0.0):.4f}` | "
            f"`{m.get('micro_f1', 0.0):.4f}` | "
            f"`{m.get('macro_f1', 0.0):.4f}` | "
            f"`{m.get('subset_accuracy', 0.0):.4f}` |\n"
        )
    lines.append("\n")

    # Overall metrics table
    lines.append("## Overall metrics\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    for k in (
        "jaccard_macro",
        "micro_precision",
        "micro_recall",
        "micro_f1",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "hamming_loss",
        "subset_accuracy",
        "n_columns",
        "n_columns_empty_pred",
        "n_columns_empty_true",
    ):
        if k in overall_metrics:
            v = overall_metrics[k]
            v_str = f"`{v:.4f}`" if isinstance(v, float) else f"`{v}`"
            lines.append(f"| {k} | {v_str} |\n")
    lines.append("\n")

    # Phase 1 comparison (overall)
    if phase1_preds is not None:
        phase1_jaccards = [_jaccard(phase1_preds[c.column_id], c.true) for c in calls if c.column_id in phase1_preds]
        if phase1_jaccards:
            phase1_macro = sum(phase1_jaccards) / len(phase1_jaccards)
            delta = overall_jaccard - phase1_macro
            lines.append("## Phase 1 → Phase 2 delta\n")
            lines.append(
                f"- Phase 1 v1 macro Jaccard on the same 50 rows: `{phase1_macro:.4f}`\n"
                f"- Phase 2 macro Jaccard: `{overall_jaccard:.4f}`\n"
                f"- Delta: `{delta:+.4f}` {'(improvement)' if delta > 0 else '(regression)' if delta < 0 else '(no change)'}\n\n"
            )

    # Cost telemetry
    lines.append("## Usage + cost telemetry\n")
    lines.append(f"- Input tokens (uncached): **{total_in:,}**\n")
    lines.append(f"- Output tokens: **{total_out:,}**\n")
    lines.append(f"- Cache read tokens: **{total_cache_read:,}** (served at ~0.1× price)\n")
    lines.append(f"- Cache creation tokens: **{total_cache_create:,}** (paid at 1.25× price)\n")
    cache_pct = (total_cache_read / max(total_cache_read + total_in, 1)) * 100
    lines.append(f"- Cache-hit rate on input: **{cache_pct:.1f}%**\n")
    cost_in = total_in * 5e-6
    cost_out = total_out * 25e-6
    cost_cache_read = total_cache_read * 5e-6 * 0.1
    cost_cache_create = total_cache_create * 5e-6 * 1.25
    total_cost = cost_in + cost_out + cost_cache_read + cost_cache_create
    lines.append(f"- **Estimated total cost:** ${total_cost:.4f}\n\n")

    if unknowns:
        lines.append("## Prompt-compliance failures (unknown label strings)\n")
        lines.append("| column_id | unknown labels |\n|---|---|\n")
        for cid, labels in unknowns:
            lines.append(f"| `{cid}` | `{', '.join(labels)}` |\n")
        lines.append("\n")

    if errors:
        lines.append("## API errors\n")
        lines.append("| column_id | error |\n|---|---|\n")
        for call in errors:
            lines.append(f"| `{call.column_id}` | `{call.error}` |\n")
        lines.append("\n")

    # Per-column disagreements (with shape column)
    lines.append("## Per-column disagreements\n")
    if not disagreements:
        lines.append("None — router-labeler matched human gold set exactly on every row.\n")
    else:
        lines.append(
            f"{len(disagreements)} / {len(calls)} rows disagree. "
            "Sorted by per-column Jaccard ascending (worst agreement first).\n\n"
        )
        lines.append("| column_id | shape | pred | true | FP | FN | Jaccard |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for cid, shape, pred, true, fp, fn, jac in disagreements:
            lines.append(
                f"| `{cid}` | `{shape}` | {_fmt_labels(pred)} | {_fmt_labels(true)} | "
                f"{_fmt_labels(fp)} | {_fmt_labels(fn)} | `{jac:.3f}` |\n"
            )
        lines.append("\n")

    # Per-branch verbatim instructions (so memo diffs capture prompt changes)
    lines.append("## Per-branch instructions used in this run\n")
    lines.append("Captured verbatim from ``llm_labeler_router.py`` at run time.\n\n")
    for shape, instructions in (
        ("structured_single", STRUCTURED_SINGLE_INSTRUCTIONS),
        ("opaque_tokens", OPAQUE_TOKENS_INSTRUCTIONS),
        ("free_text_heterogeneous", HETEROGENEOUS_INSTRUCTIONS),
    ):
        lines.append(f"### `{shape}`\n\n```\n{instructions}\n```\n\n")

    out_path.write_text("".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directory for predictions.jsonl + result.md (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap rows for smoke tests (default: all human_reviewed rows)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dump each branch's system prompt + the first column's user message without API calls",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between API calls for rate-limit headroom (default: 0)",
    )
    parser.add_argument(
        "--compare-to",
        type=Path,
        default=None,
        help="Phase 1 predictions.jsonl to diff against (enables Phase 1 regression check)",
    )
    args = parser.parse_args()

    if args.dry_run:
        from tests.benchmarks.meta_classifier.llm_labeler import build_user_message

        with GOLD_SET_PATH.open() as f:
            rows = [json.loads(line) for line in f if line.strip()]
        rows = [r for r in rows if r.get("review_status") == "human_reviewed"]
        if not rows:
            print("No human_reviewed rows in gold set.", file=sys.stderr)  # noqa: T201
            return 1
        for shape in VALID_SHAPES:
            system = build_system_prompt_for_shape(shape)
            print(f"═══ SYSTEM PROMPT ({shape}) ═══")  # noqa: T201
            print(system[0]["text"])  # noqa: T201
            print()  # noqa: T201
            sample = next((r for r in rows if r.get("true_shape") == shape), None)
            if sample is not None:
                print(f"═══ SAMPLE USER MESSAGE ({sample['column_id']}) ═══")  # noqa: T201
                print(build_user_message(sample))  # noqa: T201
                print()  # noqa: T201
        print(f"Rows that would be scored: {len(rows) if args.limit is None else min(args.limit, len(rows))}")  # noqa: T201
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Running M4d Phase 2 router-labeler → {args.out_dir}")  # noqa: T201
    calls = label_gold_set_via_router(limit=args.limit, sleep_between_calls=args.sleep)
    print(f"Scored {len(calls)} columns.")  # noqa: T201

    # Load gold set for shape lookup
    with GOLD_SET_PATH.open() as f:
        gold_list = [json.loads(line) for line in f if line.strip()]
    gold_rows = {r["column_id"]: r for r in gold_list}

    column_results: list[ColumnResult] = [c.to_column_result() for c in calls]
    overall_metrics = aggregate_multi_label(column_results)
    per_shape = _per_shape_metrics(calls, gold_rows)

    print(f"Overall Jaccard macro: {overall_metrics.get('jaccard_macro', 0.0):.4f}")  # noqa: T201
    for shape in sorted(per_shape.keys()):
        m = per_shape[shape]
        print(f"  {shape:<30s} n={m.get('n_columns', 0):>2}  jaccard={m.get('jaccard_macro', 0.0):.4f}")  # noqa: T201

    phase1_preds = None
    if args.compare_to is not None:
        phase1_preds = _load_phase1_baseline(args.compare_to)
        print(f"Loaded {len(phase1_preds)} Phase 1 baseline predictions from {args.compare_to}")  # noqa: T201

    run_meta = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": MODEL,
    }
    _write_predictions_jsonl(args.out_dir / "predictions.jsonl", calls)
    _write_memo(
        args.out_dir / "result.md",
        calls,
        overall_metrics,
        per_shape,
        gold_rows,
        run_meta,
        phase1_preds,
    )
    print(f"Wrote {args.out_dir / 'result.md'}")  # noqa: T201
    print(f"Wrote {args.out_dir / 'predictions.jsonl'}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
