"""Split full scan output into structural candidates + full archive.

Reads the post-scan candidates.jsonl (every prompt — 3.5 GB) and writes:
  - candidates.jsonl  (kept name): prompts with any non-NL zone (code/markup/
                       data/config/error_output/cli_shell/query) OR any secret.
                       This is the "interesting" sparse view.
  - all_prompts.jsonl: every prompt — the full archive intended for DVC.

The full file is renamed first so we don't lose data on script failure.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

OUT_DIR = Path("data/wildchat_unified")
SOURCE = OUT_DIR / "candidates.jsonl"
ARCHIVE = OUT_DIR / "all_prompts.jsonl"
NEW_CANDIDATES = OUT_DIR / "candidates.jsonl"  # same path, rewritten after rename
NON_NL_TYPES = {"code", "markup", "config", "data", "query", "cli_shell", "error_output"}


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing {SOURCE}")

    # Step 1: rename to archive (atomic, no copy)
    print(f"Renaming {SOURCE} → {ARCHIVE}")
    SOURCE.rename(ARCHIVE)

    total = 0
    kept = 0
    with ARCHIVE.open() as f_in, NEW_CANDIDATES.open("w") as f_out:
        for line in f_in:
            total += 1
            if total % 100_000 == 0:
                print(f"  processed {total:,} ({kept:,} kept)")
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            zones = rec.get("zones") or []
            secrets = rec.get("secrets") or []
            # Keep if any non-NL zone OR any secret
            if any(z.get("zone_type") in NON_NL_TYPES for z in zones) or secrets:
                f_out.write(line)
                kept += 1

    print()
    print(f"Total prompts: {total:,}")
    print(f"Kept (any non-NL zone or secret): {kept:,} ({kept/total*100:.2f}%)")
    print(f"Discarded (pure NL): {total - kept:,}")
    print()
    print(f"Output files:")
    print(f"  {NEW_CANDIDATES} ({NEW_CANDIDATES.stat().st_size:,} bytes)")
    print(f"  {ARCHIVE} ({ARCHIVE.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
