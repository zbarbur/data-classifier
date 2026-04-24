#!/usr/bin/env python3
"""Rebuild WildChat eval GT with the current scanner.

Runs scan_text on every prompt and categorises each finding as:
  - auto_tp:  high-confidence regex match or high-confidence KV/opaque (≥0.85)
  - review:   lower-confidence findings that need human judgement
  - auto_tn:  no findings at all

Outputs:
  1. data/wildchat_eval/wildchat_eval_v2.jsonl  — new GT (auto-labeled)
  2. data/wildchat_eval/review_cases.jsonl      — edge cases for human review
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from data_classifier.patterns._decoder import decode_encoded_strings
from data_classifier.scan_text import TextScanner

logging.basicConfig(level=logging.WARNING)

EVAL_PATH = Path("data/wildchat_eval/wildchat_eval.jsonl")
OUT_PATH = Path("data/wildchat_eval/wildchat_eval_v2.jsonl")
REVIEW_PATH = Path("data/wildchat_eval/review_cases.jsonl")

# Thresholds
AUTO_TP_CONFIDENCE = 0.85  # ≥ this = auto-label TP
REVIEW_CONFIDENCE = 0.30  # findings between 0.30 and 0.85 need review


def main() -> None:
    if not EVAL_PATH.exists():
        print(f"Error: {EVAL_PATH} not found", file=sys.stderr)
        sys.exit(1)

    with open(EVAL_PATH) as f:
        rows = [json.loads(line) for line in f]

    scanner = TextScanner()
    scanner.startup()

    gt_rows: list[dict] = []
    review_rows: list[dict] = []
    stats = {"auto_tp": 0, "auto_tn": 0, "review": 0, "total": len(rows)}

    for i, row in enumerate(rows):
        if i % 500 == 0:
            print(f"  Processing {i}/{len(rows)}...", file=sys.stderr)

        text = decode_encoded_strings(["xor:" + row["prompt_xor"]])[0]
        result = scanner.scan(text)

        findings_out = []
        needs_review = False

        for f in result.findings:
            finding_dict = {
                "entity_type": f.entity_type,
                "detection_type": f.detection_type,
                "confidence": f.confidence,
                "engine": f.engine,
                "start": f.start,
                "end": f.end,
                "value_preview": text[f.start : f.end][:80],
            }

            if f.engine == "regex" or f.confidence >= AUTO_TP_CONFIDENCE:
                finding_dict["label"] = "auto_tp"
            else:
                finding_dict["label"] = "review"
                needs_review = True

            findings_out.append(finding_dict)

        has_credential = len(findings_out) > 0

        gt_row = {
            "prompt_id": row["prompt_id"],
            "prompt_xor": row["prompt_xor"],
            "findings": findings_out,
            "has_credential": has_credential,
            "num_findings": len(findings_out),
            "scanned_length": len(text),
        }
        gt_rows.append(gt_row)

        if needs_review:
            # Build review entry with context
            review_findings = [f for f in findings_out if f["label"] == "review"]
            review_rows.append(
                {
                    "prompt_id": row["prompt_id"],
                    "text_preview": text[:300],
                    "findings": review_findings,
                    "all_findings_count": len(findings_out),
                    # Human fills this in:
                    "verdict": None,  # "tp" | "fp" | "partial" (some TP, some FP)
                    "notes": "",
                }
            )

        if has_credential:
            if needs_review:
                stats["review"] += 1
            else:
                stats["auto_tp"] += 1
        else:
            stats["auto_tn"] += 1

    # Write outputs
    with open(OUT_PATH, "w") as f:
        for row in gt_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with open(REVIEW_PATH, "w") as f:
        for row in review_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("\nGT rebuild complete:")
    print(f"  Total prompts:   {stats['total']}")
    print(f"  Auto TP:         {stats['auto_tp']} ({stats['auto_tp'] / stats['total'] * 100:.1f}%)")
    print(f"  Auto TN:         {stats['auto_tn']} ({stats['auto_tn'] / stats['total'] * 100:.1f}%)")
    print(f"  Needs review:    {stats['review']} ({stats['review'] / stats['total'] * 100:.1f}%)")
    print("\nOutputs:")
    print(f"  GT:     {OUT_PATH}")
    print(f"  Review: {REVIEW_PATH} ({len(review_rows)} cases)")


if __name__ == "__main__":
    main()
