"""S0 — WildChat-1M secret-prevalence scan.

Streams WildChat-1M from HuggingFace, runs the orchestrator-level
scanner (regex + secret_scanner) AND pattern-level finditer over each
user-turn text, aggregates prevalence statistics, and writes:

  - s0_stats.json        — aggregate counts and distributions
  - s0_pattern_hits.json — per-pattern hit count + xor-encoded examples
  - s0_audit_sample.json — random N hits with xor-encoded ±100 char context
  - s0_corpus_extract.jsonl — random K positive prompts (xor-encoded full text)
                              for differential-test seed

ML is force-disabled (DATA_CLASSIFIER_DISABLE_ML=1). Engines used:
regex_engine + secret_scanner only — see prompt-analysis queue.md
S0 stage definition.

All raw secret strings are XOR-encoded (key=90) per the
feedback_xor_fixture_pattern.md memory rule before being written
to disk. They can be decoded via
data_classifier.patterns._decoder.decode_encoded_strings.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier import ColumnInput, load_profile  # noqa: E402
from data_classifier.engines.regex_engine import RegexEngine  # noqa: E402
from data_classifier.engines.secret_scanner import SecretScannerEngine  # noqa: E402
from data_classifier.patterns import load_default_patterns  # noqa: E402
from data_classifier.patterns._decoder import _XOR_KEY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("s0")


def xor_encode(s: str) -> str:
    """Mirror of decode_encoded_strings — returns 'xor:<b64>' encoded string."""
    raw = bytes(b ^ _XOR_KEY for b in s.encode("utf-8"))
    return "xor:" + base64.b64encode(raw).decode("ascii")


def iter_user_turns(limit: int | None) -> Iterator[tuple[int, str]]:
    """Stream WildChat-1M and yield (turn_index, user_text) tuples."""
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


def build_finditer_patterns() -> list[tuple[str, str, re.Pattern]]:
    """Compile loaded patterns for span-level scanning. Returns [(name, entity_type, regex)].

    Skips patterns with ``requires_column_hint=True`` because they rely on a column-name
    gate that engine-level scans apply but a raw `re.finditer` does not. Without the
    gate, low-precision regexes like ``random_password`` (``\\S{4,64}``) match every
    word in every prompt.
    """
    patterns = load_default_patterns()
    compiled: list[tuple[str, str, re.Pattern]] = []
    skipped: list[str] = []
    for p in patterns:
        if not p.regex:
            continue
        if p.requires_column_hint:
            skipped.append(p.name)
            continue
        try:
            compiled.append((p.name, p.entity_type, re.compile(p.regex)))
        except re.error as e:
            log.warning("skipping uncompilable pattern %s: %s", p.name, e)
    log.info("compiled %d patterns for finditer (skipped %d column-hint-guarded: %s)",
             len(compiled), len(skipped), skipped)
    return compiled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50_000, help="Max user-turn texts to scan (None for full WildChat)")
    parser.add_argument("--out-dir", default="docs/experiments/prompt_analysis/s0_artifacts")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--audit-sample", type=int, default=50, help="Random N hits to capture for hand-audit"
    )
    parser.add_argument(
        "--corpus-extract", type=int, default=1000, help="K positive prompts to freeze for differential-test seed"
    )
    args = parser.parse_args()

    random.seed(args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    profile = load_profile("standard")
    regex_engine = RegexEngine()
    regex_engine.startup()
    secret_engine = SecretScannerEngine()
    secret_engine.startup()
    finditer_patterns = build_finditer_patterns()

    # Aggregates
    total_prompts = 0
    prompts_with_findings = 0
    findings_by_entity_type: Counter[str] = Counter()
    findings_by_pattern: Counter[str] = Counter()
    secrets_per_prompt_dist: Counter[int] = Counter()
    pattern_hit_examples: dict[str, list[str]] = defaultdict(list)
    pattern_hit_total: Counter[str] = Counter()  # span-level total per pattern
    audit_candidates: list[dict] = []
    positive_corpus: list[dict] = []

    t0 = time.time()
    log.info("starting scan limit=%s", args.limit)

    for idx, text in iter_user_turns(args.limit):
        total_prompts += 1
        if total_prompts % 5000 == 0:
            elapsed = time.time() - t0
            rate = total_prompts / elapsed if elapsed > 0 else 0
            log.info(
                "processed %d prompts | %.1f prompts/sec | with_findings=%d (%.2f%%)",
                total_prompts,
                rate,
                prompts_with_findings,
                100 * prompts_with_findings / total_prompts,
            )

        # Engine-level scan (column-level findings)
        col = ColumnInput(column_name="prompt", sample_values=[text])
        try:
            engine_findings = regex_engine.classify_column(
                col, profile=profile, min_confidence=0.5
            ) + secret_engine.classify_column(col, profile=profile, min_confidence=0.5)
        except Exception as e:
            log.debug("engine error on idx=%d: %s", idx, e)
            engine_findings = []

        # Pattern-level finditer (span-level)
        span_hits: list[tuple[str, str, int, int, str]] = []  # (name, entity_type, start, end, span_text)
        for name, entity_type, pat in finditer_patterns:
            for m in pat.finditer(text):
                span_hits.append((name, entity_type, m.start(), m.end(), m.group()))

        n_distinct_secrets = len(span_hits)
        secrets_per_prompt_dist[n_distinct_secrets] += 1

        if engine_findings or span_hits:
            prompts_with_findings += 1
            for f in engine_findings:
                findings_by_entity_type[f.entity_type] += 1
            for name, entity_type, _s, _e, span_text in span_hits:
                findings_by_pattern[name] += 1
                pattern_hit_total[name] += 1
                # Keep up to 5 example raw values per pattern (xor-encoded)
                if len(pattern_hit_examples[name]) < 5:
                    pattern_hit_examples[name].append(xor_encode(span_text))

            # Reservoir sample for hand-audit (xor-encoded context window)
            if len(audit_candidates) < args.audit_sample or random.random() < 0.01:
                if span_hits:
                    name, entity_type, s, e, span_text = span_hits[0]
                    ctx_start = max(0, s - 100)
                    ctx_end = min(len(text), e + 100)
                    context = text[ctx_start:ctx_end]
                    sample = {
                        "turn_index": idx,
                        "n_secrets": n_distinct_secrets,
                        "entity_types": sorted({et for _, et, _, _, _ in span_hits}),
                        "first_pattern": name,
                        "first_entity_type": entity_type,
                        "first_span_xor": xor_encode(span_text),
                        "context_window_xor": xor_encode(context),
                    }
                    if len(audit_candidates) < args.audit_sample:
                        audit_candidates.append(sample)
                    else:
                        audit_candidates[random.randrange(args.audit_sample)] = sample

            # Reservoir sample for differential-test corpus seed (xor-encoded full prompt)
            if len(positive_corpus) < args.corpus_extract or random.random() < 0.01:
                entry = {
                    "turn_index": idx,
                    "prompt_xor": xor_encode(text),
                    "expected_pattern_hits": [
                        {"name": n, "entity_type": et, "start": s, "end": e}
                        for n, et, s, e, _ in span_hits
                    ],
                }
                if len(positive_corpus) < args.corpus_extract:
                    positive_corpus.append(entry)
                else:
                    positive_corpus[random.randrange(args.corpus_extract)] = entry

    elapsed = time.time() - t0
    log.info("scan complete in %.1fs (%.1f prompts/sec)", elapsed, total_prompts / elapsed)
    log.info("prompts with findings: %d / %d (%.2f%%)", prompts_with_findings, total_prompts, 100 * prompts_with_findings / total_prompts)

    # Write outputs
    stats = {
        "total_prompts": total_prompts,
        "prompts_with_findings": prompts_with_findings,
        "prevalence_rate": prompts_with_findings / total_prompts if total_prompts else 0,
        "elapsed_seconds": elapsed,
        "throughput_prompts_per_sec": total_prompts / elapsed if elapsed else 0,
        "findings_by_entity_type": dict(findings_by_entity_type.most_common()),
        "secrets_per_prompt_distribution": {str(k): v for k, v in sorted(secrets_per_prompt_dist.items())},
        "scan_settings": {
            "limit": args.limit,
            "ml_disabled": True,
            "engines": ["regex_engine", "secret_scanner"],
            "min_confidence": 0.5,
            "patterns_compiled": len(finditer_patterns),
        },
    }
    (out_dir / "s0_stats.json").write_text(json.dumps(stats, indent=2))

    pattern_hits = {
        "patterns_with_hits": len(pattern_hit_total),
        "total_span_hits": sum(pattern_hit_total.values()),
        "by_pattern": [
            {
                "pattern_name": name,
                "hit_count": count,
                "examples_xor": pattern_hit_examples[name],
            }
            for name, count in pattern_hit_total.most_common()
        ],
    }
    (out_dir / "s0_pattern_hits.json").write_text(json.dumps(pattern_hits, indent=2))

    (out_dir / "s0_audit_sample.json").write_text(json.dumps(audit_candidates, indent=2))

    with (out_dir / "s0_corpus_extract.jsonl").open("w") as f:
        for entry in positive_corpus:
            f.write(json.dumps(entry) + "\n")

    log.info("wrote artifacts to %s", out_dir)
    log.info("  s0_stats.json — aggregate stats")
    log.info("  s0_pattern_hits.json — %d patterns with hits", pattern_hits["patterns_with_hits"])
    log.info("  s0_audit_sample.json — %d hand-audit candidates", len(audit_candidates))
    log.info("  s0_corpus_extract.jsonl — %d positive prompts for differential-test seed", len(positive_corpus))


if __name__ == "__main__":
    main()
