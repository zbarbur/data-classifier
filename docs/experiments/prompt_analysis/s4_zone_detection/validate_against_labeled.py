"""Validate the Rust UnifiedDetector against the s4 labeled corpus.

Labeling convention: ground truth marks only non-prose segments (code/markup/
config/data). Pure-prose prompts have zero ground-truth blocks. Our new
detector does complete partitioning (every line gets a zone), so we compare
only the non-NL predictions against ground truth.

Metrics:
- Block-level precision / recall / F1 per zone type
- IoU (intersection-over-union) for matched blocks
- Per-prompt classification: pure-prose vs has-blocks
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from data_classifier_core import UnifiedDetector
from docs.experiments.prompt_analysis.s4_zone_detection._codec import get_text

LABELED_PATH = Path("docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl")
PATTERNS_PATH = Path("data_classifier_core/patterns/unified_patterns.json")
IOU_MIN = 0.5

NON_PROSE_TYPES = {"code", "markup", "config", "data"}


def block_iou(a: dict, b: dict) -> float:
    """Line-range IoU (treats blocks as half-open ranges)."""
    a0, a1 = a["start_line"], a["end_line"]
    b0, b1 = b["start_line"], b["end_line"]
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def main() -> None:
    patterns_json = PATTERNS_PATH.read_text()
    detector = UnifiedDetector(patterns_json)

    # Per-zone-type counters
    tp = Counter()  # matched ground-truth blocks per type
    fp = Counter()  # predicted non-NL blocks with no matching GT
    fn = Counter()  # GT blocks with no matching prediction
    iou_sum = defaultdict(list)

    # Per-prompt-classification
    prose_correct = 0  # GT empty, pred only NL
    prose_wrong = 0  # GT empty, pred has non-NL
    blocks_seen_gt = 0
    blocks_seen_pred_nonNL = 0

    n = 0
    with LABELED_PATH.open() as f:
        for line in f:
            n += 1
            r = json.loads(line)
            text = get_text(r)
            gt_blocks = (r.get("review") or {}).get("actual_blocks") or []

            result_json = detector.detect(text)
            result = json.loads(result_json) if isinstance(result_json, str) else result_json
            zones = (result.get("zones") or {}).get("blocks") or []
            pred_blocks = [z for z in zones if z["zone_type"] in NON_PROSE_TYPES]

            blocks_seen_gt += len(gt_blocks)
            blocks_seen_pred_nonNL += len(pred_blocks)

            # Pure-prose case
            if not gt_blocks:
                if not pred_blocks:
                    prose_correct += 1
                else:
                    prose_wrong += 1
                    for p in pred_blocks:
                        fp[p["zone_type"]] += 1
                continue

            # Mixed case — match each GT block to best prediction
            matched_pred_idx = set()
            for gt in gt_blocks:
                best_iou = 0.0
                best_idx = -1
                for i, p in enumerate(pred_blocks):
                    if i in matched_pred_idx:
                        continue
                    if p["zone_type"] != gt["zone_type"]:
                        continue
                    iou = block_iou(gt, p)
                    if iou > best_iou:
                        best_iou = iou
                        best_idx = i
                if best_idx >= 0 and best_iou >= IOU_MIN:
                    tp[gt["zone_type"]] += 1
                    iou_sum[gt["zone_type"]].append(best_iou)
                    matched_pred_idx.add(best_idx)
                else:
                    fn[gt["zone_type"]] += 1

            # Unmatched predictions = false positives
            for i, p in enumerate(pred_blocks):
                if i not in matched_pred_idx:
                    fp[p["zone_type"]] += 1

    print(f"Validation against {n} labeled prompts")
    print(f"  IoU threshold: {IOU_MIN}")
    print(f"  Total GT non-prose blocks: {blocks_seen_gt}")
    print(f"  Total predicted non-NL blocks: {blocks_seen_pred_nonNL}")
    print()
    print("=== Per-zone-type metrics ===")
    print(f"  {'type':<18} {'TP':>5} {'FP':>5} {'FN':>5}  {'P':>6}  {'R':>6}  {'F1':>6}  {'meanIoU':>7}")
    for zt in sorted(set(tp) | set(fp) | set(fn)):
        t, p, n_ = tp[zt], fp[zt], fn[zt]
        prec = t / (t + p) if (t + p) else 0.0
        rec = t / (t + n_) if (t + n_) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        mean_iou = sum(iou_sum[zt]) / len(iou_sum[zt]) if iou_sum[zt] else 0.0
        print(f"  {zt:<18} {t:>5} {p:>5} {n_:>5}  {prec:>6.3f}  {rec:>6.3f}  {f1:>6.3f}  {mean_iou:>7.3f}")

    print()
    print("=== Pure-prose classification ===")
    pure_total = prose_correct + prose_wrong
    print(f"  Correct (GT empty AND pred has only NL): {prose_correct}/{pure_total} = {prose_correct / pure_total:.3f}")
    print(f"  Wrong (GT empty BUT pred has non-NL):   {prose_wrong}/{pure_total} = {prose_wrong / pure_total:.3f}")


if __name__ == "__main__":
    main()
