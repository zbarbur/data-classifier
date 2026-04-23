"""Evaluate zone detector v2 against the reviewed WildChat corpus.

Usage:
    DATA_CLASSIFIER_DISABLE_ML=1 .venv/bin/python -m docs.experiments.prompt_analysis.s4_zone_detection.v2.evaluate
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from docs.experiments.prompt_analysis.s4_zone_detection.v2 import detect_zones

CORPUS_PATH = Path(__file__).parent.parent / "labeled_data" / "s4_labeled_corpus.jsonl"


def _ground_truth_has_blocks(record: dict) -> bool | None:
    """Return the ground-truth has-blocks verdict for a reviewed record.

    The corpus schema:
        review.correct  (True | False | None)
        review.actual_blocks  — corrected block list (may be [] or absent)
        heuristic_has_blocks  — whether the v1 heuristic fired

    Logic:
      - correct=None  → unreviewed; skip (return None)
      - correct=True  → heuristic was right:
            * if actual_blocks present and non-empty → has real blocks
            * otherwise fall back to heuristic_has_blocks
      - correct=False → heuristic was wrong; actual_blocks holds the truth:
            * actual_blocks non-empty → different blocks exist (still has blocks)
            * actual_blocks empty/absent → no real blocks (was a FP)
    """
    review = record.get("review") or {}
    correct = review.get("correct")

    if correct is None:
        return None  # unreviewed — excluded from evaluated set

    actual_blocks = review.get("actual_blocks") or []

    if correct is True:
        if actual_blocks:
            return True
        # No corrected blocks recorded; heuristic was right so fall back to it
        return bool(record.get("heuristic_has_blocks", False))
    else:
        # correct=False: heuristic was wrong; truth is in actual_blocks
        return bool(actual_blocks)


def main() -> None:
    if not CORPUS_PATH.exists():
        print(f"Corpus not found: {CORPUS_PATH}")
        sys.exit(1)

    records = []
    skipped_unreviewed = 0
    with open(CORPUS_PATH) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            gt = _ground_truth_has_blocks(r)
            if gt is None:
                skipped_unreviewed += 1
            else:
                r["_gt_has_blocks"] = gt
                records.append(r)

    print(f"Corpus: {len(records) + skipped_unreviewed} total records")
    print(f"  Reviewed (evaluated): {len(records)}")
    print(f"  Unreviewed (skipped): {skipped_unreviewed}")
    print()
    print(f"Evaluating on {len(records)} reviewed records...")

    tp = fp = fn = tn = 0
    start = time.time()

    for r in records:
        text = r.get("text", "")
        if not text:
            continue

        has_real_blocks: bool = r["_gt_has_blocks"]

        result = detect_zones(text, prompt_id=r.get("prompt_id", ""))
        has_v2_blocks = len(result.blocks) > 0

        if has_real_blocks and has_v2_blocks:
            tp += 1
        elif has_real_blocks and not has_v2_blocks:
            fn += 1
        elif not has_real_blocks and has_v2_blocks:
            fp += 1
        else:
            tn += 1

    elapsed = time.time() - start
    total = tp + fp + fn + tn

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    print(f"\nResults ({total} records, {elapsed:.1f}s):")
    print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  Precision: {precision:.1%}")
    print(f"  Recall:    {recall:.1%}")
    print(f"  F1:        {f1:.3f}")
    print(f"  Throughput: {total / elapsed:.0f} prompts/sec")
    print()
    print("Targets: Precision >90%, Recall >95%, F1 >0.92")
    print(f"  Precision {'PASS' if precision > 0.90 else 'FAIL'}")
    print(f"  Recall    {'PASS' if recall > 0.95 else 'FAIL'}")
    print(f"  F1        {'PASS' if f1 > 0.92 else 'FAIL'}")


if __name__ == "__main__":
    main()
