"""Stratified spot-check of auto-approved rows in the M4d Phase 3 worksheet.

Picks N rows where ``agreement == "agree"`` and ``reviewer_status ==
"pending"`` (i.e. the labeler matched prefill exactly so the row was
auto-approved at worksheet build time). Allocation is proportional
across ``source × true_shape`` strata, with a floor of 1 row per stratum
that has any auto-approved rows.

The output is a separate JSONL file so the reviewer can mark
confirm / correct without disturbing the main worksheet. Once review is
complete, ``apply_spot_check_results`` (small inline helper here) merges
the corrections back into ``review_worksheet.jsonl``.

Co-agreement errors — where the labeler and the prefill annotator
*both* picked the same wrong label — slip past the disagreement-only
review path. This script is the safety net.

Usage::

    .venv/bin/python -m scripts.m4d_phase3_spot_check_agreed --sample-size 20
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "data/m4d_phase3b_corpus/review_worksheet.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "data/m4d_phase3b_corpus/spot_check.jsonl"


def _stratified_sample(rows: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r.get("source") or "unknown", r.get("true_shape") or "unknown")].append(r)
    if not groups:
        return []

    # Floor of 1 per stratum, then proportional top-up.
    out: list[dict[str, Any]] = []
    floor_used = 0
    for grp in groups.values():
        out.append(rng.choice(grp))
        floor_used += 1

    remaining = n - floor_used
    if remaining > 0:
        # Proportional share of the leftover budget, weighted by stratum size.
        total_pool = sum(len(g) - 1 for g in groups.values())
        if total_pool > 0:
            for grp in groups.values():
                already = next(r for r in out if r["column_id"] in {x["column_id"] for x in grp})
                pool = [r for r in grp if r["column_id"] != already["column_id"]]
                if not pool:
                    continue
                share = round(remaining * len(pool) / total_pool)
                share = min(share, len(pool))
                out.extend(rng.sample(pool, share))

    # Trim or top up to hit n exactly.
    if len(out) > n:
        out = rng.sample(out, n)
    elif len(out) < n:
        seen_ids = {r["column_id"] for r in out}
        leftover = [r for r in rows if r["column_id"] not in seen_ids]
        out.extend(rng.sample(leftover, min(n - len(out), len(leftover))))

    out.sort(key=lambda r: (r.get("source") or "", r.get("true_shape") or "", r["column_id"]))
    return out


def _to_spot_check_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "column_id": row["column_id"],
        "source": row.get("source"),
        "true_shape": row.get("true_shape"),
        "pred_labels": sorted(row["pred_labels"]),
        "sample_values_decoded": row["sample_values_decoded"],
        # Reviewer fields — fill these in:
        "spot_check_status": "pending",  # confirm | correct
        "spot_check_corrected_labels": [],  # only used if status=correct
        "spot_check_notes": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.input_path.exists():
        log.error("input not found: %s", args.input_path)
        return 1

    rows = [json.loads(line) for line in args.input_path.open() if line.strip()]
    auto_approved = [r for r in rows if r["agreement"] == "agree" and r["reviewer_status"] == "pending"]
    if not auto_approved:
        log.error("no auto-approved rows found (agreement=agree && reviewer_status=pending)")
        return 1

    sample = _stratified_sample(auto_approved, args.sample_size, args.seed)
    sample_rows = [_to_spot_check_row(r) for r in sample]

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    with args.output_path.open("w") as f:
        for r in sample_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Console summary.
    print()  # noqa: T201
    print("─" * 72)  # noqa: T201
    print(f"M4d Phase 3 — spot-check sample ({len(sample_rows)} of {len(auto_approved)} auto-approved)")  # noqa: T201
    print("─" * 72)  # noqa: T201
    by_strata: dict[tuple[str, str], int] = defaultdict(int)
    for r in sample:
        by_strata[(r.get("source") or "?", r.get("true_shape") or "?")] += 1
    for (src, shape), n in sorted(by_strata.items()):
        short = src.split(".")[-1]
        print(f"  {short:35s} {shape:28s} n={n}")  # noqa: T201
    print()  # noqa: T201
    print(f"Wrote: {args.output_path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
