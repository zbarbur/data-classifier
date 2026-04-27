"""Merge fresh problem-slice reviews into the original 50-prompt slice
and re-run validation against the combined best-known gold.

Logic:
  - For each prompt in s4_relabel_slice (50 prompts):
      if there's a re-reviewed version in s4_problem_slice with review!=None,
        use that
      else
        use the original review
  - Run the (current) Rust UnifiedDetector on each prompt
  - Compare predictions to combined-best gold

This gives the most accurate measurement of detector quality given the
labeling we've done so far.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from data_classifier_core import UnifiedDetector

SLICE_PATH = Path("docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_relabel_slice.jsonl")
PROBLEM_PATH = Path("docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_problem_slice.jsonl")
PATTERNS_PATH = Path("data_classifier_core/patterns/unified_patterns.json")
NON_PROSE = {"code", "markup", "config", "data", "query", "cli_shell"}
IOU_MIN = 0.5


def block_iou(a: dict, b: dict) -> float:
    a0, a1 = a["start_line"], a["end_line"]
    b0, b1 = b["start_line"], b["end_line"]
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def gold_blocks(record: dict) -> list[dict]:
    """Build gold from a reviewed record. NL labels are filtered out
    (NL is the implicit background)."""
    rev = record.get("review") or {}
    if rev.get("correct") is True:
        return [b for b in (record.get("heuristic_blocks") or []) if b["zone_type"] in NON_PROSE]
    blocks = rev.get("actual_blocks") or []
    return [b for b in blocks if b["zone_type"] in NON_PROSE]


def main() -> None:
    # Load problem-slice reviews keyed by prompt_id
    problem_by_id: dict[str, dict] = {}
    with PROBLEM_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("review") is not None:
                problem_by_id[r["prompt_id"]] = r

    detector = UnifiedDetector(PATTERNS_PATH.read_text())

    tp = Counter()
    soft_tp = Counter()
    fp = Counter()
    fn = Counter()
    iou_sum = defaultdict(list)
    boundary_adjustments = []

    prose_correct = 0
    prose_wrong = 0
    prose_total = 0

    n = 0
    with SLICE_PATH.open() as f:
        for line in f:
            n += 1
            r = json.loads(line)
            # Use refreshed review if available
            if r["prompt_id"] in problem_by_id:
                gold = gold_blocks(problem_by_id[r["prompt_id"]])
            else:
                gold = gold_blocks(r)

            text = r["text"]
            res = json.loads(detector.detect(text))
            blocks = (res.get("zones") or {}).get("blocks") or []
            non_nl_pred = [b for b in blocks if b["zone_type"] in NON_PROSE]

            if not gold:
                prose_total += 1
                if not non_nl_pred:
                    prose_correct += 1
                else:
                    prose_wrong += 1
                    for p in non_nl_pred:
                        fp[p["zone_type"]] += 1
                continue

            matched_pred = set()
            for g in gold:
                best_iou = 0.0
                best_idx = -1
                for i, p in enumerate(non_nl_pred):
                    if i in matched_pred or p["zone_type"] != g["zone_type"]:
                        continue
                    iou = block_iou(g, p)
                    if iou > best_iou:
                        best_iou, best_idx = iou, i
                if best_idx >= 0 and best_iou >= IOU_MIN:
                    tp[g["zone_type"]] += 1
                    soft_tp[g["zone_type"]] += 1
                    iou_sum[g["zone_type"]].append(best_iou)
                    matched_pred.add(best_idx)
                elif best_idx >= 0 and best_iou >= 0.1:
                    soft_tp[g["zone_type"]] += 1
                    matched_pred.add(best_idx)
                    boundary_adjustments.append((r["prompt_id"], g, non_nl_pred[best_idx], best_iou))
                else:
                    fn[g["zone_type"]] += 1
            for i, p in enumerate(non_nl_pred):
                if i not in matched_pred:
                    fp[p["zone_type"]] += 1

    print(f"Validation against {n} prompts (with {len(problem_by_id)} re-reviewed)")
    print(f"  IoU threshold: {IOU_MIN}")
    print()
    print(f"  Pure-prose prompts: {prose_total}")
    print(f"    correct (no non-NL pred): {prose_correct}/{prose_total} = {prose_correct/max(prose_total,1):.3f}")
    print(f"    wrong   (had non-NL pred): {prose_wrong}/{prose_total}")
    print()
    print("=== Per-zone-type metrics (IoU>=0.5) ===")
    print(f"  {'type':<18} {'TP':>5} {'softTP':>6} {'FP':>5} {'FN':>5}  {'P':>6}  {'softP':>6}  {'R':>6}  {'F1':>6}  {'meanIoU':>7}")
    total_tp = total_soft = total_fp = total_fn = 0
    for zt in sorted(set(tp) | set(soft_tp) | set(fp) | set(fn)):
        t, st, p, n_ = tp[zt], soft_tp[zt], fp[zt], fn[zt]
        total_tp += t
        total_soft += st
        total_fp += p
        total_fn += n_
        prec = t / (t + p) if (t + p) else 0.0
        soft_prec = st / (st + p) if (st + p) else 0.0
        rec = t / (t + n_) if (t + n_) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        mean_iou = sum(iou_sum[zt]) / len(iou_sum[zt]) if iou_sum[zt] else 0.0
        print(f"  {zt:<18} {t:>5} {st:>6} {p:>5} {n_:>5}  {prec:>6.3f}  {soft_prec:>6.3f}  {rec:>6.3f}  {f1:>6.3f}  {mean_iou:>7.3f}")
    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0
    overall_softp = total_soft / (total_soft + total_fp) if (total_soft + total_fp) else 0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0
    overall_f = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) else 0
    print(f"  {'OVERALL':<18} {total_tp:>5} {total_soft:>6} {total_fp:>5} {total_fn:>5}  {overall_p:>6.3f}  {overall_softp:>6.3f}  {overall_r:>6.3f}  {overall_f:>6.3f}")
    print()
    print(f"  Boundary adjustments (same type, IoU 0.1-0.5): {len(boundary_adjustments)}")


if __name__ == "__main__":
    main()
