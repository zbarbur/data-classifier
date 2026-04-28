#!/usr/bin/env python3
"""Scan WildChat-1M with the Rust unified detector (zones + secrets).

Reads the local parquet, runs every user prompt through the Rust
UnifiedDetector (zones + secrets in one call), and writes:

  data/wildchat_unified/candidates.jsonl  — prompts with any finding
  data/wildchat_unified/tn_sample.jsonl   — random sample of no-finding prompts
  data/wildchat_unified/scan_stats.json   — aggregate statistics
  data/wildchat_unified/scan_index.jsonl  — lightweight record for EVERY prompt

The candidates file is the input for the prompt_reviewer.py review tool.

Resume-safe: on restart, reads existing candidates.jsonl AND scan_index.jsonl
and skips already-processed prompt_ids.  Per-prompt timeout prevents hangs on
pathological inputs.

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
import signal
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

# Per-prompt timeout in seconds.  If the Rust detector takes longer than
# this on a single prompt (catastrophic backtracking), skip it.
PROMPT_TIMEOUT_SECONDS = 10


class PromptTimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise PromptTimeoutError()


def xor_encode(s: str) -> str:
    raw = bytes(b ^ _XOR_KEY for b in s.encode("utf-8"))
    return base64.b64encode(raw).decode("ascii")


def get_detector_version() -> str:
    """Git SHA + dirty flag for provenance tracking."""
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        return f"unified-rust-{sha}" + ("-dirty" if dirty else "")
    except Exception:
        return "unified-rust-unknown"


def make_prompt_id(conv_hash: str, turn_idx: int) -> str:
    return hashlib.sha256(f"{conv_hash}:{turn_idx}".encode()).hexdigest()[:16]


def load_existing_prompt_ids(path: Path) -> set[str]:
    """Read existing candidates file and return set of prompt_ids for resume."""
    ids: set[str] = set()
    if not path.exists():
        return ids
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                pid = rec.get("prompt_id")
                if pid:
                    ids.add(pid)
            except json.JSONDecodeError:
                continue  # skip corrupted lines
    return ids


def iter_user_prompts(parquet_path: Path, limit: int | None = None, batch_size: int = 500):
    """Yield (conversation_hash, turn_index, user_text) from local parquet."""
    pf = pq.ParquetFile(str(parquet_path))
    prompt_count = 0

    for batch in pf.iter_batches(batch_size=batch_size, columns=["conversation_hash", "conversation"]):
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
    parser.add_argument("--timeout", type=int, default=PROMPT_TIMEOUT_SECONDS, help="Per-prompt timeout in seconds")
    args = parser.parse_args()

    # Load Rust unified detector
    from data_classifier_core import UnifiedDetector

    patterns_json = PATTERNS_PATH.read_text()
    detector = UnifiedDetector(patterns_json)
    detector_version = get_detector_version()
    log.info("Detector version: %s", detector_version)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates_path = OUT_DIR / "candidates.jsonl"
    index_path = OUT_DIR / "scan_index.jsonl"

    # Resume: load existing prompt_ids to skip (index is most complete set)
    existing_ids = load_existing_prompt_ids(candidates_path)
    index_ids = load_existing_prompt_ids(index_path)
    existing_ids = existing_ids.union(index_ids)
    if existing_ids:
        log.info("Resuming: %d prompts already processed, will skip them", len(existing_ids))

    # Stats counters
    total_prompts = 0
    skipped_existing = 0
    skipped_timeout = 0
    skipped_error = 0
    prompts_with_secrets = 0
    prompts_with_zones = 0
    prompts_with_any = 0
    entity_type_counts: Counter = Counter()
    zone_type_counts: Counter = Counter()
    engine_counts: Counter = Counter()
    confidence_buckets: Counter = Counter()
    dominant_zone_counts: Counter = Counter()  # per-prompt dominant zone type

    # TN reservoir sampling
    import random

    tn_reservoir: list[dict] = []
    tn_seen = 0

    t0 = time.time()
    last_report = t0
    slow_prompts: list[dict] = []  # prompts that took > 2s

    # Open in append mode for resume safety; flush after every write
    with open(candidates_path, "a") as f_out, open(index_path, "a") as f_index:
        for conv_hash, turn_idx, text in iter_user_prompts(PARQUET_PATH, limit=args.limit, batch_size=args.batch_size):
            total_prompts += 1
            prompt_id = make_prompt_id(conv_hash, turn_idx)

            # Skip already-processed prompts (resume)
            if prompt_id in existing_ids:
                skipped_existing += 1
                continue

            # Run unified detector with timeout
            prompt_t0 = time.monotonic()
            try:
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(args.timeout)
                result_json = detector.detect(text)
                signal.alarm(0)  # cancel alarm
            except PromptTimeoutError:
                signal.alarm(0)
                skipped_timeout += 1
                log.warning(
                    "TIMEOUT (%ds) on prompt %s (len=%d chars), skipping",
                    args.timeout,
                    prompt_id,
                    len(text),
                )
                continue
            except Exception as e:
                signal.alarm(0)
                skipped_error += 1
                log.warning("ERROR on prompt %s: %s", prompt_id, e)
                continue

            prompt_elapsed = time.monotonic() - prompt_t0

            # Track slow prompts for diagnostics
            if prompt_elapsed > 2.0:
                slow_prompts.append(
                    {
                        "prompt_id": prompt_id,
                        "length": len(text),
                        "elapsed_s": round(prompt_elapsed, 2),
                    }
                )
                if len(slow_prompts) <= 10:
                    log.warning(
                        "Slow prompt %s: %.2fs (len=%d)",
                        prompt_id,
                        prompt_elapsed,
                        len(text),
                    )

            result = json.loads(result_json)
            zones_data = result.get("zones", {})
            zones = zones_data.get("blocks", []) if isinstance(zones_data, dict) else []
            findings = result.get("findings", [])

            # Filter findings by min confidence
            findings = [f for f in findings if f.get("confidence", 0) >= args.min_confidence]

            # Build zone summary from blocks
            zone_summary: dict[str, dict] = {}
            for z in zones:
                zt = z.get("zone_type", "unknown")
                lines_in_zone = z.get("end_line", 0) - z.get("start_line", 0)
                conf = z.get("confidence", 0.0)
                if zt not in zone_summary:
                    zone_summary[zt] = {"lines": 0, "max_conf": 0.0}
                zone_summary[zt]["lines"] += lines_in_zone
                zone_summary[zt]["max_conf"] = max(zone_summary[zt]["max_conf"], conf)

            # Track dominant zone type (zone with most lines) for aggregate stats
            if zone_summary:
                dominant_zt = max(zone_summary, key=lambda k: zone_summary[k]["lines"])
                dominant_zone_counts[dominant_zt] += 1

            has_secrets = len(findings) > 0
            has_zones = len(zones) > 0

            if has_secrets:
                prompts_with_secrets += 1
            if has_zones:
                prompts_with_zones += 1

            if has_secrets or has_zones:
                prompts_with_any += 1

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
                    safe_findings.append(
                        {
                            "entity_type": f.get("entity_type"),
                            "confidence": f.get("confidence"),
                            "engine": f.get("engine"),
                            "evidence": f.get("evidence", ""),
                            "detection_type": f.get("detection_type"),
                            "display_name": f.get("display_name"),
                            "value_masked": match_data.get("value_masked", ""),
                            "start": match_data.get("start", 0),
                            "end": match_data.get("end", 0),
                        }
                    )

                record = {
                    "prompt_id": prompt_id,
                    "conv_hash": conv_hash,
                    "turn_idx": turn_idx,
                    "prompt_xor": xor_encode(text),
                    "prompt_length": len(text),
                    "total_lines": text.count("\n") + 1,
                    "detector_version": detector_version,
                    "zones": zones,
                    "zone_summary": zone_summary,
                    "secrets": safe_findings,
                    "num_zones": len(zones),
                    "num_secrets": len(safe_findings),
                    "max_secret_confidence": max((f["confidence"] for f in safe_findings), default=0.0),
                    "review": None,
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                f_out.flush()  # crash-safe: every candidate is durable

            else:
                # TN — reservoir sample
                tn_seen += 1
                if len(tn_reservoir) < args.tn_sample:
                    tn_reservoir.append(
                        {
                            "prompt_id": prompt_id,
                            "conv_hash": conv_hash,
                            "turn_idx": turn_idx,
                            "prompt_xor": xor_encode(text),
                            "prompt_length": len(text),
                            "total_lines": text.count("\n") + 1,
                            "detector_version": detector_version,
                            "zones": [],
                            "zone_summary": {},
                            "secrets": [],
                            "num_zones": 0,
                            "num_secrets": 0,
                            "max_secret_confidence": 0.0,
                            "review": None,
                        }
                    )
                else:
                    j = random.randint(0, tn_seen - 1)
                    if j < args.tn_sample:
                        tn_reservoir[j] = {
                            "prompt_id": prompt_id,
                            "conv_hash": conv_hash,
                            "turn_idx": turn_idx,
                            "prompt_xor": xor_encode(text),
                            "prompt_length": len(text),
                            "total_lines": text.count("\n") + 1,
                            "detector_version": detector_version,
                            "zones": [],
                            "zone_summary": {},
                            "secrets": [],
                            "num_zones": 0,
                            "num_secrets": 0,
                            "max_secret_confidence": 0.0,
                            "review": None,
                        }

            # Write lightweight index record for EVERY prompt
            index_record = {
                "prompt_id": prompt_id,
                "prompt_length": len(text),
                "zone_summary": zone_summary,
                "num_secrets": len(findings),
                "max_secret_confidence": max((f.get("confidence", 0) for f in findings), default=0.0),
            }
            f_index.write(json.dumps(index_record, ensure_ascii=False) + "\n")
            f_index.flush()

            # Progress reporting
            now = time.time()
            if now - last_report >= 10:
                elapsed = now - t0
                scanned = total_prompts - skipped_existing
                rate = scanned / elapsed if elapsed > 0 else 0
                log.info(
                    "Progress: %d/%d scanned (skipped %d existing, %d timeout, %d error) | "
                    "%d candidates (%d secrets, %d zones) | %.0f/s | %.0fs elapsed",
                    scanned,
                    total_prompts,
                    skipped_existing,
                    skipped_timeout,
                    skipped_error,
                    prompts_with_any,
                    prompts_with_secrets,
                    prompts_with_zones,
                    rate,
                    elapsed,
                )
                last_report = now

    elapsed = time.time() - t0
    scanned = total_prompts - skipped_existing

    # Write TN sample
    tn_path = OUT_DIR / "tn_sample.jsonl"
    with open(tn_path, "w") as f:
        for rec in tn_reservoir:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Write slow prompt diagnostics
    if slow_prompts:
        slow_path = OUT_DIR / "slow_prompts.json"
        slow_path.write_text(json.dumps(slow_prompts, indent=2))
        log.info("Wrote %d slow prompt records to %s", len(slow_prompts), slow_path)

    # Write stats
    stats = {
        "detector_version": detector_version,
        "scan_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "parquet_path": str(PARQUET_PATH),
        "limit": args.limit,
        "min_confidence": args.min_confidence,
        "total_prompts": total_prompts,
        "scanned": scanned,
        "skipped_existing": skipped_existing,
        "skipped_timeout": skipped_timeout,
        "skipped_error": skipped_error,
        "prompts_with_secrets": prompts_with_secrets,
        "prompts_with_zones": prompts_with_zones,
        "prompts_with_any": prompts_with_any,
        "prompts_clean": scanned - prompts_with_any,
        "tn_sample_size": len(tn_reservoir),
        "elapsed_seconds": round(elapsed, 1),
        "prompts_per_second": round(scanned / elapsed, 1) if elapsed > 0 else 0,
        "slow_prompt_count": len(slow_prompts),
        "entity_type_counts": dict(entity_type_counts.most_common()),
        "zone_type_counts": dict(zone_type_counts.most_common()),
        "dominant_zone_counts": dict(dominant_zone_counts.most_common()),
        "engine_counts": dict(engine_counts.most_common()),
        "confidence_buckets": dict(confidence_buckets),
    }
    stats_path = OUT_DIR / "scan_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2))

    log.info("=" * 60)
    log.info("SCAN COMPLETE")
    log.info("  Total prompts seen: %d", total_prompts)
    log.info("  Scanned (new): %d", scanned)
    log.info("  Skipped (existing): %d", skipped_existing)
    log.info("  Skipped (timeout): %d", skipped_timeout)
    log.info("  Skipped (error): %d", skipped_error)
    log.info("  Candidates (any finding): %d (%.2f%%)", prompts_with_any, 100 * prompts_with_any / max(scanned, 1))
    log.info("    - with secrets: %d", prompts_with_secrets)
    log.info("    - with zones: %d", prompts_with_zones)
    log.info("  Slow prompts (>2s): %d", len(slow_prompts))
    log.info("  TN sample: %d", len(tn_reservoir))
    log.info("  Elapsed: %.1fs (%.0f prompts/s)", elapsed, scanned / max(elapsed, 1))
    log.info("  Output: %s", candidates_path)
    log.info("  Index: %s", index_path)
    log.info("  Stats: %s", stats_path)
    log.info("=" * 60)

    # Print top entity types
    if entity_type_counts:
        log.info("Top entity types:")
        for et, count in entity_type_counts.most_common(15):
            log.info("  %s: %d", et, count)

    if zone_type_counts:
        log.info("Zone types:")
        for zt, count in zone_type_counts.most_common():
            log.info("  %s: %d", zt, count)


if __name__ == "__main__":
    main()
