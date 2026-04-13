"""CLI for the gliner-context research harness.

Usage:
    .venv/bin/python -m tests.benchmarks.gliner_context \\
        --strategies baseline,s1_nl_prompt,s2_per_column_descriptions,s3_label_narrowing \\
        --samples-per-column 30 \\
        --threshold 0.5 \\
        --out docs/experiments/gliner_context/runs/20260413-1445-first-f1/

Outputs a JSON summary + a markdown table to the given output dir.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from tests.benchmarks.gliner_context.harness import (
    STRATEGIES,
    build_corpus,
    load_ai4privacy_value_pools,
    run_strategy_on_corpus,
    stratify_by_context_kind,
    summarize,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GLiNER context-injection measurement harness")
    parser.add_argument(
        "--strategies",
        default="baseline,s1_nl_prompt,s2_per_column_descriptions,s3_label_narrowing",
        help="Comma-separated list of strategy names (see harness.STRATEGIES).",
    )
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/corpora/ai4privacy_sample.json",
        help="Path to Ai4Privacy fixture JSON.",
    )
    parser.add_argument("--samples-per-column", type=int, default=30)
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument(
        "--model",
        default="fastino/gliner2-base-v1",
        help="HuggingFace repo ID to load from local cache.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/experiments/gliner_context/runs") / time.strftime("%Y%m%d-%H%M"),
        help="Output directory for summary JSON and markdown.",
    )
    args = parser.parse_args(argv)

    strategy_names = [s.strip() for s in args.strategies.split(",") if s.strip()]
    for name in strategy_names:
        if name not in STRATEGIES:
            print(f"Unknown strategy: {name}. Available: {list(STRATEGIES)}", file=sys.stderr)
            return 2

    args.out.mkdir(parents=True, exist_ok=True)

    # 1. Build corpus
    print(f"[1/4] Loading Ai4Privacy value pools from {args.fixture}")
    pools = load_ai4privacy_value_pools(Path(args.fixture))
    print(f"      got {len(pools)} entity types with usable pools: {sorted(pools)}")
    for gt, pool in sorted(pools.items()):
        print(f"        {gt}: {len(pool)} values")

    corpus = build_corpus(pools, samples_per_column=args.samples_per_column)
    print(f"      built {len(corpus)} corpus rows")

    # 2. Load model
    print(f"[2/4] Loading {args.model} from local HF cache")
    t0 = time.perf_counter()
    from gliner2 import GLiNER2
    model = GLiNER2.from_pretrained(args.model)
    print(f"      loaded in {time.perf_counter() - t0:.2f}s")

    # 3. Run each strategy
    all_results: dict[str, dict] = {}
    per_strategy_raw = {}
    for name in strategy_names:
        print(f"[3/4] Running strategy {name!r} on {len(corpus)} columns...")
        t0 = time.perf_counter()
        results = run_strategy_on_corpus(
            model=model,
            strategy_name=name,
            strategy_fn=STRATEGIES[name],
            corpus=corpus,
            threshold=args.threshold,
        )
        wall = time.perf_counter() - t0
        print(f"      done in {wall:.1f}s")
        all_results[name] = {
            "overall": summarize(results),
            "by_context_kind": stratify_by_context_kind(results),
            "wall_s": round(wall, 2),
        }
        per_strategy_raw[name] = [
            {
                "column_id": r.column_id,
                "ground_truth": r.ground_truth,
                "context_kind": r.context_kind,
                "predicted": sorted(r.predicted_entity_types),
                "top_confidence_by_type": {k: round(v, 4) for k, v in r.top_confidence_by_type.items()},
                "latency_ms": round(r.latency_s * 1000, 1),
            }
            for r in results
        ]

    # 4. Write outputs
    print(f"[4/4] Writing summary to {args.out}")
    (args.out / "summary.json").write_text(json.dumps(all_results, indent=2))
    (args.out / "per_column.json").write_text(json.dumps(per_strategy_raw, indent=2))

    # Markdown table
    md_lines = [
        "# GLiNER context injection — measurement run",
        "",
        f"- Model: `{args.model}`",
        f"- Corpus: Ai4Privacy fixture, {len(corpus)} columns, {args.samples_per_column} values each",
        f"- Threshold: {args.threshold}",
        f"- Strategies: {', '.join(strategy_names)}",
        "",
        "## Overall macro F1",
        "",
        "| Strategy | Macro F1 | Columns | Latency p50 (ms) | Latency p95 (ms) | Wall (s) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in strategy_names:
        summary = all_results[name]["overall"]
        md_lines.append(
            f"| `{name}` | **{summary['macro_f1']:.4f}** | {summary['column_count']} | "
            f"{summary['latency_p50_ms']} | {summary['latency_p95_ms']} | {all_results[name]['wall_s']} |"
        )

    md_lines += ["", "## Per context-kind stratification (macro F1)", ""]
    kinds = sorted({k for r in all_results.values() for k in r["by_context_kind"]})
    md_lines.append("| Strategy | " + " | ".join(kinds) + " |")
    md_lines.append("|---|" + "|".join(["---:"] * len(kinds)) + "|")
    for name in strategy_names:
        row = [f"`{name}`"]
        for k in kinds:
            by = all_results[name]["by_context_kind"].get(k, {})
            f1 = by.get("macro_f1", 0.0)
            row.append(f"**{f1:.4f}**")
        md_lines.append("| " + " | ".join(row) + " |")

    md_lines += ["", "## Per-entity F1 (baseline strategy only)", ""]
    base_per = all_results[strategy_names[0]]["overall"]["per_entity"]
    md_lines.append("| Entity | P | R | F1 | TP | FP | FN |")
    md_lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for ent, m in base_per.items():
        md_lines.append(
            f"| {ent} | {m['p']:.3f} | {m['r']:.3f} | **{m['f1']:.3f}** | "
            f"{m['tp']} | {m['fp']} | {m['fn']} |"
        )

    (args.out / "RESULTS.md").write_text("\n".join(md_lines) + "\n")

    print("\n" + "\n".join(md_lines[: 20 + len(strategy_names) * 2]))
    print(f"\nFull results: {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
