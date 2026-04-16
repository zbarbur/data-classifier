"""Interactive labeler CLI for the M4c heterogeneous gold set.

Paginates columns where ``review_status != 'human_reviewed'``, decodes
XOR-encoded values for display, and accepts accept/edit/skip/quit
commands. Writes atomically (temp file + rename) so Ctrl-C mid-session
can never corrupt the gold set.

Usage::

    python -m tests.benchmarks.meta_classifier.gold_set_labeler
    python -m tests.benchmarks.meta_classifier.gold_set_labeler \\
        --annotator "guy.guzner" --show-values 15

The labeler pre-fills were written by Claude Opus 4.6. Every row still
needs human review before it counts as gold. See
``docs/research/multi_label_gold_set_annotator_guide.md`` for the
annotation protocol.

This module uses ``print`` (not ``logging``) because it is a CLI
labeler whose stdout output IS the user interface — the values, the
prompt, the confirmation land in front of the labeler's eyes. The
``# noqa: T201`` on each ``print`` documents that this is an
intentional CLI entrypoint, not a library-code violation of
CLAUDE.md's "no print statements" rule.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from data_classifier.core.taxonomy import ENTITY_TYPE_TO_FAMILY, family_for
from data_classifier.patterns._decoder import decode_encoded_strings

GOLD_SET_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "tests/benchmarks/meta_classifier/heterogeneous_gold_set.jsonl"
)

# Terminal colours (plain ANSI; degrades gracefully on dumb terminals).
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


ALLOWED_ENTITIES = sorted(ENTITY_TYPE_TO_FAMILY.keys())


@dataclass
class LabelerArgs:
    gold_set_path: Path
    annotator: str
    show_values: int
    show_all: bool


def load_rows(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def write_rows_atomic(path: Path, rows: list[dict]) -> None:
    """Write JSONL atomically so Ctrl-C mid-write can't corrupt the file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def decode_for_display(values: list[str], encoding: str) -> list[str]:
    if encoding == "xor":
        return decode_encoded_strings(values)
    return values


def validate_labels(labels: list[str]) -> tuple[list[str], list[str]]:
    """Split labels into (valid, unknown). Unknown = not in taxonomy."""
    valid = [lbl for lbl in labels if lbl in ENTITY_TYPE_TO_FAMILY]
    unknown = [lbl for lbl in labels if lbl not in ENTITY_TYPE_TO_FAMILY]
    return valid, unknown


def parse_labels(raw: str) -> list[str]:
    """Parse a comma/space-separated label string. Empty → []."""
    raw = raw.strip()
    if not raw:
        return []
    parts: list[str] = []
    for chunk in raw.replace(";", ",").split(","):
        for token in chunk.strip().split():
            token = token.upper().strip()
            if token:
                parts.append(token)
    # Preserve first-seen order but dedupe.
    seen: set[str] = set()
    ordered: list[str] = []
    for p in parts:
        if p not in seen:
            ordered.append(p)
            seen.add(p)
    return ordered


def display_row(row: dict, args: LabelerArgs, idx: int, total_to_review: int, total: int) -> None:
    """Pretty-print one row for labeling."""
    decoded = decode_for_display(row["values"], row["encoding"])
    n_values = len(decoded)
    to_show = n_values if args.show_all else min(args.show_values, n_values)

    print()  # noqa: T201
    print(f"{BOLD}{'═' * 74}{RESET}")  # noqa: T201
    print(  # noqa: T201
        f"{BOLD}[{idx}/{total_to_review}]{RESET}  "
        f"{CYAN}{row['column_id']}{RESET}  "
        f"{DIM}(row {row.get('_original_idx', '?')}/{total}){RESET}"
    )
    print(f"{DIM}source:    {row['source']}{RESET}")  # noqa: T201
    print(f"{DIM}reference: {row['source_reference']}{RESET}")  # noqa: T201
    print(  # noqa: T201
        f"{DIM}shape:     {row['true_shape']}   encoding: {row['encoding']}   values: {n_values}{RESET}"
    )
    print(f"{DIM}notes:     {row['notes']}{RESET}")  # noqa: T201
    print()  # noqa: T201
    print(f"{YELLOW}Sample values (showing {to_show}/{n_values}):{RESET}")  # noqa: T201
    for i, v in enumerate(decoded[:to_show]):
        # Truncate very long values for readability — full value is in the file.
        display_v = v if len(v) <= 200 else v[:200] + f"{DIM}… ({len(v)} chars total){RESET}"
        print(f"  {DIM}[{i:>3}]{RESET} {display_v}")  # noqa: T201
    print()  # noqa: T201
    print(  # noqa: T201
        f"{YELLOW}Pre-filled labels (Claude's best guess):{RESET}  {GREEN}{row['true_labels']}{RESET}"
    )
    print(  # noqa: T201
        f"{YELLOW}Derived families:{RESET}                         {GREEN}{row['true_labels_family']}{RESET}"
    )
    if row["true_labels_prevalence"]:
        print(  # noqa: T201
            f"{YELLOW}Prevalence estimates:{RESET}                     {row['true_labels_prevalence']}"
        )


def prompt_action(row: dict) -> tuple[str, list[str] | None]:
    """Prompt for user action. Returns (action, new_labels_or_None).

    Actions: accept | edit | skip | expand | quit
    """
    while True:
        print(  # noqa: T201
            f"\n{BOLD}[a]ccept  [e]dit  [s]kip  [x]expand-values  [q]uit{RESET}   ",
            end="",
        )
        try:
            raw = input().strip().lower()
        except EOFError:
            return ("quit", None)
        if raw in ("a", "accept", ""):
            return ("accept", row["true_labels"])
        if raw in ("s", "skip"):
            return ("skip", None)
        if raw in ("q", "quit", "exit"):
            return ("quit", None)
        if raw in ("x", "expand"):
            return ("expand", None)
        if raw in ("e", "edit"):
            print(  # noqa: T201
                f"{YELLOW}New labels (comma-separated, empty=no labels).{RESET}\n"
                f"{DIM}Valid entities: {', '.join(ALLOWED_ENTITIES)}{RESET}\n> ",
                end="",
            )
            try:
                raw_labels = input()
            except EOFError:
                return ("quit", None)
            new_labels = parse_labels(raw_labels)
            valid, unknown = validate_labels(new_labels)
            if unknown:
                print(  # noqa: T201
                    f"{RED}Unknown labels (will be skipped): {unknown}{RESET}\n"
                    f"{DIM}Valid entities: {', '.join(ALLOWED_ENTITIES)}{RESET}"
                )
            # Show what will be stored for confirmation.
            new_families = sorted({family_for(e) for e in valid if family_for(e)})
            print(  # noqa: T201
                f"{YELLOW}Will store:{RESET} labels={GREEN}{valid}{RESET}  families={GREEN}{new_families}{RESET}"
            )
            print(f"{BOLD}Confirm? [y]/n{RESET}   ", end="")  # noqa: T201
            try:
                confirm = input().strip().lower()
            except EOFError:
                return ("quit", None)
            if confirm in ("", "y", "yes"):
                return ("edit", valid)
            # Fall through — re-prompt
        else:
            print(f"{RED}Unknown command: {raw!r}{RESET}")  # noqa: T201


def run_labeler(args: LabelerArgs) -> int:
    rows = load_rows(args.gold_set_path)
    if not rows:
        print(f"{RED}No rows found at {args.gold_set_path}{RESET}")  # noqa: T201
        return 1

    # Tag each row with its original index so skip/quit preserves ordering.
    for i, row in enumerate(rows):
        row["_original_idx"] = i

    todo = [r for r in rows if r.get("review_status") != "human_reviewed"]
    total_to_review = len(todo)
    print(  # noqa: T201
        f"{BOLD}Gold set:{RESET} {args.gold_set_path}\n"
        f"{BOLD}Total rows:{RESET} {len(rows)}  "
        f"{BOLD}To review:{RESET} {total_to_review}  "
        f"{BOLD}Annotator:{RESET} {args.annotator}"
    )

    if not todo:
        print(f"{GREEN}All rows already reviewed. Nothing to do.{RESET}")  # noqa: T201
        return 0

    reviewed_count = 0
    idx = 0
    while idx < len(todo):
        row = todo[idx]
        display_row(row, args, idx=idx + 1, total_to_review=total_to_review, total=len(rows))
        action, new_labels = prompt_action(row)

        if action == "quit":
            print(f"\n{YELLOW}Quitting. Progress so far is saved.{RESET}")  # noqa: T201
            break

        if action == "skip":
            print(f"{DIM}skipped{RESET}")  # noqa: T201
            idx += 1
            continue

        if action == "expand":
            args.show_all = True
            continue  # re-display with all values

        # accept or edit — update the canonical row
        if new_labels is not None:
            orig = next(r for r in rows if r["_original_idx"] == row["_original_idx"])
            orig["true_labels"] = new_labels
            orig["true_labels_family"] = sorted({family_for(e) for e in new_labels if family_for(e)})
            orig["review_status"] = "human_reviewed"
            orig["annotator"] = args.annotator
            orig["annotated_on"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Strip the transient _original_idx before writing.
            to_write = [{k: v for k, v in r.items() if k != "_original_idx"} for r in rows]
            write_rows_atomic(args.gold_set_path, to_write)

            reviewed_count += 1
            print(f"{GREEN}✓ saved ({reviewed_count} reviewed this session){RESET}")  # noqa: T201

        args.show_all = False  # reset expand after each row
        idx += 1

    remaining = sum(1 for r in rows if r.get("review_status") != "human_reviewed")
    print()  # noqa: T201
    print(  # noqa: T201
        f"{BOLD}Session summary:{RESET}  reviewed {reviewed_count} this session.  {remaining} still to review."
    )
    return 0


def parse_args(argv: list[str] | None = None) -> LabelerArgs:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--gold-set",
        type=Path,
        default=GOLD_SET_PATH,
        help=f"Path to the JSONL gold set. Default: {GOLD_SET_PATH}",
    )
    parser.add_argument(
        "--annotator",
        type=str,
        default=os.environ.get("USER", "unknown"),
        help="Annotator name to write into reviewed rows.",
    )
    parser.add_argument(
        "--show-values",
        type=int,
        default=20,
        help="Number of sample values to show per column (default: 20; use x command to expand to all).",
    )
    ns = parser.parse_args(argv)
    return LabelerArgs(
        gold_set_path=ns.gold_set,
        annotator=ns.annotator,
        show_values=ns.show_values,
        show_all=False,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_labeler(args)


if __name__ == "__main__":
    sys.exit(main())
