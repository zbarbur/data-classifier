"""S2 spike: WildChat-1M → 11K-prompt corpus (10K random + 1K longest).

Loads WildChat-1M from local DVC data (data/wildchat_1m/) if available,
falls back to HuggingFace streaming. Dedupes by SHA-256, splits into a
random sample (first 10K by stream order) and a long-prompt sample
(top-1K longest from the remaining 10K). XOR-encodes prompt text per
project rule.

Run: .venv/bin/python docs/experiments/prompt_analysis/s2_spike/extract_corpus.py
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import random
from pathlib import Path

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier.patterns._decoder import _XOR_KEY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("s2_corpus")


def xor_encode(s: str) -> str:
    raw = bytes(b ^ _XOR_KEY for b in s.encode("utf-8"))
    return "xor:" + base64.b64encode(raw).decode("ascii")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream-size", type=int, default=20_000)
    ap.add_argument("--random-size", type=int, default=10_000)
    ap.add_argument("--long-size", type=int, default=1_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(Path(__file__).parent / "corpus.jsonl"))
    args = ap.parse_args()

    if args.random_size + args.long_size > args.stream_size:
        raise SystemExit(
            f"stream-size ({args.stream_size}) must be >= random + long ({args.random_size + args.long_size})"
        )

    random.seed(args.seed)

    from data_classifier.datasets import load_local_or_remote

    log.info("loading WildChat-1M (local DVC or HuggingFace fallback)")
    ds = load_local_or_remote("wildchat_1m")

    seen: set[str] = set()
    records: list[dict] = []
    for row in ds:
        if len(records) >= args.stream_size:
            break
        for msg in row.get("conversation", []):
            if msg.get("role") != "user":
                continue
            text = msg.get("content", "") or ""
            if not text.strip():
                continue
            fp = hashlib.sha256(text.encode()).hexdigest()[:16]
            if fp in seen:
                continue
            seen.add(fp)
            records.append(
                {
                    "turn_index": len(records),
                    "length": len(text),
                    "sha256": fp,
                    "text_xor": xor_encode(text),
                }
            )
            if len(records) >= args.stream_size:
                break
        if (len(records) % 5_000) == 0 and len(records) > 0:
            log.info("collected %d unique user-turns", len(records))

    log.info("collected %d unique user-turns total", len(records))

    # Stable shuffle for reproducibility, then split.
    random.shuffle(records)
    random_recs = records[: args.random_size]
    remaining = records[args.random_size :]
    remaining.sort(key=lambda r: r["length"], reverse=True)
    long_recs = remaining[: args.long_size]

    for r in random_recs:
        r["bucket"] = "random"
    for r in long_recs:
        r["bucket"] = "long"

    out_records = random_recs + long_recs
    with open(args.out, "w") as f:
        for r in out_records:
            f.write(json.dumps(r) + "\n")

    avg_random_len = sum(r["length"] for r in random_recs) / len(random_recs)
    avg_long_len = sum(r["length"] for r in long_recs) / len(long_recs)
    log.info(
        "wrote %d records: %d random (avg %.0f chars) + %d long (avg %.0f chars) → %s",
        len(out_records),
        len(random_recs),
        avg_random_len,
        len(long_recs),
        avg_long_len,
        args.out,
    )


if __name__ == "__main__":
    main()
