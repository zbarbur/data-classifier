"""Build the M4d Phase 3 spot-check review worksheet.

Consumes ``data/m4d_phase3b_corpus/labeled.jsonl`` (produced by
``scripts.run_m4d_phase3_scale``) and emits a JSONL worksheet the human
reviewer fills in, plus a markdown companion for quick scanning.

For the Phase 3a pilot (~45 cols) the worksheet covers every row — no
sampling. Phase 3b (~500 cols) will switch to stratified sampling; the
``--sample-size`` flag is scaffolded now.

Review workflow::

    .venv/bin/python -m scripts.m4d_phase3_build_worksheet
    # Reviewer edits review_worksheet.jsonl: sets reviewer_labels and
    # reviewer_status for each row.
    .venv/bin/python -m scripts.m4d_phase3_score_worksheet   # (next sprint)

Worksheet row schema:

    column_id, source, source_reference, true_shape, encoding,
    prefill_labels, pred_labels, labeler_error,
    agreement (str: agree | disagree | error),
    sample_values_decoded (first 10 decoded values for eyeballing),
    reviewer_labels: [] (TO FILL — empty means "matches pred_labels"),
    reviewer_status: "pending" (TO UPDATE → approve | amend | reject),
    reviewer_notes: "" (TO FILL — free text)
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

from data_classifier.patterns._decoder import decode_encoded_strings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "data/m4d_phase3b_corpus/labeled.jsonl"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/m4d_phase3b_corpus"
DEFAULT_SAMPLE_VALUES = 10  # per row shown to the reviewer


def _agreement(prefill: list[str], pred: list[str], error: str | None) -> str:
    if error:
        return "error"
    return "agree" if set(prefill) == set(pred) else "disagree"


def _decode_sample_values(row: dict[str, Any], k: int) -> list[str]:
    values = row.get("values") or []
    encoding = row.get("encoding", "plaintext")
    if encoding == "xor":
        values = decode_encoded_strings(values)
    # Truncate each value at 200 chars so the worksheet stays scannable.
    return [v[:200] + ("…" if len(v) > 200 else "") for v in values[:k]]


def _stratified_sample(rows: list[dict[str, Any]], target_n: int, seed: int) -> list[dict[str, Any]]:
    """Proportional allocation across true_shape × agreement groups.

    Stable under ``seed``; callable but unused at pilot scale (all 41 rows
    ≤ 50 ≤ sample_size default). Kept here so Phase 3b can flip to
    sampling without restructuring the script.
    """
    if len(rows) <= target_n:
        return list(rows)
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        agreement = _agreement(r.get("prefill_labels", []), r.get("pred_labels", []), r.get("error"))
        groups[(r.get("true_shape", "unknown"), agreement)].append(r)
    out: list[dict[str, Any]] = []
    for group_rows in groups.values():
        share = max(1, round(len(group_rows) / len(rows) * target_n))
        out.extend(rng.sample(group_rows, min(share, len(group_rows))))
    # Trim or top up to hit target_n exactly.
    if len(out) > target_n:
        out = rng.sample(out, target_n)
    elif len(out) < target_n:
        remaining = [r for r in rows if r not in out]
        out.extend(rng.sample(remaining, min(target_n - len(out), len(remaining))))
    out.sort(key=lambda r: r["column_id"])
    return out


def _to_worksheet_row(row: dict[str, Any], sample_k: int) -> dict[str, Any]:
    prefill = row.get("prefill_labels", [])
    pred = row.get("pred_labels", [])
    error = row.get("error")
    return {
        "column_id": row["column_id"],
        "source": row.get("source"),
        "source_reference": row.get("source_reference"),
        "true_shape": row.get("true_shape"),
        "encoding": row.get("encoding"),
        "prefill_labels": sorted(prefill),
        "pred_labels": sorted(pred),
        "labeler_error": error,
        "agreement": _agreement(prefill, pred, error),
        "sample_values_decoded": _decode_sample_values(row, sample_k),
        # Reviewer fields — start empty so the reviewer knows what to fill.
        "reviewer_labels": [],
        "reviewer_status": "pending",
        "reviewer_notes": "",
    }


def _write_markdown(worksheet: list[dict[str, Any]], out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# M4d Phase 3a — spot-check review worksheet\n\n")
    lines.append(
        f"**Rows:** {len(worksheet)}. Agreement counts: "
        f"agree={sum(1 for r in worksheet if r['agreement'] == 'agree')}, "
        f"disagree={sum(1 for r in worksheet if r['agreement'] == 'disagree')}, "
        f"error={sum(1 for r in worksheet if r['agreement'] == 'error')}.\n\n"
    )
    lines.append("Edit `review_worksheet.jsonl` (not this file) to record decisions.\n\n")
    by_shape: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in worksheet:
        by_shape[r["true_shape"] or "unknown"].append(r)
    for shape in sorted(by_shape.keys()):
        lines.append(f"## Shape: `{shape}` ({len(by_shape[shape])} rows)\n\n")
        for r in sorted(by_shape[shape], key=lambda r: r["column_id"]):
            lines.append(f"### `{r['column_id']}` — {r['agreement']}\n\n")
            lines.append(f"- source: `{r['source']}`\n")
            lines.append(f"- reference: `{r['source_reference']}`\n")
            lines.append(f"- prefill: `{r['prefill_labels']}`\n")
            lines.append(f"- pred:    `{r['pred_labels']}`\n")
            if r["labeler_error"]:
                lines.append(f"- error:   `{r['labeler_error']}`\n")
            lines.append("- samples:\n")
            for i, v in enumerate(r["sample_values_decoded"], start=1):
                # Escape pipes for markdown-friendliness; tabulate values as a list.
                safe = v.replace("`", "'").replace("\n", " ⏎ ")
                lines.append(f"  {i}. `{safe}`\n")
            lines.append("\n")
    out_path.write_text("".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=0,
        help="Stratified-sample N rows (0 = keep all; for pilot leave at 0).",
    )
    parser.add_argument(
        "--sample-values",
        type=int,
        default=DEFAULT_SAMPLE_VALUES,
        help=f"Values shown per column to the reviewer (default {DEFAULT_SAMPLE_VALUES}).",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not args.input_path.exists():
        log.error("input not found: %s", args.input_path)
        return 1

    with args.input_path.open() as f:
        rows = [json.loads(line) for line in f if line.strip()]
    log.info("loaded %d labeled rows from %s", len(rows), args.input_path)

    if args.sample_size and args.sample_size < len(rows):
        rows = _stratified_sample(rows, args.sample_size, args.seed)
        log.info("stratified-sampled to %d rows", len(rows))

    worksheet = [_to_worksheet_row(r, args.sample_values) for r in rows]
    worksheet.sort(key=lambda r: (r["true_shape"] or "", r["column_id"]))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.output_dir / "review_worksheet.jsonl"
    md_path = args.output_dir / "review_worksheet.md"

    with jsonl_path.open("w") as f:
        for wrow in worksheet:
            f.write(json.dumps(wrow, ensure_ascii=False) + "\n")
    _write_markdown(worksheet, md_path)

    agree = sum(1 for r in worksheet if r["agreement"] == "agree")
    disagree = sum(1 for r in worksheet if r["agreement"] == "disagree")
    errors = sum(1 for r in worksheet if r["agreement"] == "error")
    print()  # noqa: T201
    print("─" * 60)  # noqa: T201
    print(f"M4d Phase 3 review worksheet — {len(worksheet)} rows")  # noqa: T201
    print("─" * 60)  # noqa: T201
    print(f"agree / disagree / error: {agree} / {disagree} / {errors}")  # noqa: T201
    print(f"Wrote: {jsonl_path}")  # noqa: T201
    print(f"Wrote: {md_path}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
