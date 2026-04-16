"""S0 v2 — curate ALL credential findings + sample non-credential findings.

Streams WildChat-1M, runs regex_engine + secret_scanner, and captures:

  - s0_credentials.jsonl       — EVERY CREDENTIAL-family finding (not sampled)
                                 with full prompt context, prompt fingerprint
                                 for dedup, and engine evidence. XOR-encoded.
  - s0_non_credential_sample.jsonl — RANDOM SAMPLE of non-credential findings
                                 (URL, SWIFT_BIC, IP, EMAIL, MAC, DOB, PHONE)
                                 to verify we don't have FP problems on the
                                 credential side that masquerade as other types.

Both outputs include prompt SHA-256 fingerprints for deduplication. WildChat
contains heavy prompt duplication (same homework assignments, same scraper
scripts) so dedup matters for the headline numbers.

Engines: regex_engine + secret_scanner (ML disabled).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Iterator

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier import ColumnInput, load_profile  # noqa: E402
from data_classifier.core.taxonomy import ENTITY_TYPE_TO_FAMILY  # noqa: E402
from data_classifier.engines.regex_engine import RegexEngine  # noqa: E402
from data_classifier.engines.secret_scanner import SecretScannerEngine  # noqa: E402
from data_classifier.patterns._decoder import _XOR_KEY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("s0v2")


def xor_encode(s: str) -> str:
    raw = bytes(b ^ _XOR_KEY for b in s.encode("utf-8"))
    return "xor:" + base64.b64encode(raw).decode("ascii")


def iter_user_turns(limit: int | None) -> Iterator[tuple[int, str]]:
    from datasets import load_dataset

    log.info("loading allenai/WildChat-1M (streaming=True)")
    ds = load_dataset("allenai/WildChat-1M", split="train", streaming=True)
    turn_idx = 0
    for row in ds:
        for msg in row.get("conversation", []):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "") or ""
            if not content.strip():
                continue
            yield turn_idx, content
            turn_idx += 1
            if limit is not None and turn_idx >= limit:
                return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--out-dir", default="docs/experiments/prompt_analysis/s0_artifacts")
    parser.add_argument("--non-cred-sample-rate", type=float, default=0.05,
                        help="Fraction of non-credential findings to capture for FP audit")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    profile = load_profile("standard")
    regex_engine = RegexEngine(); regex_engine.startup()
    secret_engine = SecretScannerEngine(); secret_engine.startup()

    cred_records: list[dict] = []
    non_cred_records: list[dict] = []

    t0 = time.time()
    log.info("starting curate scan limit=%s", args.limit)

    for idx, text in iter_user_turns(args.limit):
        if (idx + 1) % 10000 == 0:
            elapsed = time.time() - t0
            log.info("processed %d (%.0f/sec) | cred=%d non_cred=%d",
                     idx + 1, (idx + 1) / elapsed, len(cred_records), len(non_cred_records))

        col = ColumnInput(column_name="prompt", sample_values=[text])
        try:
            findings = regex_engine.classify_column(col, profile=profile, min_confidence=0.5, max_evidence_samples=10) \
                + secret_engine.classify_column(col, profile=profile, min_confidence=0.5, max_evidence_samples=10)
        except Exception as e:
            log.debug("engine error idx=%d: %s", idx, e)
            continue

        if not findings:
            continue

        prompt_fp = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        for f in findings:
            family = ENTITY_TYPE_TO_FAMILY.get(f.entity_type, "OTHER")
            record = {
                "turn_index": idx,
                "prompt_fingerprint": prompt_fp,
                "prompt_length": len(text),
                "entity_type": f.entity_type,
                "family": family,
                "confidence": f.confidence,
                "engine": f.engine,
                "evidence": f.evidence,
                "prompt_xor": xor_encode(text),
            }
            if family == "CREDENTIAL":
                cred_records.append(record)
            elif random.random() < args.non_cred_sample_rate:
                non_cred_records.append(record)

    elapsed = time.time() - t0
    log.info("scan complete in %.1fs", elapsed)
    log.info("CREDENTIAL findings (all kept): %d", len(cred_records))
    log.info("non-credential findings (sampled at %.0f%%): %d", args.non_cred_sample_rate * 100, len(non_cred_records))

    # Dedup analysis
    cred_fps = {r["prompt_fingerprint"]: 0 for r in cred_records}
    for r in cred_records:
        cred_fps[r["prompt_fingerprint"]] += 1
    log.info("Distinct prompts with credentials: %d (out of %d hits)", len(cred_fps), len(cred_records))

    with (out_dir / "s0_credentials.jsonl").open("w") as f:
        for r in cred_records:
            f.write(json.dumps(r) + "\n")

    with (out_dir / "s0_non_credential_sample.jsonl").open("w") as f:
        for r in non_cred_records:
            f.write(json.dumps(r) + "\n")

    # Summary stats
    from collections import Counter
    cred_by_type = Counter(r["entity_type"] for r in cred_records)
    cred_by_engine = Counter(r["engine"] for r in cred_records)
    non_cred_by_type = Counter(r["entity_type"] for r in non_cred_records)
    summary = {
        "limit": args.limit,
        "elapsed_seconds": elapsed,
        "credential_findings_total": len(cred_records),
        "credential_distinct_prompts": len(cred_fps),
        "credential_by_entity_type": dict(cred_by_type.most_common()),
        "credential_by_engine": dict(cred_by_engine.most_common()),
        "non_credential_sample_rate": args.non_cred_sample_rate,
        "non_credential_sample_size": len(non_cred_records),
        "non_credential_by_entity_type": dict(non_cred_by_type.most_common()),
    }
    (out_dir / "s0_curate_summary.json").write_text(json.dumps(summary, indent=2))
    log.info("wrote artifacts to %s", out_dir)


if __name__ == "__main__":
    main()
