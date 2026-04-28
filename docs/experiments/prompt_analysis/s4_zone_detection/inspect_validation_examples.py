"""Surface concrete FP/FN examples from the validation run.

Three buckets:
  1) FP-code on pure-prose: GT empty, pred has 'code' block — sample 5
  2) FN-code we missed: GT has 'code', no matching pred — sample 5
  3) CONFIG/DATA — full list since recall is 0 (we want to see what the labels
     look like vs what our detector returns).
"""

from __future__ import annotations

import json
from pathlib import Path

from data_classifier_core import UnifiedDetector

LABELED_PATH = Path("docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl")
PATTERNS_PATH = Path("data_classifier_core/patterns/unified_patterns.json")
NON_PROSE = {"code", "markup", "config", "data"}


def block_iou(a: dict, b: dict) -> float:
    a0, a1 = a["start_line"], a["end_line"]
    b0, b1 = b["start_line"], b["end_line"]
    inter = max(0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def show_block(text: str, b: dict, max_lines: int = 6) -> str:
    lines = text.split("\n")
    s, e = b["start_line"], b["end_line"]
    snippet = lines[s : min(e, s + max_lines)]
    extra = f" …(+{e - s - max_lines} more)" if e - s > max_lines else ""
    return "\n    | " + "\n    | ".join(snippet) + extra


def main() -> None:
    detector = UnifiedDetector(PATTERNS_PATH.read_text())

    fp_code = []  # GT empty, predicted code
    fn_code = []  # GT has code, no matching pred
    config_examples = []  # all GT config rows
    data_examples = []  # all GT data rows

    with LABELED_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            text = r["text"]
            gt = (r.get("review") or {}).get("actual_blocks") or []

            res = json.loads(detector.detect(text))
            blocks = (res.get("zones") or {}).get("blocks") or []
            non_nl_pred = [b for b in blocks if b["zone_type"] in NON_PROSE]

            # Bucket 1: pure prose mis-fired as code
            if not gt and any(b["zone_type"] == "code" for b in non_nl_pred):
                if len(fp_code) < 5:
                    fp_code.append((r, blocks))

            # Bucket 2: real code missed
            for g in gt:
                if g["zone_type"] == "code":
                    matched = any(p["zone_type"] == "code" and block_iou(g, p) >= 0.5 for p in non_nl_pred)
                    if not matched and len(fn_code) < 5:
                        fn_code.append((r, blocks, g))

            # Bucket 3: every GT config/data
            for g in gt:
                if g["zone_type"] == "config":
                    config_examples.append((r, blocks, g))
                if g["zone_type"] == "data":
                    data_examples.append((r, blocks, g))

    def print_pred(blocks):
        if not blocks:
            return "    (no predictions)"
        return "\n".join(
            f"    pred: {b['zone_type']:<16} lines {b['start_line']}-{b['end_line']} "
            f"method={b.get('method', '?')} conf={b['confidence']:.2f} hint={b.get('language_hint', '')}"
            for b in blocks
        )

    print("=" * 70)
    print("FP-code (pure prose mis-detected as code) — 5 examples")
    print("=" * 70)
    for r, blocks in fp_code:
        print(f"\nprompt_id={r['prompt_id']} (lines={r['total_lines']})")
        print(f"  text: {repr(r['text'][:200])}{'…' if len(r['text']) > 200 else ''}")
        print(print_pred(blocks))

    print()
    print("=" * 70)
    print("FN-code (we missed real code) — 5 examples")
    print("=" * 70)
    for r, blocks, g in fn_code:
        print(f"\nprompt_id={r['prompt_id']} (lines={r['total_lines']})")
        print(f"  GT: code lines {g['start_line']}-{g['end_line']}")
        print(f"  GT snippet:{show_block(r['text'], g)}")
        print(print_pred(blocks))

    print()
    print("=" * 70)
    print(f"CONFIG ground-truth — all {len(config_examples)} rows")
    print("=" * 70)
    for r, blocks, g in config_examples:
        print(f"\nprompt_id={r['prompt_id']} GT: config lines {g['start_line']}-{g['end_line']}")
        print(f"  GT snippet:{show_block(r['text'], g, 4)}")
        print(print_pred(blocks))

    print()
    print("=" * 70)
    print(f"DATA ground-truth — all {len(data_examples)} rows")
    print("=" * 70)
    for r, blocks, g in data_examples:
        print(f"\nprompt_id={r['prompt_id']} GT: data lines {g['start_line']}-{g['end_line']}")
        print(f"  GT snippet:{show_block(r['text'], g, 4)}")
        print(print_pred(blocks))


if __name__ == "__main__":
    main()
