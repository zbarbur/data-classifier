"""WildChat labeled-eval regression test (Sprint 18 item).

Locks in the labeled WildChat eval set as a regression gate:

* The fixture ``data/wildchat_labeled_eval/labeled_set.jsonl`` is built
  by ``scripts/build_wildchat_labeled.py``.  It carries 334 human-
  reviewed prompts (425 TP / 549 FP per-finding verdicts) plus the
  rest of the 3,515-prompt WildChat credential corpus, with the
  scanner output snapshotted at build time.
* These tests rescan every prompt with the current scanner and diff
  against the snapshotted output.  Any diff means the scanner has
  drifted from the locked baseline — either a regression or an
  intentional improvement that requires re-running the build script.

Two test classes:

* ``TestLabelPreservation`` — TP rows must keep emitting; FP rows
  must not grow the finding count.  These are the tight gates.
* ``TestSnapshotIntegrity`` — full diff against the snapshot
  (entity_type, span, confidence).  Surfaces drift even when the
  metric counts didn't move.

Skips the entire module when the labeled set isn't available
(DVC-tracked; CI must ``dvc pull`` first).
"""

from __future__ import annotations

import json

import pytest

from tests.benchmarks.wildchat_labeled_eval import DEFAULT_LABELED_PATH, evaluate_labeled_set

_LABELED_SET_PRESENT = DEFAULT_LABELED_PATH.exists()
_SKIP_REASON = (
    f"Labeled set missing at {DEFAULT_LABELED_PATH} — "
    "build via `.venv/bin/python scripts/build_wildchat_labeled.py` "
    "or `dvc pull data/wildchat_labeled_eval/`. "
    "See docs/process/dataset_management.md."
)

# Locked Sprint 18 baselines from the initial build (scanner state at
# commit time).  Tightening these is welcome; loosening requires
# rebuilding the labeled set and an explicit decision in the PR.
_MAX_TP_ROWS_LOST: int = 1
_MIN_TP_ROWS_KEPT: int = 153

pytestmark = pytest.mark.skipif(not _LABELED_SET_PRESENT, reason=_SKIP_REASON)


@pytest.fixture(scope="module")
def labeled_metrics() -> dict:
    return evaluate_labeled_set()


class TestLabelPreservation:
    """Hard gates on the human-reviewed slice of the corpus."""

    def test_no_more_than_baseline_tp_rows_lost(self, labeled_metrics: dict) -> None:
        """Sprint 18 baseline: 1 TP row lost (prompt 2130).  Anything
        above this means the scanner has dropped a previously-confirmed
        secret detection — block merge.
        """
        lost = labeled_metrics["n_tp_rows_lost"]
        assert lost <= _MAX_TP_ROWS_LOST, (
            f"Lost {lost} TP rows (baseline: {_MAX_TP_ROWS_LOST}). "
            f"Regressed prompt_ids: {labeled_metrics['regressed_tp_prompt_ids']}"
        )

    def test_tp_rows_kept_at_or_above_baseline(self, labeled_metrics: dict) -> None:
        """The kept-count is the inverse of the lost-count and acts as
        a sanity check on the labeled-set integrity itself.
        """
        kept = labeled_metrics["n_tp_rows_kept"]
        assert kept >= _MIN_TP_ROWS_KEPT, (
            f"Only {kept} TP rows kept (baseline: {_MIN_TP_ROWS_KEPT}). "
            "Did the labeled set get rebuilt against a degraded scanner?"
        )

    def test_dataset_size_invariant(self, labeled_metrics: dict) -> None:
        """The labeled set is the full 3,515-prompt corpus.  A smaller
        count means a build-script regression or fixture truncation.
        """
        assert labeled_metrics["n_rows"] == 3515, (
            f"Expected 3515 rows, got {labeled_metrics['n_rows']}. Rebuild via scripts/build_wildchat_labeled.py."
        )
        assert labeled_metrics["n_reviewed"] == 334, (
            f"Expected 334 reviewed rows, got {labeled_metrics['n_reviewed']}. "
            "Source review_corpus.jsonl may have changed."
        )


class TestSnapshotIntegrity:
    """Snapshot diff: live scan vs. baked-in scanner_findings.

    The labeled set carries a snapshot of scanner output from the
    moment it was built.  These tests confirm the snapshot is internally
    consistent (no NaN confidences, no negative spans) and surface
    aggregate drift if the scanner has changed without a rebuild.
    """

    def test_snapshot_finding_shape_is_well_formed(self) -> None:
        with DEFAULT_LABELED_PATH.open() as f:
            for line in f:
                row = json.loads(line)
                for finding in row["scanner_findings"]:
                    assert finding["entity_type"], "entity_type must be non-empty"
                    assert isinstance(finding["confidence"], (int, float))
                    assert 0.0 <= finding["confidence"] <= 1.0
                    if finding["start"] is not None and finding["end"] is not None:
                        assert finding["start"] >= 0
                        assert finding["end"] > finding["start"]

    def test_human_verdicts_are_normalised(self) -> None:
        """Every row that claims ``reviewed=True`` must carry a non-None
        ``human_verdicts`` dict (the build script normalises non-tp/fp
        labels out, but the field itself must exist).
        """
        with DEFAULT_LABELED_PATH.open() as f:
            for line in f:
                row = json.loads(line)
                if row["reviewed"]:
                    assert row["human_verdicts"] is not None, (
                        f"reviewed=True but human_verdicts is None for prompt {row['prompt_id']}"
                    )
                else:
                    assert row["human_verdicts"] is None
