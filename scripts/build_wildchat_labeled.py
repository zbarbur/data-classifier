"""Build the WildChat labeled evaluation dataset (Sprint 18 item).

Joins three sources:

* ``data/wildchat_eval/wildchat_eval_v2.jsonl`` — the 3,515 WildChat
  credential-prompt corpus, XOR-encoded per repo policy
  (see memory ``feedback_xor_fixture_pattern``).
* ``data/wildchat_eval/review_corpus.jsonl`` — 421 prompts surfaced for
  human review during the Sprint 14/15 secret-scanner review.  334 of
  these have human verdicts attached (``review.secret_reviews``).
* Current ``scan_text`` output — re-scanned at build time so the
  labeled set reflects the scanner that ships in this commit.

Each output row carries:

* ``prompt_id``
* ``prompt_xor`` (XOR-encoded)
* ``scanner_findings`` — current ``scan_text`` output
* ``old_findings`` — the v2 GT findings from the historical run
* ``human_verdicts`` — per-index TP/FP labels from the human review
  (only set on the 334 reviewed rows)
* ``label`` — row-level summary: ``TP_REVIEWED``, ``FP_REVIEWED``,
  ``MIXED_REVIEWED``, ``UNREVIEWED_POSITIVE``, ``UNREVIEWED_NEGATIVE``
* ``reviewed`` — bool

The "row-level label" is a coarse aggregation kept for convenience;
the regression test reads ``human_verdicts`` directly so per-finding
verdicts are not collapsed.

Usage::

    .venv/bin/python scripts/build_wildchat_labeled.py
        # writes data/wildchat_labeled_eval/labeled_set.jsonl

Re-runnable from a clean checkout: requires
``data/wildchat_eval/{wildchat_eval_v2.jsonl, review_corpus.jsonl}``
to be present (DVC-pulled) and a working ``data_classifier`` install.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

EVAL_PATH = Path("data/wildchat_eval/wildchat_eval_v2.jsonl")
REVIEW_PATH = Path("data/wildchat_eval/review_corpus.jsonl")
OUT_PATH = Path("data/wildchat_labeled_eval/labeled_set.jsonl")


def _load_review_verdicts(path: Path) -> dict[int, dict]:
    """Return ``{prompt_id: review_dict}`` for every reviewed prompt.

    The reviewer UI stores the verdict on the row's ``review`` field;
    we keep only rows that have it set.
    """
    verdicts: dict[int, dict] = {}
    with path.open() as f:
        for line in f:
            row = json.loads(line)
            review = row.get("review")
            if not review:
                continue
            try:
                pid = int(row["prompt_id"])
            except (KeyError, ValueError, TypeError):
                continue
            verdicts[pid] = review
    return verdicts


def _row_label(human_verdicts: dict[str, str] | None, scanner_findings: list) -> str:
    """Aggregate per-finding verdicts and current scanner output to a
    coarse row-level label so consumers without finding-level needs
    can filter quickly.
    """
    if human_verdicts is None:
        return "UNREVIEWED_POSITIVE" if scanner_findings else "UNREVIEWED_NEGATIVE"
    values = list(human_verdicts.values())
    if not values:
        return "UNREVIEWED_POSITIVE" if scanner_findings else "UNREVIEWED_NEGATIVE"
    tp_count = sum(1 for v in values if v == "tp")
    fp_count = sum(1 for v in values if v == "fp")
    if tp_count and not fp_count:
        return "TP_REVIEWED"
    if fp_count and not tp_count:
        return "FP_REVIEWED"
    return "MIXED_REVIEWED"


def _findings_to_jsonable(findings) -> list[dict]:
    """Strip ``scan_text`` Finding dataclass into a JSON-safe shape.

    Keeps fields the regression test compares against (entity_type,
    confidence, detection_type, engine).  Span offsets are kept too
    so the test can detect drift in *where* a match lands.
    """
    out = []
    for f in findings:
        out.append(
            {
                "entity_type": f.entity_type,
                "detection_type": getattr(f, "detection_type", None),
                "engine": f.engine,
                "confidence": f.confidence,
                "start": getattr(f, "start", None),
                "end": getattr(f, "end", None),
            }
        )
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not EVAL_PATH.exists():
        raise FileNotFoundError(
            f"Source corpus missing: {EVAL_PATH}\n"
            "Pull via: dvc pull data/wildchat_eval/\n"
            "See docs/process/dataset_management.md."
        )
    if not REVIEW_PATH.exists():
        raise FileNotFoundError(
            f"Review corpus missing: {REVIEW_PATH}\n"
            "Pull via: dvc pull data/wildchat_eval/\n"
            "See docs/process/dataset_management.md."
        )

    from data_classifier.patterns._decoder import decode_encoded_strings
    from data_classifier.scan_text import TextScanner

    verdicts = _load_review_verdicts(REVIEW_PATH)
    logger.info("Loaded %d reviewed prompt verdicts", len(verdicts))

    scanner = TextScanner()
    scanner.startup()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    n_rows = 0
    n_reviewed = 0
    n_label_counts: dict[str, int] = {}
    with EVAL_PATH.open() as fin, OUT_PATH.open("w") as fout:
        for line in fin:
            row = json.loads(line)
            prompt_id = row["prompt_id"]
            prompt_xor = row["prompt_xor"]

            [text] = decode_encoded_strings(["xor:" + prompt_xor])
            result = scanner.scan(text, min_confidence=0.3)
            scanner_findings = _findings_to_jsonable(result.findings)

            human_verdicts: dict[str, str] | None = None
            if prompt_id in verdicts:
                review = verdicts[prompt_id]
                sr = review.get("secret_reviews") or {}
                # Keep only tp/fp leaves; drop anything else (the UI
                # also writes 'review'/'unsure' which we treat as no
                # judgement).
                human_verdicts = {k: v for k, v in sr.items() if v in ("tp", "fp")}
                n_reviewed += 1

            label = _row_label(human_verdicts, scanner_findings)
            n_label_counts[label] = n_label_counts.get(label, 0) + 1

            out_row = {
                "prompt_id": prompt_id,
                "prompt_xor": prompt_xor,
                "scanner_findings": scanner_findings,
                "old_findings": row.get("findings", []),
                "human_verdicts": human_verdicts,
                "label": label,
                "reviewed": human_verdicts is not None,
            }
            fout.write(json.dumps(out_row) + "\n")
            n_rows += 1

            if n_rows % 500 == 0:
                logger.info("Processed %d/%d", n_rows, n_rows)

    logger.info("Wrote %d rows (%d reviewed) to %s", n_rows, n_reviewed, OUT_PATH)
    for label, count in sorted(n_label_counts.items()):
        logger.info("  %s: %d", label, count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
