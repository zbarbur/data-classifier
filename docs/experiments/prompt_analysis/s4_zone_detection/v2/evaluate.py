"""Evaluate zone detector v2 against the reviewed WildChat corpus.

Measures both detection accuracy (does a block exist?) and boundary
accuracy (do the detected line ranges match the human-marked ranges?).

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


def _ground_truth(record: dict) -> tuple[bool | None, list[dict]]:
    """Return (has_blocks, ground_truth_blocks) for a reviewed record.

    Returns (None, []) for unreviewed records.
    """
    review = record.get("review") or {}
    correct = review.get("correct")

    if correct is None:
        return None, []

    actual_blocks = review.get("actual_blocks") or []

    if correct is True:
        if actual_blocks:
            return True, actual_blocks
        return bool(record.get("heuristic_has_blocks", False)), []
    else:
        return bool(actual_blocks), actual_blocks


def _line_set(blocks: list[dict], key_start: str = "start_line", key_end: str = "end_line") -> set[int]:
    """Convert block list to set of covered line indices."""
    lines = set()
    for b in blocks:
        s = b.get(key_start, 0)
        e = b.get(key_end, 0)
        lines.update(range(s, e))
    return lines


def _jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 1.0
    return len(set_a & set_b) / len(union)


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
            has_blocks, gt_blocks = _ground_truth(r)
            if has_blocks is None:
                skipped_unreviewed += 1
            else:
                r["_gt_has_blocks"] = has_blocks
                r["_gt_blocks"] = gt_blocks
                records.append(r)

    print(f"Corpus: {len(records) + skipped_unreviewed} total records")
    print(f"  Reviewed (evaluated): {len(records)}")
    print(f"  Unreviewed (skipped): {skipped_unreviewed}")
    print()

    # --- Detection accuracy ---
    tp = fp = fn = tn = 0
    # --- Boundary accuracy ---
    boundary_jaccards: list[float] = []
    boundary_recalls: list[float] = []
    boundary_precisions: list[float] = []
    block_count_ratios: list[float] = []

    start = time.time()

    for r in records:
        text = r.get("text", "")
        if not text:
            continue

        has_real_blocks: bool = r["_gt_has_blocks"]
        gt_blocks: list[dict] = r["_gt_blocks"]

        result = detect_zones(text, prompt_id=r.get("prompt_id", ""))
        has_v2_blocks = len(result.blocks) > 0

        # Detection accuracy
        if has_real_blocks and has_v2_blocks:
            tp += 1
        elif has_real_blocks and not has_v2_blocks:
            fn += 1
        elif not has_real_blocks and has_v2_blocks:
            fp += 1
        else:
            tn += 1

        # Boundary accuracy (only for records with human-marked ranges)
        if gt_blocks and has_v2_blocks:
            gt_lines = _line_set(gt_blocks)
            v2_lines = _line_set([{"start_line": b.start_line, "end_line": b.end_line} for b in result.blocks])
            if gt_lines:
                jacc = _jaccard(gt_lines, v2_lines)
                boundary_jaccards.append(jacc)
                # Boundary recall: what fraction of human-marked lines did v2 cover?
                b_recall = len(gt_lines & v2_lines) / len(gt_lines)
                boundary_recalls.append(b_recall)
                # Boundary precision: what fraction of v2 lines are in human marks?
                if v2_lines:
                    b_prec = len(gt_lines & v2_lines) / len(v2_lines)
                    boundary_precisions.append(b_prec)
                # Block count ratio (fragmentation)
                gt_count = len(gt_blocks)
                v2_count = len(result.blocks)
                if gt_count > 0:
                    block_count_ratios.append(v2_count / gt_count)

    elapsed = time.time() - start
    total = tp + fp + fn + tn

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    print(f"=== Detection Accuracy ({total} records, {elapsed:.1f}s) ===")
    print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  Precision: {precision:.1%}")
    print(f"  Recall:    {recall:.1%}")
    print(f"  F1:        {f1:.3f}")
    print(f"  Throughput: {total / elapsed:.0f} prompts/sec")
    print()

    if boundary_jaccards:
        avg_jacc = sum(boundary_jaccards) / len(boundary_jaccards)
        avg_b_recall = sum(boundary_recalls) / len(boundary_recalls)
        avg_b_prec = sum(boundary_precisions) / len(boundary_precisions) if boundary_precisions else 0
        avg_frag = sum(block_count_ratios) / len(block_count_ratios) if block_count_ratios else 0
        median_jacc = sorted(boundary_jaccards)[len(boundary_jaccards) // 2]
        median_b_recall = sorted(boundary_recalls)[len(boundary_recalls) // 2]

        print(f"=== Boundary Accuracy ({len(boundary_jaccards)} records with human-marked ranges) ===")
        print(f"  Line-level Jaccard:     mean={avg_jacc:.1%}  median={median_jacc:.1%}")
        print(f"  Boundary recall:        mean={avg_b_recall:.1%}  median={median_b_recall:.1%}")
        print(f"  Boundary precision:     mean={avg_b_prec:.1%}")
        print(f"  Fragmentation ratio:    mean={avg_frag:.2f}x  (1.0 = perfect, >1 = over-split)")
        print()

    print("=== Targets ===")
    print(f"  Detection precision >90%:   {'PASS' if precision > 0.90 else 'FAIL'} ({precision:.1%})")
    print(f"  Detection recall >95%:      {'PASS' if recall > 0.95 else 'FAIL'} ({recall:.1%})")
    print(f"  Detection F1 >0.92:         {'PASS' if f1 > 0.92 else 'FAIL'} ({f1:.3f})")
    if boundary_jaccards:
        print(f"  Boundary recall >85%:       {'PASS' if avg_b_recall > 0.85 else 'FAIL'} ({avg_b_recall:.1%})")
        print(f"  Fragmentation <1.3x:        {'PASS' if avg_frag < 1.3 else 'FAIL'} ({avg_frag:.2f}x)")


if __name__ == "__main__":
    main()
