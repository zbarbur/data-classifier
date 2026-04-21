"""Generate test fixtures from S2 corpus for the browser PoC execution track.

Runs regex_engine + secret_scanner against the 11K S2 corpus and exports
findings as a JSONL fixture. The execution track (sprint14/browser-poc-secret)
loads this fixture to verify JS port produces matching results.

Output: s2_spike/report/s2_test_fixtures.jsonl

Run: .venv/bin/python docs/experiments/prompt_analysis/s2_spike/generate_test_fixtures.py
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path

os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")

from data_classifier import ColumnInput, load_profile  # noqa: E402
from data_classifier.core.taxonomy import ENTITY_TYPE_TO_FAMILY  # noqa: E402
from data_classifier.engines.regex_engine import RegexEngine  # noqa: E402
from data_classifier.engines.secret_scanner import SecretScannerEngine  # noqa: E402
from data_classifier.patterns._decoder import _XOR_KEY  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("s2_fixtures")

SPIKE_DIR = Path(__file__).parent
CORPUS = SPIKE_DIR / "corpus.jsonl"
REPORT_DIR = SPIKE_DIR / "report"


def xor_decode(s: str) -> str:
    b64 = s.removeprefix("xor:")
    raw = base64.b64decode(b64)
    return bytes(b ^ _XOR_KEY for b in raw).decode("utf-8")


def main() -> None:
    profile = load_profile("standard")
    regex_engine = RegexEngine()
    regex_engine.startup()
    secret_engine = SecretScannerEngine()
    secret_engine.startup()

    records = [json.loads(line) for line in CORPUS.read_text().splitlines()]
    log.info("loaded %d corpus records", len(records))

    fixtures: list[dict] = []
    finding_count = 0
    t0 = time.time()

    for i, rec in enumerate(records):
        if (i + 1) % 2000 == 0:
            elapsed = time.time() - t0
            log.info(
                "processed %d/%d (%.0f/sec) | fixtures=%d findings=%d",
                i + 1,
                len(records),
                (i + 1) / elapsed,
                len(fixtures),
                finding_count,
            )

        text = xor_decode(rec["text_xor"])
        col = ColumnInput(column_name="prompt", sample_values=[text])

        try:
            findings = regex_engine.classify_column(
                col, profile=profile, min_confidence=0.5, max_evidence_samples=10
            ) + secret_engine.classify_column(col, profile=profile, min_confidence=0.5, max_evidence_samples=10)
        except Exception as e:
            log.debug("engine error idx=%d: %s", i, e)
            continue

        if not findings:
            continue

        expected = []
        for f in findings:
            expected.append(
                {
                    "entity_type": f.entity_type,
                    "family": ENTITY_TYPE_TO_FAMILY.get(f.entity_type, "OTHER"),
                    "confidence": f.confidence,
                    "engine": f.engine,
                    "evidence": f.evidence,
                }
            )

        fixtures.append(
            {
                "prompt_fingerprint": rec["sha256"],
                "prompt_length": rec["length"],
                "bucket": rec["bucket"],
                "prompt_xor": rec["text_xor"],
                "expected_findings": expected,
            }
        )
        finding_count += len(expected)

    elapsed = time.time() - t0
    log.info(
        "done in %.1fs: %d prompts with findings, %d total findings (out of %d corpus)",
        elapsed,
        len(fixtures),
        finding_count,
        len(records),
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / "s2_test_fixtures.jsonl"
    with out_path.open("w") as f:
        for fix in fixtures:
            f.write(json.dumps(fix) + "\n")

    # Summary
    from collections import Counter

    by_engine = Counter(e["engine"] for fix in fixtures for e in fix["expected_findings"])
    by_family = Counter(e["family"] for fix in fixtures for e in fix["expected_findings"])
    summary = {
        "corpus_size": len(records),
        "prompts_with_findings": len(fixtures),
        "total_findings": finding_count,
        "by_engine": dict(by_engine.most_common()),
        "by_family": dict(by_family.most_common()),
        "elapsed_seconds": elapsed,
    }
    log.info("summary: %s", json.dumps(summary, indent=2))

    summary_path = REPORT_DIR / "s2_test_fixtures_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    log.info("wrote %s + %s", out_path, summary_path)


if __name__ == "__main__":
    main()
