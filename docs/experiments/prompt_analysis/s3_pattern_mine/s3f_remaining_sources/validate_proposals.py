"""Validate S3-F proposed patterns against the S2 11K WildChat corpus.

For each proposed pattern: count hits, sample matches for manual FP review.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier.patterns._decoder import _XOR_KEY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("s3f_validate")

SPIKE_DIR = Path(__file__).parent.parent.parent / "s2_spike"
CORPUS = SPIKE_DIR / "corpus.jsonl"
PROPOSALS = Path(__file__).parent / "s3f_proposed_patterns.json"
OUT = Path(__file__).parent / "s3f_corpus_validation.json"


def xor_decode(s: str) -> str:
    b64 = s.removeprefix("xor:")
    raw = base64.b64decode(b64)
    return bytes(b ^ _XOR_KEY for b in raw).decode("utf-8")


def main() -> None:
    corpus = [json.loads(line) for line in CORPUS.read_text().splitlines()]
    proposals = json.load(PROPOSALS.open())["patterns"]
    log.info("corpus: %d prompts, proposals: %d patterns", len(corpus), len(proposals))

    # Compile patterns
    compiled = []
    for p in proposals:
        try:
            compiled.append((p["name"], re.compile(p["regex"]), p))
        except re.error as e:
            log.error("SKIP %s: %s", p["name"], e)

    results = {}
    t0 = time.time()
    for name, regex, meta in compiled:
        hits = 0
        samples = []
        for rec in corpus:
            text = xor_decode(rec["text_xor"])
            matches = list(regex.finditer(text))
            if matches:
                hits += 1
                if len(samples) < 5:
                    samples.append({
                        "fingerprint": rec["sha256"],
                        "length": rec["length"],
                        "bucket": rec["bucket"],
                        "match_count": len(matches),
                        "first_match_snippet": text[max(0, matches[0].start()-20):matches[0].end()+20][:100],
                    })
        results[name] = {
            "hits": hits,
            "hit_rate_pct": round(hits / len(corpus) * 100, 4),
            "samples": samples,
        }
        log.info("  %s: %d hits (%.4f%%)", name, hits, hits / len(corpus) * 100)

    elapsed = time.time() - t0
    out = {
        "corpus_size": len(corpus),
        "pattern_count": len(compiled),
        "elapsed_seconds": round(elapsed, 1),
        "results": results,
    }
    OUT.write_text(json.dumps(out, indent=2))
    log.info("wrote %s in %.1fs", OUT, elapsed)


if __name__ == "__main__":
    main()
