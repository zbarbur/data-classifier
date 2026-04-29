"""Build labeled dataset from S4 zone detection scan.

Exports:
  1. All prompts with detected blocks (heuristic pre-labels)
  2. Stratified random sample of "no detection" prompts (false-negative candidates)

Output: s4_labeled_corpus.jsonl — each record has prompt text + heuristic block annotations
        ready for human review.

Usage:
    python -m docs.experiments.prompt_analysis.s4_zone_detection.build_labeled_set \
        --annotations /tmp/s4_results_v3/s4_zone_annotations.jsonl \
        --negative-sample 300 \
        --out-dir docs/experiments/prompt_analysis/s4_zone_detection/labeled_data
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))

from docs.experiments.prompt_analysis.s4_zone_detection._codec import encode
from docs.experiments.prompt_analysis.s4_zone_detection.zone_detector import detect_zones

log = logging.getLogger(__name__)


def _extract_prompt_text(row: dict) -> str | None:
    conv = row.get("conversation", [])
    for turn in conv:
        if turn.get("role") == "user":
            return turn.get("content", "")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=str, default="/tmp/s4_results_v3/s4_zone_annotations.jsonl")
    parser.add_argument(
        "--negative-sample",
        type=int,
        default=300,
        help="Number of no-detection prompts to include for false-negative review",
    )
    parser.add_argument(
        "--out-dir", type=str, default="docs/experiments/prompt_analysis/s4_zone_detection/labeled_data"
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load annotations
    with open(args.annotations) as f:
        records = [json.loads(l) for l in f]

    positive_ids = {r["prompt_id"] for r in records if r["has_blocks"]}
    negative_ids = [r["prompt_id"] for r in records if not r["has_blocks"]]

    # Sample negatives
    rng = random.Random(args.seed)
    neg_sample = set(rng.sample(negative_ids, min(args.negative_sample, len(negative_ids))))

    target_ids = positive_ids | neg_sample
    log.info(
        "Target: %d positives + %d negative samples = %d total", len(positive_ids), len(neg_sample), len(target_ids)
    )

    # Load WildChat locally and find matching prompts
    from data_classifier.datasets import load_local_or_remote

    log.info("Loading WildChat (local)...")
    ds = load_local_or_remote("wildchat_1m")
    log.info("Loaded %d rows, scanning for target prompts...", len(ds))

    found: dict[str, str] = {}
    for idx in range(len(ds)):
        text = _extract_prompt_text(ds[idx])
        if not text or len(text.strip()) < 10:
            continue
        pid = hashlib.sha256(text.encode()).hexdigest()[:16]
        if pid in target_ids:
            found[pid] = text
            if len(found) == len(target_ids):
                break
        if idx % 100_000 == 0 and idx > 0:
            log.info("  scanned %d rows, found %d / %d", idx, len(found), len(target_ids))

    log.info("Found %d / %d target prompts", len(found), len(target_ids))

    # Build labeled records
    # Re-run detector to get block text included
    output_path = out_dir / "s4_labeled_corpus.jsonl"
    stats = Counter()

    with open(output_path, "w") as f:
        for pid, text in sorted(found.items()):
            zones = detect_zones(text, prompt_id=pid)
            is_positive = pid in positive_ids

            record = {
                "prompt_id": pid,
                "text_xor": encode(text),
                "total_lines": zones.total_lines,
                "heuristic_has_blocks": is_positive,
                "heuristic_blocks": [
                    {
                        "start_line": b.start_line,
                        "end_line": b.end_line,
                        "zone_type": b.zone_type,
                        "confidence": b.confidence,
                        "method": b.method,
                        "language_hint": b.language_hint,
                    }
                    for b in zones.blocks
                ],
                # Human review fields — to be filled during labeling
                "review": {
                    "correct": None,  # True if heuristic labels are correct
                    "actual_blocks": None,  # Corrected block list if wrong
                    "notes": "",
                },
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

            if is_positive:
                stats["positive"] += 1
                for b in zones.blocks:
                    stats[f"type_{b.zone_type}"] += 1
                    stats[f"method_{b.method}"] += 1
            else:
                stats["negative_sample"] += 1

    # Summary
    summary = {
        "total_records": stats["positive"] + stats["negative_sample"],
        "positives": stats["positive"],
        "negative_samples": stats["negative_sample"],
        "block_counts": {k: v for k, v in stats.items() if k.startswith("type_")},
        "method_counts": {k: v for k, v in stats.items() if k.startswith("method_")},
    }

    summary_path = out_dir / "s4_labeled_corpus_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nLabeled corpus: {output_path}")
    print(f"  Positives: {stats['positive']}")
    print(f"  Negative samples: {stats['negative_sample']}")
    print(f"  Total: {stats['positive'] + stats['negative_sample']}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
