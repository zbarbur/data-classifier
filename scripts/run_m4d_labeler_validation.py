"""Driver for M4d Phase 1 — LLM labeler vs M4c human gold set.

Runs ``llm_labeler.label_gold_set()``, scores predictions via M4a's
``aggregate_multi_label``, writes per-column predictions + a markdown
result memo.

Usage::

    export ANTHROPIC_API_KEY=...
    python scripts/run_m4d_labeler_validation.py

    # Dry-run on 3 rows first:
    python scripts/run_m4d_labeler_validation.py --limit 3 --dry-run

    # Custom output directory:
    python scripts/run_m4d_labeler_validation.py \\
        --out-dir docs/experiments/meta_classifier/runs/20260417-m4d-phase1-labeler-validation

Writes:
  <out_dir>/result.md          — human-readable summary + per-column disagreements
  <out_dir>/predictions.jsonl  — per-column predictions + telemetry

This is a research CLI — ``print`` is the intended output surface (stdout
is the interactive progress report), matching the pattern established by
``tests/benchmarks/meta_classifier/gold_set_labeler.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from tests.benchmarks.meta_classifier.llm_labeler import (
    LABELER_INSTRUCTIONS,
    LabelerCall,
    label_gold_set,
)
from tests.benchmarks.meta_classifier.multi_label_metrics import (
    ColumnResult,
    aggregate_multi_label,
)

DEFAULT_OUT_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs/experiments/meta_classifier/runs/20260417-m4d-phase1-labeler-validation"
)
INSTRUCTIONS_TODO_SENTINEL = "TODO(guy.guzner): Write the instructions block here."


def _fmt_labels(labels: list[str]) -> str:
    return "[" + ", ".join(labels) + "]" if labels else "[]"


def _per_column_disagreement_rows(
    calls: list[LabelerCall],
) -> list[tuple[str, list[str], list[str], list[str], list[str], float]]:
    """Return rows where pred != true, with FP / FN diffs and per-column Jaccard."""
    rows = []
    for call in calls:
        pred_set, true_set = set(call.pred), set(call.true)
        if pred_set == true_set:
            continue
        fp = sorted(pred_set - true_set)
        fn = sorted(true_set - pred_set)
        union = pred_set | true_set
        jaccard = len(pred_set & true_set) / len(union) if union else 1.0
        rows.append((call.column_id, call.pred, call.true, fp, fn, jaccard))
    rows.sort(key=lambda r: r[5])  # worst Jaccard first
    return rows


def _write_predictions_jsonl(out_path: Path, calls: list[LabelerCall]) -> None:
    with out_path.open("w") as f:
        for call in calls:
            f.write(json.dumps(call.to_jsonl_dict(), ensure_ascii=False) + "\n")


def _write_memo(
    out_path: Path,
    calls: list[LabelerCall],
    metrics: dict,
    run_meta: dict,
) -> None:
    disagreements = _per_column_disagreement_rows(calls)
    total_in = sum(c.input_tokens for c in calls)
    total_out = sum(c.output_tokens for c in calls)
    total_cache_read = sum(c.cache_read_input_tokens for c in calls)
    total_cache_create = sum(c.cache_creation_input_tokens for c in calls)
    errors = [c for c in calls if c.error]
    unknowns = [(c.column_id, c.unknown_labels) for c in calls if c.unknown_labels]

    lines: list[str] = []
    lines.append("# M4d Phase 1 — LLM labeler validation vs M4c gold set\n")
    lines.append(f"**Run date:** {run_meta['timestamp']}\n")
    lines.append(f"**Model:** `{run_meta['model']}`\n")
    lines.append(f"**Gold-set rows scored:** {len(calls)} (human_reviewed only)\n")
    lines.append(f"**API errors:** {len(errors)}\n")
    lines.append(f"**Invalid-label responses:** {len(unknowns)} columns emitted unknown label strings\n\n")

    lines.append("## Quality gate\n")
    jaccard = metrics.get("jaccard_macro", 0.0)
    gate_verdict = "✅ PASS" if jaccard >= 0.8 else "❌ FAIL — iterate on LABELER_INSTRUCTIONS"
    lines.append(f"**Jaccard macro:** `{jaccard:.4f}` (gate: ≥ 0.8) → {gate_verdict}\n\n")

    lines.append("## Metrics\n")
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
        if k in metrics:
            v = metrics[k]
            v_str = f"`{v:.4f}`" if isinstance(v, float) else f"`{v}`"
            lines.append(f"| {k} | {v_str} |\n")
    lines.append("\n")

    lines.append("## Usage + cost telemetry\n")
    lines.append(f"- Input tokens (uncached): **{total_in:,}**\n")
    lines.append(f"- Output tokens: **{total_out:,}**\n")
    lines.append(f"- Cache read tokens: **{total_cache_read:,}** (served at ~0.1× price)\n")
    lines.append(f"- Cache creation tokens: **{total_cache_create:,}** (paid at 1.25× price, once)\n")
    cache_pct = (total_cache_read / max(total_cache_read + total_in, 1)) * 100
    lines.append(f"- Cache-hit rate on input: **{cache_pct:.1f}%**\n")
    if cache_pct < 5 and len(calls) > 1:
        lines.append(
            "- ⚠️ Cache-hit rate near 0 suggests the system prompt is below Opus 4.7's "
            "4096-token minimum cacheable prefix. Consider extending the few-shot examples "
            "or the instructions block, or accept the higher per-call cost.\n"
        )
    # Opus 4.7 pricing: $5/M input, $25/M output. Cache reads ~0.1×; writes ~1.25×.
    cost_in = total_in * 5e-6
    cost_out = total_out * 25e-6
    cost_cache_read = total_cache_read * 5e-6 * 0.1
    cost_cache_create = total_cache_create * 5e-6 * 1.25
    total_cost = cost_in + cost_out + cost_cache_read + cost_cache_create
    lines.append(f"- **Estimated total cost:** ${total_cost:.4f}\n\n")

    if unknowns:
        lines.append("## Prompt-compliance failures (unknown label strings)\n")
        lines.append(
            "The LLM emitted labels outside the allowed entity set. These are filtered "
            "from the prediction but flagged here for prompt iteration.\n\n"
        )
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

    lines.append("## Per-column disagreements\n")
    if not disagreements:
        lines.append("None — labeler matched human gold set exactly on every row.\n")
    else:
        lines.append(
            f"{len(disagreements)} / {len(calls)} rows disagree. "
            "Sorted by per-column Jaccard ascending (worst agreement first).\n\n"
        )
        lines.append("| column_id | pred | true | FP (over-fire) | FN (missed) | Jaccard |\n")
        lines.append("|---|---|---|---|---|---|\n")
        for cid, pred, true, fp, fn, jac in disagreements:
            lines.append(
                f"| `{cid}` | {_fmt_labels(pred)} | {_fmt_labels(true)} | "
                f"{_fmt_labels(fp)} | {_fmt_labels(fn)} | `{jac:.3f}` |\n"
            )
        lines.append("\n")

    lines.append("## Labeler instructions used in this run\n")
    lines.append(
        "Captured verbatim from ``llm_labeler.py`` at run time, so memo diffs "
        "across iterations show which instruction change produced which "
        "Jaccard delta.\n\n```\n"
    )
    lines.append(LABELER_INSTRUCTIONS + "\n")
    lines.append("```\n")

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
        help="Validate setup + print first-column prompt without making API calls",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between API calls for rate-limit headroom (default: 0)",
    )
    args = parser.parse_args()

    if args.dry_run:
        from tests.benchmarks.meta_classifier.llm_labeler import (
            GOLD_SET_PATH,
            build_system_prompt,
            build_user_message,
        )

        with GOLD_SET_PATH.open() as f:
            rows = [json.loads(line) for line in f if line.strip()]
        rows = [r for r in rows if r.get("review_status") == "human_reviewed"]
        if not rows:
            print("No human_reviewed rows in gold set.", file=sys.stderr)  # noqa: T201
            return 1
        system = build_system_prompt()
        print("═══ SYSTEM PROMPT ═══")  # noqa: T201
        print(system[0]["text"])  # noqa: T201
        print("\n═══ FIRST USER MESSAGE ═══")  # noqa: T201
        print(build_user_message(rows[0]))  # noqa: T201
        print(f"\nRows that would be scored: {len(rows) if args.limit is None else min(args.limit, len(rows))}")  # noqa: T201
        return 0

    if LABELER_INSTRUCTIONS.startswith(INSTRUCTIONS_TODO_SENTINEL):
        print(  # noqa: T201
            "❌ LABELER_INSTRUCTIONS in llm_labeler.py is still the TODO stub.\n"
            "   Edit that block before running the validation.",
            file=sys.stderr,
        )
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Running M4d Phase 1 validation → {args.out_dir}")  # noqa: T201
    calls = label_gold_set(limit=args.limit, sleep_between_calls=args.sleep)
    print(f"Scored {len(calls)} columns.")  # noqa: T201

    column_results: list[ColumnResult] = [c.to_column_result() for c in calls]
    metrics = aggregate_multi_label(column_results)
    print(f"Jaccard macro: {metrics.get('jaccard_macro', 0.0):.4f}")  # noqa: T201

    from tests.benchmarks.meta_classifier.llm_labeler import MODEL

    run_meta = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": MODEL,
    }
    _write_predictions_jsonl(args.out_dir / "predictions.jsonl", calls)
    _write_memo(args.out_dir / "result.md", calls, metrics, run_meta)
    print(f"Wrote {args.out_dir / 'result.md'}")  # noqa: T201
    print(f"Wrote {args.out_dir / 'predictions.jsonl'}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
