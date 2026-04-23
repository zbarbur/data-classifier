"""Text-path benchmark — scan_text accuracy on WildChat credential prompts.

Loads the WildChat eval dataset (built by scripts/build_wildchat_eval.py),
re-runs scan_text on each prompt, and computes precision/recall/F1 for
credential detection. This is the text-path equivalent of the family
accuracy benchmark's family_macro_f1.

Usage:
    .venv/bin/python -m tests.benchmarks.text_path_benchmark \
        --eval-data data/wildchat_eval/wildchat_eval.jsonl \
        --summary /tmp/text_bench.summary.json
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)


def run_benchmark(
    eval_path: Path,
    *,
    min_confidence: float = 0.3,
) -> dict:
    """Run text-path benchmark and return metrics dict."""
    from data_classifier.patterns._decoder import decode_encoded_strings
    from data_classifier.scan_text import TextScanner

    scanner = TextScanner()
    scanner.startup()

    with open(eval_path) as f:
        rows = [json.loads(line) for line in f]

    total = len(rows)
    gt_positive = sum(1 for r in rows if r["has_credential"])
    gt_negative = total - gt_positive

    tp = fp = fn = tn = 0
    entity_counts: Counter[str] = Counter()
    scan_times: list[float] = []

    for row in rows:
        gt_has_cred = row["has_credential"]

        # Decode prompt from xor encoding
        [text] = decode_encoded_strings([row["prompt_xor"]])

        t0 = time.perf_counter()
        result = scanner.scan(text, min_confidence=min_confidence)
        scan_times.append(time.perf_counter() - t0)

        pred_has_cred = len(result.findings) > 0

        if gt_has_cred and pred_has_cred:
            tp += 1
        elif not gt_has_cred and pred_has_cred:
            fp += 1
        elif gt_has_cred and not pred_has_cred:
            fn += 1
        else:
            tn += 1

        for f in result.findings:
            entity_counts[f.entity_type] += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    scan_times.sort()
    p50 = scan_times[len(scan_times) // 2] if scan_times else 0.0
    p95 = scan_times[int(len(scan_times) * 0.95)] if scan_times else 0.0
    p99 = scan_times[int(len(scan_times) * 0.99)] if scan_times else 0.0

    return {
        "total_prompts": total,
        "gt_positive": gt_positive,
        "gt_negative": gt_negative,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "entity_type_counts": dict(entity_counts.most_common()),
        "latency_ms": {
            "p50": round(p50 * 1000, 2),
            "p95": round(p95 * 1000, 2),
            "p99": round(p99 * 1000, 2),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Text-path benchmark")
    parser.add_argument("--eval-data", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--min-confidence", type=float, default=0.3)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    logger.info("Running text-path benchmark on %s", args.eval_data)
    metrics = run_benchmark(args.eval_data, min_confidence=args.min_confidence)

    print(json.dumps(metrics, indent=2))

    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(metrics, indent=2))
        logger.info("Summary written to %s", args.summary)


if __name__ == "__main__":
    main()
