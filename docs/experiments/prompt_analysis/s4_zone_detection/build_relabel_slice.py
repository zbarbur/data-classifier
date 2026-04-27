"""Build a stratified 50-prompt slice for clean re-labeling.

Pulls from the existing s4_labeled_corpus, runs the new Rust UnifiedDetector
on each, and selects examples that exercise the cases where validation gave
suspect signals:

  - 12 "code FP candidates": GT had no blocks but our detector predicts code
    (these are the ones we suspect are missed labels, not real FPs)
  - 10 "code GT" : GT marked code — boundary accuracy check
  - 8  "config/data/markup GT": rare label types (only 13/7/34 in corpus)
  - 10 "agree-no-blocks": GT empty AND we predict only NL — sanity floor
  - 10 "high-confidence multi-line": our detector confident, multi-line —
    spot-check confidence calibration

Output:
  docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/
    s4_relabel_slice.jsonl  (50 records, review field cleared,
                              has fresh `pred_blocks` from new detector)
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from data_classifier_core import UnifiedDetector

LABELED_PATH = Path("docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl")
PATTERNS_PATH = Path("data_classifier_core/patterns/unified_patterns.json")
OUT_PATH = Path("docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_relabel_slice.jsonl")
NON_PROSE = {"code", "markup", "config", "data"}
SEED = 42


def block_iou(a: dict, b: dict) -> float:
    a0, a1 = a["start_line"], a["end_line"]
    b0, b1 = b["start_line"], b["end_line"]
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def main() -> None:
    rng = random.Random(SEED)
    detector = UnifiedDetector(PATTERNS_PATH.read_text())

    bucket_fp = []          # GT empty, pred code
    bucket_gt_code = []     # GT has code
    bucket_rare = []        # GT has config/data/markup
    bucket_clean = []       # GT empty, pred only NL
    bucket_highconf = []    # multi-line, high-confidence pred

    print("Pre-running detector on full 1,954-prompt corpus to bucket...")
    with LABELED_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            text = r["text"]
            gt = (r.get("review") or {}).get("actual_blocks") or []

            res = json.loads(detector.detect(text))
            blocks = (res.get("zones") or {}).get("blocks") or []
            non_nl = [b for b in blocks if b["zone_type"] in NON_PROSE]

            row = {
                "prompt_id": r["prompt_id"],
                "text": text,
                "total_lines": r.get("total_lines", text.count("\n") + 1),
                "gt_blocks": gt,
                "pred_blocks": blocks,  # full predictions for the reviewer
                "review": None,         # cleared for fresh labeling
            }

            if not gt and any(b["zone_type"] == "code" for b in non_nl):
                bucket_fp.append(row)
            if any(g["zone_type"] == "code" for g in gt):
                bucket_gt_code.append(row)
            if any(g["zone_type"] in ("config", "data", "markup") for g in gt):
                bucket_rare.append(row)
            if not gt and not non_nl:
                bucket_clean.append(row)
            if row["total_lines"] >= 5 and any(
                b["zone_type"] in NON_PROSE and b["confidence"] >= 0.85 for b in blocks
            ):
                bucket_highconf.append(row)

    print(f"  bucket_fp (GT∅, pred code): {len(bucket_fp)}")
    print(f"  bucket_gt_code:             {len(bucket_gt_code)}")
    print(f"  bucket_rare (config/data/markup GT): {len(bucket_rare)}")
    print(f"  bucket_clean (GT∅, pred ∅): {len(bucket_clean)}")
    print(f"  bucket_highconf:            {len(bucket_highconf)}")

    def take(bucket: list[dict], n: int) -> list[dict]:
        rng.shuffle(bucket)
        return bucket[:n]

    selected = (
        take(bucket_fp, 12)
        + take(bucket_gt_code, 10)
        + take(bucket_rare, 8)
        + take(bucket_clean, 10)
        + take(bucket_highconf, 10)
    )

    # Dedup by prompt_id (a prompt can match multiple buckets)
    seen = set()
    unique = []
    for r in selected:
        if r["prompt_id"] in seen:
            continue
        seen.add(r["prompt_id"])
        unique.append(r)

    print(f"\nSelected: {len(selected)} (with dups), {len(unique)} unique")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for r in unique:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
