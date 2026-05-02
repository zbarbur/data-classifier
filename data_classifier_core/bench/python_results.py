"""Output per-prompt detection results for parity comparison with Rust."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docs.experiments.prompt_analysis.s4_zone_detection.v2 import detect_zones

CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs/experiments/prompt_analysis/s4_zone_detection/labeled_data/s4_labeled_corpus.jsonl"
)
OUTPUT_PATH = Path("/tmp/python_results.jsonl")


def main():
    records = []
    with open(CORPUS_PATH) as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            review = r.get("review") or {}
            if review.get("correct") is not None:
                records.append(r)

    start = time.time()
    with open(OUTPUT_PATH, "w") as out:
        for r in records:
            text = r.get("text", "")
            if not text:
                continue
            result = detect_zones(text, prompt_id=r.get("prompt_id", ""))
            blocks = [
                {
                    "start_line": b.start_line,
                    "end_line": b.end_line,
                    "zone_type": b.zone_type,
                    "confidence": round(b.confidence, 3),
                    "method": b.method,
                    "language_hint": b.language_hint,
                }
                for b in result.blocks
            ]
            out.write(
                json.dumps(
                    {
                        "prompt_id": r.get("prompt_id", ""),
                        "has_blocks": len(result.blocks) > 0,
                        "block_count": len(result.blocks),
                        "blocks": blocks,
                    }
                )
                + "\n"
            )

    elapsed = time.time() - start
    print(f"Processed {len(records)} records in {elapsed:.1f}s ({len(records) / elapsed:.0f} prompts/sec)")
    print(f"Results written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
