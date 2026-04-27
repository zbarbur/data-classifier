#!/usr/bin/env python3
"""Scan WildChat-1M with the Rust unified detector (zones + secrets).

Reads the local parquet, runs every user prompt through the Rust
UnifiedDetector (zones + secrets in one call), and writes:

  data/wildchat_unified/candidates.jsonl  — ALL prompts with any finding
  data/wildchat_unified/tn_sample.jsonl   — random sample of no-finding prompts
  data/wildchat_unified/scan_stats.json   — aggregate statistics

The candidates file is the input for the prompt_reviewer.py review tool.

Usage:
    .venv/bin/python scripts/scan_wildchat_unified.py

    # Limit to first N user prompts (for testing):
    .venv/bin/python scripts/scan_wildchat_unified.py --limit 5000

    # Include a TN sample for FN discovery:
    .venv/bin/python scripts/scan_wildchat_unified.py --tn-sample 500
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import subprocess
import time
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from data_classifier.patterns._decoder import _XOR_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("scan_wildchat_unified")

PARQUET_PATH = Path("data/wildchat_1m/train.parquet")
PATTERNS_PATH = Path("data_classifier_core/patterns/unified_patterns.json")
OUT_DIR = Path("data/wildchat_unified")


def xor_encode(s: str) -> str:
    raw = bytes(b ^ _XOR_KEY for b in s.encode("utf-8"))
    return base64.b64encode(raw).decode("ascii")


def get_detector_version() -> str:
    """Git SHA + dirty flag for provenance tracking."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], text=True
        ).strip()
        return f"unified-rust-{sha}" + ("-dirty" if dirty else "")
    except Exception:
        return "unified-rust-unknown"


def iter_user_prompts(
    parquet_path: Path, limit: int | None = None, batch_size: int = 500
):
    """Yield (conversation_hash, turn_index, user_text) from local parquet."""
    pf = pq.ParquetFile(str(parquet_path))
    prompt_count = 0

    for batch in pf.iter_batches(
        batch_size=batch_size, columns=["conversation_hash", "conversation"]
    ):
        for i in range(batch.num_rows):
            conv_hash = batch.column("conversation_hash")[i].as_py()
            conversation = batch.column("conversation")[i].as_py()
            if not conversation:
                continue

            for turn_idx, msg in enumerate(conversation):
                if msg.get("role") != "user":
                    continue
                content = msg.get("content") or ""
                if not content.strip():
                    continue

                yield conv_hash, turn_idx, content
                prompt_count += 1

                if limit is not None and prompt_count >= limit:
                    return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Max user prompts to scan")
    parser.add_argument("--tn-sample", type=int, default=200, help="Random TN prompts to keep for FN discovery")
    parser.add_argument("--batch-size", type=int, default=500, help="Parquet read batch size")
    parser.add_argument("--min-confidence", type=float, default=0.3, help="Min secret confidence to keep")
    args = parser.parse_args()

    # Load Rust unified detector
    from data_classifier_core import UnifiedDetector

    patterns_json = PATTERNS_PATH.read_text()
    detector = UnifiedDetector(patterns_json)
    detector_version = get_detector_version()
    log.info("Detector version: %s", detector_version)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Stats counters
    total_prompts = 0
    prompts_with_secrets = 0
    prompts_with_zones = 0
    prompts_with_any = 0
    entity_type_counts: Counter = Counter()
    zone_type_counts: Counter = Counter()
    engine_counts: Counter = Counter()
    confidence_buckets: Counter = Counter()  # low/mid/high

    # TN reservoir sampling
    import random
    tn_reservoir: list[dict] = []
    tn_seen = 0

    t0 = time.time()
    last_report = t0

    candidates_path = OUT_DIR / "candidates.jsonl"
    with open(candidates_path, "w") as f_out:
        for conv_hash, turn_idx, text in iter_user_prompts(
            PARQUET_PATH, limit=args.limit, batch_size=args.batch_size
        ):
            total_prompts += 1

            # Run unified detector
            result_json = detector.detect(text)
            result = json.loads(result_json)

            zones_data = result.get("zones", {})
            zones = zones_data.get("blocks", []) if isinstance(zones_data, dict) else []
            findings = result.get("findings", [])

            # Filter findings by min confidence
            findings = [f for f in findings if f.get("confidence", 0) >= args.min_confidence]

            has_secrets = len(findings) > 0
            has_zones = len(zones) > 0

            if has_secrets:
                prompts_with_secrets += 1
            if has_zones:
                prompts_with_zones += 1

            if has_secrets or has_zones:
                prompts_with_any += 1

                # Build prompt_id from conversation hash + turn
                prompt_id = hashlib.sha256(
                    f"{conv_hash}:{turn_idx}".encode()
                ).hexdigest()[:16]

                # Count stats
                for f in findings:
                    et = f.get("entity_type", "UNKNOWN")
                    entity_type_counts[et] += 1
                    engine_counts[f.get("engine", "unknown")] += 1
                    conf = f.get("confidence", 0)
                    if conf >= 0.85:
                        confidence_buckets["high"] += 1
                    elif conf >= 0.5:
                        confidence_buckets["mid"] += 1
                    else:
                        confidence_buckets["low"] += 1

                for z in zones:
                    zone_type_counts[z.get("zone_type", "unknown")] += 1

                # Strip raw values from findings for safety, keep masked
                safe_findings = []
                for f in findings:
                    match_data = f.get("match", {})
                    safe_findings.append({
                        "entity_type": f.get("entity_type"),
                        "confidence": f.get("confidence"),
                        "engine": f.get("engine"),
                        "evidence": f.get("evidence", ""),
                        "detection_type": f.get("detection_type"),
                        "display_name": f.get("display_name"),
                        "value_masked": match_data.get("value_masked", ""),
                        "start": match_data.get("start", 0),
                        "end": match_data.get("end", 0),
                    })

                record = {
                    "prompt_id": prompt_id,
                    "conv_hash": conv_hash,
                    "turn_idx": turn_idx,
                    "prompt_xor": xor_encode(text),
                    "prompt_length": len(text),
                    "total_lines": text.count("\n") + 1,
                    "detector_version": detector_version,
                    "zones": zones,
                    "secrets": safe_findings,
                    "num_zones": len(zones),
                    "num_secrets": len(safe_findings),
                    "max_secret_confidence": max(
                        (f["confidence"] for f in safe_findings), default=0.0
                    ),
                    "review": None,
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")

            else:
                # TN — reservoir sample
                tn_seen += 1
                if len(tn_reservoir) < args.tn_sample:
                    prompt_id = hashlib.sha256(
                        f"{conv_hash}:{turn_idx}".encode()
                    ).hexdigest()[:16]
                    tn_reservoir.append({
                        "prompt_id": prompt_id,
                        "conv_hash": conv_hash,
                        "turn_idx": turn_idx,
                        "prompt_xor": xor_encode(text),
                        "prompt_length": len(text),
                        "total_lines": text.count("\n") + 1,
                        "detector_version": detector_version,
                        "zones": [],
                        "secrets": [],
                        "num_zones": 0,
                        "num_secrets": 0,
                        "max_secret_confidence": 0.0,
                        "review": None,
                    })
                else:
                    j = random.randint(0, tn_seen - 1)
                    if j < args.tn_sample:
                        prompt_id = hashlib.sha256(
                            f"{conv_hash}:{turn_idx}".encode()
                        ).hexdigest()[:16]
                        tn_reservoir[j] = {
                            "prompt_id": prompt_id,
                            "conv_hash": conv_hash,
                            "turn_idx": turn_idx,
                            "prompt_xor": xor_encode(text),
                            "prompt_length": len(text),
                            "total_lines": text.count("\n") + 1,
                            "detector_version": detector_version,
                            "zones": [],
                            "secrets": [],
                            "num_zones": 0,
                            "num_secrets": 0,
                            "max_secret_confidence": 0.0,
                            "review": None,
                        }

            # Progress reporting
            now = time.time()
            if now - last_report >= 10:
                elapsed = now - t0
                rate = total_prompts / elapsed
                log.info(
                    "Progress: %d prompts (%.0f/s) | %d candidates (%d secrets, %d zones) | %.0fs elapsed",
                    total_prompts,
                    rate,
                    prompts_with_any,
                    prompts_with_secrets,
                    prompts_with_zones,
                    elapsed,
                )
                last_report = now

    elapsed = time.time() - t0

    # Write TN sample
    tn_path = OUT_DIR / "tn_sample.jsonl"
    with open(tn_path, "w") as f:
        for rec in tn_reservoir:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Write stats
    stats = {
        "detector_version": detector_version,
        "scan_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "parquet_path": str(PARQUET_PATH),
        "limit": args.limit,
        "min_confidence": args.min_confidence,
        "total_prompts": total_prompts,
        "prompts_with_secrets": prompts_with_secrets,
        "prompts_with_zones": prompts_with_zones,
        "prompts_with_any": prompts_with_any,
        "prompts_clean": total_prompts - prompts_with_any,
        "tn_sample_size": len(tn_reservoir),
        "elapsed_seconds": round(elapsed, 1),
        "prompts_per_second": round(total_prompts / elapsed, 1) if elapsed > 0 else 0,
        "entity_type_counts": dict(entity_type_counts.most_common()),
        "zone_type_counts": dict(zone_type_counts.most_common()),
        "engine_counts": dict(engine_counts.most_common()),
        "confidence_buckets": dict(confidence_buckets),
    }
    stats_path = OUT_DIR / "scan_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2))

    log.info("=" * 60)
    log.info("SCAN COMPLETE")
    log.info("  Total prompts scanned: %d", total_prompts)
    log.info("  Candidates (any finding): %d (%.2f%%)", prompts_with_any, 100 * prompts_with_any / max(total_prompts, 1))
    log.info("    - with secrets: %d", prompts_with_secrets)
    log.info("    - with zones: %d", prompts_with_zones)
    log.info("  TN sample: %d", len(tn_reservoir))
    log.info("  Elapsed: %.1fs (%.0f prompts/s)", elapsed, total_prompts / max(elapsed, 1))
    log.info("  Output: %s", candidates_path)
    log.info("  Stats: %s", stats_path)
    log.info("=" * 60)

    # Print top entity types
    log.info("Top entity types:")
    for et, count in entity_type_counts.most_common(15):
        log.info("  %s: %d", et, count)

    log.info("Zone types:")
    for zt, count in zone_type_counts.most_common():
        log.info("  %s: %d", zt, count)


if __name__ == "__main__":
    main()
