#!/usr/bin/env python3
"""Build a reviewer-compatible corpus from WildChat eval edge cases.

Converts the review_cases.jsonl (from rebuild_wildchat_gt.py) into the format
expected by prompt_reviewer.py. Decodes XOR-encoded prompts to plain text.

Usage:
    .venv/bin/python scripts/build_review_corpus.py

Then review:
    .venv/bin/python docs/experiments/prompt_analysis/tools/prompt_reviewer.py \
        --corpus data/wildchat_eval/review_corpus.jsonl --port 8234
"""

from __future__ import annotations

import json
from pathlib import Path

from data_classifier.patterns._decoder import decode_encoded_strings

EVAL_PATH = Path("data/wildchat_eval/wildchat_eval_v2.jsonl")
OUT_PATH = Path("data/wildchat_eval/review_corpus.jsonl")


def main() -> None:
    with open(EVAL_PATH) as f:
        rows = [json.loads(line) for line in f]

    # Select only prompts with at least one "review" finding
    review_rows = []
    for row in rows:
        review_findings = [f for f in row["findings"] if f.get("label") == "review"]
        if not review_findings:
            continue

        text = decode_encoded_strings(["xor:" + row["prompt_xor"]])[0]

        review_rows.append(
            {
                "prompt_id": str(row["prompt_id"]),
                "text": text,
                "total_lines": text.count("\n") + 1,
                # Pre-populate with empty heuristic_blocks (zone detection not needed)
                "heuristic_has_blocks": False,
                "heuristic_blocks": [],
                # Store our pre-computed findings for reference
                "precomputed_findings": row["findings"],
                "review": None,
            }
        )

    with open(OUT_PATH, "w") as f:
        for row in review_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Review corpus: {len(review_rows)} prompts → {OUT_PATH}")
    print("\nTo review:")
    print("  .venv/bin/python docs/experiments/prompt_analysis/tools/prompt_reviewer.py \\")
    print(f"      --corpus {OUT_PATH} --port 8234")


if __name__ == "__main__":
    main()
