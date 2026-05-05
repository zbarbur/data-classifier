"""WildChat labeled-eval runner — Sprint 18 regression infrastructure.

Loads ``data/wildchat_labeled_eval/labeled_set.jsonl`` (built by
``scripts/build_wildchat_labeled.py``) and computes per-row regression
metrics by comparing the *current* scanner output against the
labeled per-finding verdicts.

The runner is intentionally a thin pure function so the regression
test (``tests/test_wildchat_labeled_regression.py``) can call it
without subprocesses.  The labeled set is large enough (~48 MB,
3,515 rows) that we keep IO scoped to one open call.

Returned shape::

    {
        "n_rows": int,
        "n_reviewed": int,
        "n_tp_rows_kept": int,        # TP_REVIEWED rows with >=1 current finding
        "n_tp_rows_lost": int,        # TP_REVIEWED rows with 0 current findings (REGRESSION)
        "n_fp_rows_clean": int,       # FP_REVIEWED rows with 0 current findings
        "n_fp_rows_residual": int,    # FP_REVIEWED rows that still emit (info, not regression)
        "n_fp_rows_grew": int,        # FP_REVIEWED rows where current findings exceed historical (REGRESSION)
        "regressed_tp_prompt_ids": list[int],
        "regressed_new_fp_prompt_ids": list[int],
    }

Two regression classes:

* **TP regression** — a TP_REVIEWED row that previously emitted at
  least one finding but now emits none means we lost a confirmed
  secret detection.
* **FP regression** — an FP_REVIEWED row whose finding count exceeds
  the historical ``old_findings`` count means we grew the FP surface
  for a prompt the human flagged as not-a-secret.

FP_REVIEWED rows that *shrink* are improvements; the runner reports
them but they never fail the test.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_LABELED_PATH = Path("data/wildchat_labeled_eval/labeled_set.jsonl")


def evaluate_labeled_set(labeled_path: Path = DEFAULT_LABELED_PATH) -> dict:
    """Compute regression metrics over the labeled set."""
    if not labeled_path.exists():
        raise FileNotFoundError(
            f"Labeled set missing: {labeled_path}\n"
            "Build via: .venv/bin/python scripts/build_wildchat_labeled.py\n"
            "See docs/process/dataset_management.md."
        )

    n_rows = 0
    n_reviewed = 0
    n_tp_rows_kept = 0
    n_tp_rows_lost = 0
    n_fp_rows_clean = 0
    n_fp_rows_residual = 0
    n_fp_rows_grew = 0
    regressed_tp: list[int] = []
    regressed_new_fp: list[int] = []

    with labeled_path.open() as f:
        for line in f:
            row = json.loads(line)
            n_rows += 1
            label = row.get("label", "")
            scanner_findings = row.get("scanner_findings") or []
            old_findings = row.get("old_findings") or []

            if not row.get("reviewed"):
                continue
            n_reviewed += 1

            if label == "TP_REVIEWED":
                # Reviewed as confirmed-real; we must still emit something.
                if scanner_findings:
                    n_tp_rows_kept += 1
                else:
                    n_tp_rows_lost += 1
                    regressed_tp.append(row["prompt_id"])
            elif label == "FP_REVIEWED":
                # Reviewed as not-a-secret; ideally we emit nothing, but
                # the immediate regression bar is "don't grow the FP set".
                if not scanner_findings:
                    n_fp_rows_clean += 1
                else:
                    n_fp_rows_residual += 1
                    if len(scanner_findings) > len(old_findings):
                        n_fp_rows_grew += 1
                        regressed_new_fp.append(row["prompt_id"])

    return {
        "n_rows": n_rows,
        "n_reviewed": n_reviewed,
        "n_tp_rows_kept": n_tp_rows_kept,
        "n_tp_rows_lost": n_tp_rows_lost,
        "n_fp_rows_clean": n_fp_rows_clean,
        "n_fp_rows_residual": n_fp_rows_residual,
        "n_fp_rows_grew": n_fp_rows_grew,
        "regressed_tp_prompt_ids": regressed_tp,
        "regressed_new_fp_prompt_ids": regressed_new_fp,
    }


__all__ = ["DEFAULT_LABELED_PATH", "evaluate_labeled_set"]
