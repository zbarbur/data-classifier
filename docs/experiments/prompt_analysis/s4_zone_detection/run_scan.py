"""Run zone detection over WildChat sample and produce labeled JSONL.

Usage:
    python -m docs.experiments.prompt_analysis.s4_zone_detection.run_scan \
        --limit 10000 --out-dir /tmp/s4_results

Output files:
    s4_zone_annotations.jsonl  — one JSON object per prompt with block annotations
    s4_summary.json            — aggregate prevalence stats
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sys
import time
from collections import Counter
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from docs.experiments.prompt_analysis.s4_zone_detection.zone_detector import detect_zones

log = logging.getLogger(__name__)


def _extract_prompt_text(row: dict) -> str | None:
    """Extract first user prompt from a WildChat conversation."""
    conv = row.get("conversation", [])
    if not conv:
        return None
    for turn in conv:
        if turn.get("role") == "user":
            return turn.get("content", "")
    return None


def main():
    parser = argparse.ArgumentParser(description="S4 zone detection scan")
    parser.add_argument("--limit", type=int, default=10_000)
    parser.add_argument("--out-dir", type=str, default="/tmp/s4_results")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load corpus — local DVC data (fast)
    from data_classifier.datasets import load_local_or_remote

    log.info("Loading WildChat (local)...")
    ds = load_local_or_remote("wildchat_1m")
    log.info("Loaded %d rows", len(ds))

    # Extract all user prompts, then sample
    log.info("Extracting user prompts...")
    all_prompts: list[tuple[str, str]] = []
    for idx in range(len(ds)):
        text = _extract_prompt_text(ds[idx])
        if not text or len(text.strip()) < 10:
            continue
        prompt_id = hashlib.sha256(text.encode()).hexdigest()[:16]
        all_prompts.append((prompt_id, text))

    log.info("Found %d valid prompts, sampling %d", len(all_prompts), args.limit)
    rng = random.Random(args.seed)
    reservoir = rng.sample(all_prompts, min(args.limit, len(all_prompts)))
    seen = len(all_prompts)

    # Run zone detection
    log.info("Running zone detection...")
    t0 = time.time()

    annotations_path = out_dir / "s4_zone_annotations.jsonl"

    # Stats accumulators
    total = len(reservoir)
    prompts_with_blocks = 0
    prompts_by_type: Counter = Counter()  # how many prompts contain each type
    blocks_by_type: Counter = Counter()
    blocks_by_method: Counter = Counter()
    blocks_by_lang: Counter = Counter()
    fenced_count = 0
    unfenced_count = 0
    line_counts: list[int] = []  # lines of code/structured per prompt
    confidence_sum = 0.0
    confidence_count = 0

    with open(annotations_path, "w") as f:
        for i, (prompt_id, text) in enumerate(reservoir):
            zones = detect_zones(text, prompt_id=prompt_id)

            # Gather stats
            has_block = len(zones.blocks) > 0
            if has_block:
                prompts_with_blocks += 1
                types_in_prompt = set()
                block_lines = 0
                for b in zones.blocks:
                    blocks_by_type[b.zone_type] += 1
                    blocks_by_method[b.method] += 1
                    if b.language_hint:
                        blocks_by_lang[b.language_hint] += 1
                    types_in_prompt.add(b.zone_type)
                    if b.method == "fenced":
                        fenced_count += 1
                    else:
                        unfenced_count += 1
                    block_lines += b.end_line - b.start_line
                    confidence_sum += b.confidence
                    confidence_count += 1
                for t in types_in_prompt:
                    prompts_by_type[t] += 1
                line_counts.append(block_lines)

            record = zones.to_dict()
            record["has_blocks"] = has_block
            record["num_blocks"] = len(zones.blocks)
            f.write(json.dumps(record) + "\n")

            if (i + 1) % 2000 == 0:
                log.info("  processed %d / %d", i + 1, total)

    elapsed = time.time() - t0
    log.info("Zone detection complete in %.1fs (%.0f prompts/sec)", elapsed, total / elapsed)

    # Build summary
    sorted_line_counts = sorted(line_counts) if line_counts else [0]

    def percentile(data, p):
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    summary = {
        "scan_params": {
            "limit": args.limit,
            "seed": args.seed,
            "actual_sampled": total,
            "total_scanned": seen,
        },
        "prevalence": {
            "prompts_with_any_block": prompts_with_blocks,
            "pct_with_any_block": round(100 * prompts_with_blocks / max(total, 1), 2),
            "prompts_by_type": {
                t: {"count": c, "pct": round(100 * c / max(total, 1), 2)}
                for t, c in prompts_by_type.most_common()
            },
        },
        "blocks": {
            "total_blocks": sum(blocks_by_type.values()),
            "by_type": dict(blocks_by_type.most_common()),
            "by_method": dict(blocks_by_method.most_common()),
            "by_language_hint": dict(blocks_by_lang.most_common(30)),
            "fenced_vs_unfenced": {
                "fenced": fenced_count,
                "unfenced": unfenced_count,
                "pct_fenced": round(100 * fenced_count / max(fenced_count + unfenced_count, 1), 1),
            },
        },
        "confidence": {
            "mean": round(confidence_sum / max(confidence_count, 1), 3),
        },
        "block_lines_per_prompt": {
            "mean": round(sum(line_counts) / max(len(line_counts), 1), 1),
            "median": percentile(sorted_line_counts, 50),
            "p90": percentile(sorted_line_counts, 90),
            "p99": percentile(sorted_line_counts, 99),
            "max": max(line_counts) if line_counts else 0,
        },
        "elapsed_sec": round(elapsed, 1),
        "throughput_per_sec": round(total / elapsed, 0),
    }

    summary_path = out_dir / "s4_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Print summary
    print("\n" + "=" * 60)
    print("S4 Zone Detection — Prevalence Summary")
    print("=" * 60)
    print(f"Prompts scanned: {total:,}")
    print(f"Prompts with code/structured blocks: {prompts_with_blocks:,} "
          f"({summary['prevalence']['pct_with_any_block']}%)")
    print()
    print("By type (prompt-level):")
    for t, info in summary["prevalence"]["prompts_by_type"].items():
        print(f"  {t:20s}: {info['count']:5d} ({info['pct']}%)")
    print()
    print(f"Total blocks: {summary['blocks']['total_blocks']:,}")
    print(f"Fenced: {fenced_count:,} ({summary['blocks']['fenced_vs_unfenced']['pct_fenced']}%)"
          f"  Unfenced: {unfenced_count:,}")
    print()
    print("By detection method:")
    for m, c in blocks_by_method.most_common():
        print(f"  {m:20s}: {c:5d}")
    print()
    print("Top language hints:")
    for lang, c in blocks_by_lang.most_common(15):
        print(f"  {lang:20s}: {c:5d}")
    print()
    print(f"Block lines per prompt: mean={summary['block_lines_per_prompt']['mean']}, "
          f"median={summary['block_lines_per_prompt']['median']}, "
          f"p90={summary['block_lines_per_prompt']['p90']}")
    print(f"\nThroughput: {summary['throughput_per_sec']:.0f} prompts/sec")
    print(f"Output: {annotations_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
