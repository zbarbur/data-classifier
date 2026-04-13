"""CLI for the gliner-context research harness (Pass 1).

Usage:
    .venv/bin/python -m tests.benchmarks.gliner_context \\
        --strategies baseline,s1_nl_prompt,s2_per_column_descriptions,s3_label_narrowing \\
        --seeds 42,7,101 \\
        --thresholds 0.5,0.7,0.8 \\
        --samples-per-column 30 \\
        --out docs/experiments/gliner_context/runs/pass1/

Pass 1 adds:
  - Multi-seed value-slice replication (--seeds)
  - Threshold sweep (--thresholds)
  - Paired McNemar exact test per variant vs baseline
  - BCa 95% bootstrap CI on each strategy's macro F1
  - BCa 95% bootstrap CI on each variant's paired Δ F1 vs baseline
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from tests.benchmarks.gliner_context.harness import (
    STRATEGIES,
    bootstrap_f1_ci,
    build_multi_seed_corpus,
    compare_strategies,
    load_ai4privacy_value_pools,
    run_strategy_on_corpus,
    stratify_by_context_kind,
    summarize,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GLiNER context-injection harness (Pass 1)")
    parser.add_argument(
        "--strategies",
        default="baseline,s1_nl_prompt,s2_per_column_descriptions,s3_label_narrowing",
    )
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/corpora/ai4privacy_sample.json",
    )
    parser.add_argument("--samples-per-column", type=int, default=30)
    parser.add_argument(
        "--seeds",
        default="42,7,101",
        help="Comma-separated value-slice seeds for replication.",
    )
    parser.add_argument(
        "--thresholds",
        default="0.5,0.7,0.8",
        help="Comma-separated GLiNER thresholds to sweep.",
    )
    parser.add_argument(
        "--n-resamples",
        type=int,
        default=1000,
        help="Bootstrap resample count. 1000 is standard; 5000 is paranoid.",
    )
    parser.add_argument("--model", default="fastino/gliner2-base-v1")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/experiments/gliner_context/runs") / time.strftime("%Y%m%d-%H%M-pass1"),
    )
    args = parser.parse_args(argv)

    strategy_names = [s.strip() for s in args.strategies.split(",") if s.strip()]
    for name in strategy_names:
        if name not in STRATEGIES:
            print(f"Unknown strategy: {name}. Available: {list(STRATEGIES)}", file=sys.stderr)
            return 2
    if "baseline" not in strategy_names:
        print("baseline strategy is required as the paired comparison anchor", file=sys.stderr)
        return 2

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    thresholds = [float(t) for t in args.thresholds.split(",") if t.strip()]
    args.out.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] Loading Ai4Privacy value pools from {args.fixture}")
    pools = load_ai4privacy_value_pools(Path(args.fixture))
    print(f"      got {len(pools)} entity types with usable pools")

    print(f"[2/5] Building multi-seed corpus with seeds={seeds}")
    corpus = build_multi_seed_corpus(
        pools,
        samples_per_column=args.samples_per_column,
        rng_seeds=seeds,
    )
    print(f"      built {len(corpus)} corpus rows "
          f"({len(corpus) // len(seeds)} templates × {len(seeds)} seeds)")

    print(f"[3/5] Loading {args.model} from local HF cache")
    t0 = time.perf_counter()
    from gliner2 import GLiNER2
    model = GLiNER2.from_pretrained(args.model)
    print(f"      loaded in {time.perf_counter() - t0:.2f}s")

    # Structure: out[threshold][strategy] = {overall, by_context_kind, wall_s, f1_ci, compare}
    all_results: dict[str, dict] = {}

    for threshold in thresholds:
        print(f"\n[4/5] Threshold = {threshold}")
        per_strategy_raw = {}
        strategy_results: dict[str, list] = {}

        for name in strategy_names:
            t0 = time.perf_counter()
            results = run_strategy_on_corpus(
                model=model,
                strategy_name=name,
                strategy_fn=STRATEGIES[name],
                corpus=corpus,
                threshold=threshold,
            )
            wall = time.perf_counter() - t0
            print(f"        {name!r}: {wall:.1f}s")
            strategy_results[name] = results
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

        # Summary + bootstrap F1 CIs + paired comparisons vs baseline
        threshold_summary: dict[str, dict] = {}
        baseline_results = strategy_results["baseline"]
        for name in strategy_names:
            results = strategy_results[name]
            summary_block = {
                "overall": summarize(results),
                "by_context_kind": stratify_by_context_kind(results),
                "f1_ci": bootstrap_f1_ci(results, n_resamples=args.n_resamples, rng_seed=0),
            }
            if name != "baseline":
                summary_block["compare_vs_baseline"] = compare_strategies(
                    baseline_results,
                    results,
                    variant_name=name,
                    n_resamples=args.n_resamples,
                    rng_seed=0,
                )
            threshold_summary[name] = summary_block

        all_results[f"threshold_{threshold}"] = threshold_summary

        # Raw per-column JSON for this threshold
        per_thr_path = args.out / f"per_column_thr{threshold}.json"
        per_thr_path.write_text(json.dumps(per_strategy_raw, indent=2))

    # 5. Write summary JSON + markdown
    print(f"\n[5/5] Writing summary to {args.out}")
    (args.out / "summary.json").write_text(json.dumps(all_results, indent=2))

    md_lines = [
        "# GLiNER context injection — Pass 1",
        "",
        f"- Model: `{args.model}`",
        f"- Corpus: Ai4Privacy, {len(corpus)} rows "
        f"({len(corpus) // len(seeds)} templates × {len(seeds)} seeds)",
        f"- Seeds: {seeds}",
        f"- Thresholds: {thresholds}",
        f"- Bootstrap resamples: {args.n_resamples} (BCa 95%)",
        "",
    ]

    for threshold in thresholds:
        key = f"threshold_{threshold}"
        md_lines += [f"## Threshold {threshold}", ""]
        md_lines += [
            "| Strategy | Macro F1 | 95% CI | vs baseline Δ | Δ 95% CI | Excl 0 | Excl +0.02 | McNemar p | (b, c) |",
            "|---|---:|---|---:|---|:-:|:-:|---:|---:|",
        ]
        baseline_f1 = all_results[key]["baseline"]["f1_ci"]["point"]
        baseline_ci = all_results[key]["baseline"]["f1_ci"]
        md_lines.append(
            f"| `baseline` | **{baseline_f1:.4f}** | "
            f"[{baseline_ci['ci_low']:.3f}, {baseline_ci['ci_high']:.3f}] "
            f"(w={baseline_ci['ci_width']:.3f}) | — | — | — | — | — | — |"
        )
        for name in strategy_names:
            if name == "baseline":
                continue
            block = all_results[key][name]
            ci = block["f1_ci"]
            cmp = block["compare_vs_baseline"]
            dci = cmp["delta_ci"]
            mc = cmp["mcnemar"]
            ez = "✓" if dci["excludes_zero"] else "×"
            ez02 = "✓" if dci["excludes_plus_02"] else "×"
            md_lines.append(
                f"| `{name}` | {ci['point']:.4f} | "
                f"[{ci['ci_low']:.3f}, {ci['ci_high']:.3f}] "
                f"(w={ci['ci_width']:.3f}) | "
                f"{dci['point']:+.4f} | "
                f"[{dci['ci_low']:+.3f}, {dci['ci_high']:+.3f}] "
                f"(w={dci['ci_width']:.3f}) | "
                f"{ez} | {ez02} | "
                f"{mc['p_value']:.4f} | "
                f"({mc['b']}, {mc['c']}) |"
            )
        md_lines += [""]

    # Context-kind stratification at the Sprint 9 target threshold
    target_thr = thresholds[-1]
    target_key = f"threshold_{target_thr}"
    md_lines += [
        f"## Context-kind stratification (threshold={target_thr})",
        "",
        "| Strategy | empty | helpful | misleading |",
        "|---|---:|---:|---:|",
    ]
    for name in strategy_names:
        by = all_results[target_key][name]["by_context_kind"]
        row = [f"`{name}`"]
        for kind in ("empty", "helpful", "misleading"):
            f1 = by.get(kind, {}).get("macro_f1", 0.0)
            row.append(f"{f1:.4f}")
        md_lines.append("| " + " | ".join(row) + " |")
    md_lines += [""]

    (args.out / "RESULTS.md").write_text("\n".join(md_lines) + "\n")

    # Print abbreviated headline to stdout
    print("\n" + "\n".join(md_lines[:30]))
    print(f"\nFull results: {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
