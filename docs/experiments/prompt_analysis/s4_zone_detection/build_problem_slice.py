"""Extract prompts that still have FP or FN after the markup fixes.

Re-runs the (now-fixed) detector on each of the originally-reviewed 50 prompts,
identifies which still mismatch the user's gold, and writes a focused
re-review slice with FRESH predictions and `review` cleared so the user can
look at them with fresh eyes.

Usage:
    python build_problem_slice.py
    # then launch reviewer on the output file
"""

from __future__ import annotations

import json
from pathlib import Path

from data_classifier_core import UnifiedDetector

SLICE_PATH = Path("docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_relabel_slice.jsonl")
PATTERNS_PATH = Path("data_classifier_core/patterns/unified_patterns.json")
OUT_PATH = Path("docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_problem_slice.jsonl")
NON_PROSE = {"code", "markup", "config", "data", "query", "cli_shell"}
IOU_MIN = 0.5


def block_iou(a: dict, b: dict) -> float:
    a0, a1 = a["start_line"], a["end_line"]
    b0, b1 = b["start_line"], b["end_line"]
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def gold_blocks(record: dict) -> list[dict]:
    rev = record.get("review") or {}
    if rev.get("correct") is True:
        return [b for b in (record.get("heuristic_blocks") or []) if b["zone_type"] in NON_PROSE]
    return rev.get("actual_blocks") or []


def main() -> None:
    detector = UnifiedDetector(PATTERNS_PATH.read_text())

    problem_records = []
    with SLICE_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            text = r["text"]
            gold = gold_blocks(r)

            res = json.loads(detector.detect(text))
            blocks = (res.get("zones") or {}).get("blocks") or []
            non_nl_pred = [b for b in blocks if b["zone_type"] in NON_PROSE]

            has_fn = False
            has_fp = False
            matched_pred = set()
            for g in gold:
                best_iou, best_idx = 0.0, -1
                for i, p in enumerate(non_nl_pred):
                    if i in matched_pred or p["zone_type"] != g["zone_type"]:
                        continue
                    iou = block_iou(g, p)
                    if iou > best_iou:
                        best_iou, best_idx = iou, i
                if best_idx >= 0 and best_iou >= IOU_MIN:
                    matched_pred.add(best_idx)
                else:
                    has_fn = True
            for i in range(len(non_nl_pred)):
                if i not in matched_pred:
                    has_fp = True
                    break

            if has_fp or has_fn:
                # Build a fresh record with the LATEST detector predictions
                # and a cleared review for re-labeling
                fresh = {
                    "prompt_id": r["prompt_id"],
                    "text": text,
                    "total_lines": r.get("total_lines", text.count("\n") + 1),
                    "previous_gold": gold,  # what the user said before
                    "heuristic_blocks": blocks,  # latest predictions
                    "review": None,
                }
                problem_records.append(fresh)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for r in problem_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {len(problem_records)} problem prompts to {OUT_PATH}")
    for r in problem_records:
        types = sorted({b["zone_type"] for b in r["heuristic_blocks"] if b["zone_type"] in NON_PROSE})
        print(f"  {r['prompt_id']}: {len(r['heuristic_blocks'])} pred blocks, prev_gold={len(r['previous_gold'])} types_pred={types}")


if __name__ == "__main__":
    main()
