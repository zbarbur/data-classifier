"""Build labeled evaluation dataset from WildChat credential prompts.

Scans the 3,515 WildChat credential prompts with scan_text and saves
results as a labeled JSONL dataset for the text-path benchmark.

Usage:
    .venv/bin/python scripts/build_wildchat_eval.py \
        --input data/wildchat_1m_credential_prompts.jsonl \
        --output data/wildchat_eval/wildchat_eval.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build WildChat eval dataset")
    parser.add_argument("--input", type=Path, required=True, help="Input credential prompts JSONL (xor-encoded)")
    parser.add_argument("--output", type=Path, required=True, help="Output eval dataset JSONL")
    parser.add_argument("--min-confidence", type=float, default=0.3)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    from data_classifier.patterns._decoder import decode_encoded_strings
    from data_classifier.scan_text import TextScanner

    scanner = TextScanner()
    scanner.startup()
    logger.info("Scanner initialized")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with_cred = 0
    with open(args.input) as fin, open(args.output, "w") as fout:
        for line in fin:
            row = json.loads(line)

            # Decode xor-encoded prompt
            prompt_xor = row.get("prompt_xor", "")
            if not prompt_xor:
                continue
            [text] = decode_encoded_strings([prompt_xor])

            result = scanner.scan(text, min_confidence=args.min_confidence)
            findings_data = [
                {
                    "entity_type": f.entity_type,
                    "detection_type": f.detection_type,
                    "confidence": f.confidence,
                    "engine": f.engine,
                    "start": f.start,
                    "end": f.end,
                }
                for f in result.findings
            ]

            has_credential = len(findings_data) > 0
            if has_credential:
                with_cred += 1

            out_row = {
                "prompt_id": count,
                "prompt_xor": prompt_xor,
                "findings": findings_data,
                "has_credential": has_credential,
                "num_findings": len(findings_data),
                "scanned_length": result.scanned_length,
            }
            fout.write(json.dumps(out_row) + "\n")
            count += 1

            if count % 500 == 0:
                logger.info("Processed %d prompts (%d with credentials)", count, with_cred)

    logger.info("Done. %d prompts → %s (%d with credentials)", count, args.output, with_cred)


if __name__ == "__main__":
    main()
