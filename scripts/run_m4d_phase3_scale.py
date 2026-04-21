"""Driver for M4d Phase 3 — router-labeler over the unlabeled scale corpus.

Consumes ``data/m4d_phase3_corpus/unlabeled.jsonl`` (produced by
``scripts.m4d_phase3_build_scale_corpus``), routes each column to its
Phase 2 branch by ``true_shape``, calls the router-labeler, and emits:

  * ``labeled.jsonl`` — per-column predictions + prefill labels + full telemetry
  * ``summary.json``  — aggregate stats (per-shape counts, label distribution,
                        token usage, cost estimate, error / unknown-label counts)

Unlike Phase 2's driver, Phase 3 has NO human ground truth at run time —
the labeler output IS the candidate ground truth for Phase 3b. Quality
assurance happens out-of-band via the spot-check worksheet
(``scripts.m4d_phase3_build_worksheet``).

Usage::

    export ANTHROPIC_API_KEY=...
    .venv/bin/python -m scripts.run_m4d_phase3_scale

    # Smoke-test on 3 rows first:
    .venv/bin/python -m scripts.run_m4d_phase3_scale --limit 3

    # Custom input / output paths:
    .venv/bin/python -m scripts.run_m4d_phase3_scale \\
        --input-path data/m4d_phase3_corpus/unlabeled.jsonl \\
        --output-dir  data/m4d_phase3_corpus

Partial-progress safety: each row is flushed to ``labeled.jsonl`` as soon
as the API call returns, so a mid-run crash preserves every successful
call. Re-run with ``--skip-existing`` to resume.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

from tests.benchmarks.meta_classifier.llm_labeler import MODEL, LabelerCall, label_column
from tests.benchmarks.meta_classifier.llm_labeler_router import (
    VALID_SHAPES,
    build_system_prompt_for_shape,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "data/m4d_phase3_corpus/unlabeled.jsonl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/m4d_phase3_corpus"

# Claude Opus 4.7 pricing ($/MTok); keep in sync with llm_labeler_router cost telemetry.
COST_IN = 5.0e-6
COST_OUT = 25.0e-6
COST_CACHE_READ = COST_IN * 0.1
COST_CACHE_CREATE = COST_IN * 1.25


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _call_to_output_row(call: LabelerCall, source_row: dict[str, Any]) -> dict[str, Any]:
    """Merge labeler output with source metadata into one labeled.jsonl row."""
    return {
        "column_id": call.column_id,
        "source": source_row.get("source"),
        "source_reference": source_row.get("source_reference"),
        "encoding": source_row.get("encoding"),
        "values": source_row.get("values"),
        "true_shape": source_row.get("true_shape"),
        # Prefill labels: what the fetcher guessed (unverified). Keep
        # under this name to avoid confusion with real gold-set true_labels.
        "prefill_labels": source_row.get("true_labels", []),
        "prefill_prevalence": source_row.get("true_labels_prevalence", {}),
        "pred_labels": sorted(call.pred),
        "unknown_labels": sorted(call.unknown_labels),
        "review_status": "llm_labeled",
        "annotator": "phase3-router-labeler",
        "annotated_on": _now_iso(),
        "error": call.error,
        "usage": {
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
            "cache_read_input_tokens": call.cache_read_input_tokens,
            "cache_creation_input_tokens": call.cache_creation_input_tokens,
        },
        "raw_response": call.raw_response,
    }


def _load_existing_column_ids(output_path: Path) -> set[str]:
    if not output_path.exists():
        return set()
    seen: set[str] = set()
    with output_path.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = obj.get("column_id")
            if cid and not obj.get("error"):
                seen.add(cid)
    return seen


def _compute_summary(output_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_shape_count: dict[str, int] = Counter(r["true_shape"] for r in output_rows)
    pred_label_dist: dict[str, int] = Counter()
    pred_label_by_shape: dict[str, dict[str, int]] = defaultdict(Counter)
    for r in output_rows:
        for label in r["pred_labels"]:
            pred_label_dist[label] += 1
            pred_label_by_shape[r["true_shape"]][label] += 1

    total_in = sum(r["usage"]["input_tokens"] for r in output_rows)
    total_out = sum(r["usage"]["output_tokens"] for r in output_rows)
    total_cache_read = sum(r["usage"]["cache_read_input_tokens"] for r in output_rows)
    total_cache_create = sum(r["usage"]["cache_creation_input_tokens"] for r in output_rows)
    cost = (
        total_in * COST_IN
        + total_out * COST_OUT
        + total_cache_read * COST_CACHE_READ
        + total_cache_create * COST_CACHE_CREATE
    )
    cache_hit_pct = (total_cache_read / max(total_cache_read + total_in, 1)) * 100

    errors = [r["column_id"] for r in output_rows if r["error"]]
    unknowns = [
        {"column_id": r["column_id"], "unknown_labels": r["unknown_labels"]} for r in output_rows if r["unknown_labels"]
    ]
    empty_preds = sum(1 for r in output_rows if not r["pred_labels"] and not r["error"])

    return {
        "n_columns": len(output_rows),
        "n_errors": len(errors),
        "n_unknown_label_emissions": len(unknowns),
        "n_empty_predictions": empty_preds,
        "by_shape_count": dict(by_shape_count),
        "pred_label_distribution": dict(sorted(pred_label_dist.items(), key=lambda kv: -kv[1])),
        "pred_label_by_shape": {
            s: dict(sorted(d.items(), key=lambda kv: -kv[1])) for s, d in pred_label_by_shape.items()
        },
        "usage": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cache_read_input_tokens": total_cache_read,
            "cache_creation_input_tokens": total_cache_create,
            "cache_hit_rate_pct": round(cache_hit_pct, 2),
        },
        "estimated_cost_usd": round(cost, 4),
        "errors": errors,
        "unknown_label_rows": unknowns,
        "model": MODEL,
        "run_timestamp": _now_iso(),
    }


def run(
    input_path: Path,
    output_dir: Path,
    limit: int | None = None,
    sleep_between_calls: float = 0.0,
    skip_existing: bool = False,
) -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY not set. Export it before running the labeler.")
        return 1
    if not input_path.exists():
        log.error("input not found: %s", input_path)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    labeled_path = output_dir / "labeled.jsonl"
    summary_path = output_dir / "summary.json"

    with input_path.open() as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if limit is not None:
        rows = rows[:limit]
    log.info("loaded %d rows from %s", len(rows), input_path)

    skip_ids = _load_existing_column_ids(labeled_path) if skip_existing else set()
    if skip_ids:
        log.info("skip_existing: %d rows already labeled, resuming", len(skip_ids))

    # Build all 3 cacheable system prompts once. First call per shape pays
    # cache-creation; subsequent calls are cache-reads.
    systems_by_shape = {shape: build_system_prompt_for_shape(shape) for shape in VALID_SHAPES}
    client = anthropic.Anthropic()

    # Append mode so partial progress survives mid-run crashes. If not resuming,
    # truncate first so a prior-run's stale rows don't mix with this run's.
    file_mode = "a" if skip_existing else "w"
    output_rows: list[dict[str, Any]] = []

    # If resuming, re-load existing rows into our in-memory summary.
    if skip_existing and labeled_path.exists():
        with labeled_path.open() as f:
            for line in f:
                if line.strip():
                    output_rows.append(json.loads(line))

    with labeled_path.open(file_mode) as f_out:
        for i, row in enumerate(rows, start=1):
            cid = row["column_id"]
            if cid in skip_ids:
                log.info("[%d/%d] skip (already labeled): %s", i, len(rows), cid)
                continue
            shape = row.get("true_shape")
            if shape not in VALID_SHAPES:
                call = LabelerCall(
                    column_id=cid,
                    pred=[],
                    true=list(row.get("true_labels", [])),
                    error=f"unrouted_shape: {shape!r}",
                )
            else:
                try:
                    call = label_column(client, row, systems_by_shape[shape])
                except Exception as exc:  # noqa: BLE001 — broad catch intentional
                    call = LabelerCall(
                        column_id=cid,
                        pred=[],
                        true=list(row.get("true_labels", [])),
                        error=f"{type(exc).__name__}: {exc}",
                    )
            out_row = _call_to_output_row(call, row)
            output_rows.append(out_row)
            f_out.write(json.dumps(out_row, ensure_ascii=False) + "\n")
            f_out.flush()
            log.info(
                "[%d/%d] %s shape=%s pred=%s%s",
                i,
                len(rows),
                cid,
                shape,
                out_row["pred_labels"],
                f" ERROR={call.error}" if call.error else "",
            )
            if sleep_between_calls > 0:
                time.sleep(sleep_between_calls)

    summary = _compute_summary(output_rows)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    print()  # noqa: T201
    print("─" * 72)  # noqa: T201
    print(f"M4d Phase 3 scale-labeler run — {summary['n_columns']} columns")  # noqa: T201
    print("─" * 72)  # noqa: T201
    print(f"Errors:            {summary['n_errors']}")  # noqa: T201
    print(f"Unknown labels:    {summary['n_unknown_label_emissions']}")  # noqa: T201
    print(f"Empty predictions: {summary['n_empty_predictions']}")  # noqa: T201
    print(f"By shape:          {summary['by_shape_count']}")  # noqa: T201
    print(f"Top 10 labels:     {dict(list(summary['pred_label_distribution'].items())[:10])}")  # noqa: T201
    print(
        f"Usage:             in={summary['usage']['input_tokens']:,}  "  # noqa: T201
        f"out={summary['usage']['output_tokens']:,}  "
        f"cache_read={summary['usage']['cache_read_input_tokens']:,}  "
        f"cache_create={summary['usage']['cache_creation_input_tokens']:,}  "
        f"cache_hit={summary['usage']['cache_hit_rate_pct']}%"
    )
    print(f"Est. cost:         ${summary['estimated_cost_usd']:.4f}")  # noqa: T201
    print(f"Wrote:             {labeled_path}")  # noqa: T201
    print(f"Wrote:             {summary_path}")  # noqa: T201
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=None, help="Cap rows for smoke tests.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between API calls.")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Resume a prior run by skipping columns already present in labeled.jsonl.",
    )
    args = parser.parse_args()
    return run(
        input_path=args.input_path,
        output_dir=args.output_dir,
        limit=args.limit,
        sleep_between_calls=args.sleep,
        skip_existing=args.skip_existing,
    )


if __name__ == "__main__":
    sys.exit(main())
