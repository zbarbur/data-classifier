"""Score the M4d Phase 3 review worksheet.

Reads ``data/m4d_phase3b_corpus/review_worksheet.jsonl`` (filled by the
human reviewer) and computes Jaccard / exact-match metrics by shape and
source, plus a gate verdict against M4d Phase 3 thresholds.

Convention for combining agreed and reviewed rows into "effective gold":

- ``agreement == "agree"`` and ``reviewer_status == "pending"``: row was
  auto-approved at worksheet build time (prefill matched pred). Treat
  the reviewer's gold as ``pred_labels`` — the reviewer accepted by not
  touching the row.
- otherwise: use ``reviewer_labels`` as gold.

A row is ``skipped`` only if it sits in disagreement *and* the reviewer
hasn't set ``reviewer_status`` away from ``pending``. After full review
this should be zero.

Usage::

    .venv/bin/python -m scripts.m4d_phase3_score_worksheet
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "data/m4d_phase3b_corpus/review_worksheet.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "data/m4d_phase3b_corpus/score_summary.json"

# M4d Phase 3 gate thresholds (macro Jaccard).
# Floor of 0.80 overall is the published M4d target; per-shape floors mirror
# the canonical family-benchmark gates for similar shape mixes.
DEFAULT_GATES = {
    "overall": 0.80,
    "structured_single": 0.90,
    "opaque_tokens": 0.85,
    "free_text_heterogeneous": 0.75,
}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _effective_gold(row: dict[str, Any]) -> list[str]:
    if row["agreement"] == "agree" and row["reviewer_status"] == "pending":
        return list(row["pred_labels"])
    return list(row["reviewer_labels"])


def _is_reviewed(row: dict[str, Any]) -> bool:
    if row["agreement"] == "agree" and row["reviewer_status"] == "pending":
        return True  # auto-approved
    return row["reviewer_status"] != "pending"


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "macro_jaccard": None, "exact_match_rate": None, "exact_match": "0/0"}
    jaccards = []
    exact = 0
    for r in rows:
        gold = set(_effective_gold(r))
        pred = set(r["pred_labels"])
        j = _jaccard(gold, pred)
        jaccards.append(j)
        if gold == pred:
            exact += 1
    macro = sum(jaccards) / len(jaccards)
    return {
        "n": len(rows),
        "macro_jaccard": round(macro, 4),
        "exact_match_rate": round(exact / len(rows), 4),
        "exact_match": f"{exact}/{len(rows)}",
    }


def _per_label_prf(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Micro per-label precision/recall/F1 across all rows."""
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    for r in rows:
        gold = set(_effective_gold(r))
        pred = set(r["pred_labels"])
        for label in gold | pred:
            in_g, in_p = label in gold, label in pred
            if in_g and in_p:
                tp[label] += 1
            elif in_p:
                fp[label] += 1
            else:
                fn[label] += 1
    out = {}
    for label in sorted(set(tp) | set(fp) | set(fn)):
        p = tp[label] / (tp[label] + fp[label]) if (tp[label] + fp[label]) else 0.0
        r = tp[label] / (tp[label] + fn[label]) if (tp[label] + fn[label]) else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        out[label] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "support_gold": tp[label] + fn[label],
            "support_pred": tp[label] + fp[label],
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gate-overall", type=float, default=DEFAULT_GATES["overall"])
    args = parser.parse_args()

    if not args.input_path.exists():
        log.error("input not found: %s", args.input_path)
        return 1

    rows = [json.loads(line) for line in args.input_path.open() if line.strip()]
    reviewed = [r for r in rows if _is_reviewed(r)]
    pending = [r for r in rows if not _is_reviewed(r)]

    by_shape: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_status: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in reviewed:
        by_shape[r["true_shape"] or "unknown"].append(r)
        by_source[r["source"] or "unknown"].append(r)
        # Treat agreed-and-pending as "auto" for status reporting.
        s = "auto-approve" if (r["agreement"] == "agree" and r["reviewer_status"] == "pending") else r["reviewer_status"]
        by_status[s].append(r)

    overall = _aggregate(reviewed)
    summary = {
        "total_rows": len(rows),
        "reviewed": len(reviewed),
        "pending": len(pending),
        "by_status": {s: len(rs) for s, rs in by_status.items()},
        "overall": overall,
        "by_shape": {k: _aggregate(v) for k, v in by_shape.items()},
        "by_source": {k: _aggregate(v) for k, v in by_source.items()},
        "per_label_prf": _per_label_prf(reviewed),
        "gates": {
            "overall_threshold": args.gate_overall,
            "overall_pass": (overall["macro_jaccard"] or 0.0) >= args.gate_overall,
            "per_shape": {
                shape: {
                    "threshold": DEFAULT_GATES.get(shape, args.gate_overall),
                    "macro_jaccard": agg["macro_jaccard"],
                    "pass": (agg["macro_jaccard"] or 0.0) >= DEFAULT_GATES.get(shape, args.gate_overall),
                }
                for shape, agg in {k: _aggregate(v) for k, v in by_shape.items()}.items()
            },
        },
    }

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(summary, indent=2) + "\n")

    # Console report.
    print()  # noqa: T201
    print("─" * 72)  # noqa: T201
    print(f"M4d Phase 3 — review worksheet score ({args.input_path.name})")  # noqa: T201
    print("─" * 72)  # noqa: T201
    print(f"Total rows: {summary['total_rows']}    reviewed: {summary['reviewed']}    pending: {summary['pending']}")  # noqa: T201
    print(f"  by status: {summary['by_status']}")  # noqa: T201
    print()  # noqa: T201
    print(f"OVERALL  macro_jaccard={overall['macro_jaccard']}  exact_match={overall['exact_match']} ({overall['exact_match_rate'] * 100:.1f}%)")  # noqa: T201
    print()  # noqa: T201
    print("BY SHAPE")  # noqa: T201
    for shape, agg in sorted(summary["by_shape"].items()):
        gate = DEFAULT_GATES.get(shape, args.gate_overall)
        verdict = "PASS" if (agg["macro_jaccard"] or 0.0) >= gate else "FAIL"
        print(f"  {shape:28s} n={agg['n']:3d}  macro_jaccard={agg['macro_jaccard']}  exact={agg['exact_match']}  gate={gate}  {verdict}")  # noqa: T201
    print()  # noqa: T201
    print("BY SOURCE")  # noqa: T201
    for source, agg in sorted(summary["by_source"].items()):
        short = source.split(".")[-1]
        print(f"  {short:35s} n={agg['n']:3d}  macro_jaccard={agg['macro_jaccard']}  exact={agg['exact_match']}")  # noqa: T201
    print()  # noqa: T201
    overall_verdict = "PASS" if summary["gates"]["overall_pass"] else "FAIL"
    print(f"OVERALL GATE: threshold={args.gate_overall}  macro={overall['macro_jaccard']}  {overall_verdict}")  # noqa: T201
    print(f"Wrote: {args.output_path}")  # noqa: T201
    return 0 if summary["gates"]["overall_pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
