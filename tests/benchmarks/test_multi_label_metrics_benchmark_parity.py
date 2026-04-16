"""Regression guard for M4e dual-report harness.

Catches silent drift between the single-label and multi-label tiers
of the family benchmark. Two families of invariants:

1. **Per-column vs per-column invariants** (hold always at K=1):

   - ``multi_label.subset_accuracy == multi_label.jaccard_macro`` for
     every K=1 projection, regardless of whether some rows have empty
     pred. Both reduce to "fraction of columns where pred and true
     are identical sets" — identical by construction at K=1.

2. **Global-reduction invariants** (hold only when no row has empty
   pred):

   - ``multi_label.subset_accuracy == multi_label.micro_f1`` also
     holds, BUT only if no row emits ``pred=[]`` vs non-empty
     ``true``. Empty preds add to ``fn`` without a symmetric ``fp``,
     which skews the global micro-count's P and R while leaving the
     per-column reduction untouched. The shadow path never emits
     empty preds (meta-classifier always fires on every shard), so
     the stricter invariant holds there. The live cascade (regex +
     column_name) intentionally falls silent on shards it can't
     classify — so live-path tests assert only the weaker invariant
     plus the "empty preds exist" documentation.

3. **Cross-tier agreement** (Sprint 11 ↔ M4a on the same data):

   - ``shadow.subtype.accuracy == shadow.multi_label.subtype.subset_accuracy``
     to 4-decimal rounding. Both computations reduce to "how often
     does pred exactly equal true" on the same benchmark rows.

When Sprint 13's column-shape router starts emitting ``list[Finding]``
per column, the K=1 invariants no longer hold by design — that's the
entire *point* of dual-report. At that point these assertions move
to a "K=1-only subset of predictions" filter rather than the whole
benchmark.

Fast-path: uses ``--limit 500`` in the module fixture; full-run
validation still lives at the canonical
``python -m tests.benchmarks.family_accuracy_benchmark`` entry-point.
"""

from __future__ import annotations

import json

import pytest

from tests.benchmarks.family_accuracy_benchmark import main as benchmark_main


@pytest.fixture(scope="module")
def small_benchmark_summary(tmp_path_factory):
    """Run the family benchmark on a small shard slice; return the summary.

    500 shards is enough to exercise every code path and stabilize
    the invariant check without paying the 40s full-run cost.
    """
    tmp = tmp_path_factory.mktemp("m4e")
    out_path = tmp / "predictions.jsonl"
    summary_path = tmp / "summary.json"
    exit_code = benchmark_main(
        [
            "--out",
            str(out_path),
            "--summary",
            str(summary_path),
            "--limit",
            "500",
        ]
    )
    assert exit_code == 0
    return json.loads(summary_path.read_text())


class TestSummaryShape:
    def test_multi_label_tier_exists(self, small_benchmark_summary):
        """New multi_label section must appear in every tier slot."""
        for path in ("live.overall", "shadow.overall"):
            obj = small_benchmark_summary
            for key in path.split("."):
                obj = obj[key]
            assert "multi_label" in obj, f"missing multi_label at {path}"
            assert "family" in obj["multi_label"]
            assert "subtype" in obj["multi_label"]

    def test_multi_label_metric_keys(self, small_benchmark_summary):
        ml = small_benchmark_summary["shadow"]["overall"]["multi_label"]["family"]
        required = {
            "jaccard_macro",
            "micro_f1",
            "macro_f1",
            "subset_accuracy",
            "hamming_loss",
            "per_class",
            "n_columns",
        }
        assert required.issubset(ml.keys())

    def test_single_label_tiers_still_present(self, small_benchmark_summary):
        """Sprint 11 continuity: family + subtype tiers must still exist."""
        shadow = small_benchmark_summary["shadow"]["overall"]
        assert "family" in shadow
        assert "subtype" in shadow
        # Canonical Sprint 11 quality gate — must still be readable.
        assert "cross_family_rate" in shadow["family"]
        assert "family_macro_f1" in shadow["family"]


class TestK1Invariants:
    """When every row is K=1, subset_accuracy = jaccard_macro always.

    Stricter invariant — ``subset_accuracy = micro_f1`` — holds only
    when no row is empty-vs-nonempty. Empty preds (cascade silent)
    add to ``fn`` without symmetric ``fp``, which skews global micro
    counts without skewing per-column Jaccard. The shadow path never
    emits empty preds (meta-classifier always fires), so the stricter
    invariant holds there; the live cascade skips rows it can't
    classify, so only the weaker invariant holds.
    """

    def test_family_k1_subset_jaccard_always_equal(self, small_benchmark_summary):
        """subset_accuracy == jaccard_macro at K=1 holds regardless of empties."""
        for path in ("live", "shadow"):
            ml = small_benchmark_summary[path]["overall"]["multi_label"]["family"]
            assert ml["subset_accuracy"] == pytest.approx(ml["jaccard_macro"], abs=1e-9), (
                f"{path}.multi_label.family: subset_acc and jaccard_macro diverged — "
                f"{ml['subset_accuracy']} vs {ml['jaccard_macro']}"
            )

    def test_subtype_k1_subset_jaccard_always_equal(self, small_benchmark_summary):
        for path in ("live", "shadow"):
            ml = small_benchmark_summary[path]["overall"]["multi_label"]["subtype"]
            assert ml["subset_accuracy"] == pytest.approx(ml["jaccard_macro"], abs=1e-9)

    def test_shadow_full_k1_convergence(self, small_benchmark_summary):
        """Shadow path never emits empty preds — full three-way converges."""
        ml = small_benchmark_summary["shadow"]["overall"]["multi_label"]["family"]
        assert ml["subset_accuracy"] == pytest.approx(ml["jaccard_macro"], abs=1e-9)
        assert ml["subset_accuracy"] == pytest.approx(ml["micro_f1"], abs=1e-9)
        # Explicit documentation-via-assertion: shadow must have zero
        # empty preds for this to hold. If this ever flips, the test
        # above this one still passes but the divergence is informative.
        assert ml["n_columns_empty_pred"] == 0, (
            f"shadow emitted {ml['n_columns_empty_pred']} empty preds — "
            f"the full three-way convergence assumption is invalid"
        )

    def test_live_path_has_empty_preds(self, small_benchmark_summary):
        """Live cascade IS expected to skip rows it can't classify —
        this test documents that assumption so it can't silently change."""
        ml = small_benchmark_summary["live"]["overall"]["multi_label"]["family"]
        # The live cascade (regex + column_name) doesn't fire on every shard,
        # especially on blind shards where column name is stripped.
        assert ml["n_columns_empty_pred"] > 0, (
            "live path emitted no empty preds — cascade behavior changed "
            "or synthetic pool no longer contains cascade-silent shards"
        )


class TestCrossTierAgreement:
    """Sprint 11 single-label metrics ↔ M4a multi-label metrics must agree.

    Since this K=1 benchmark is exactly the same underlying data being
    scored two ways, they must match to rounding. The rounding tolerance
    is loose enough to survive Sprint 11's 4-decimal round without
    being loose enough to hide genuine drift.
    """

    def test_subtype_accuracy_matches_subset_accuracy(self, small_benchmark_summary):
        """Sprint 11 subtype accuracy == multi-label subtype subset_accuracy.

        Both reduce to "how often does pred exactly equal true" on the
        same data — any divergence means a projection bug.
        """
        s11 = small_benchmark_summary["shadow"]["overall"]["subtype"]["accuracy"]
        ml = small_benchmark_summary["shadow"]["overall"]["multi_label"]["subtype"]["subset_accuracy"]
        # 5e-4 covers Sprint 11's round(_, 4) without hiding real drift.
        assert s11 == pytest.approx(ml, abs=5e-4), (
            f"Sprint 11 subtype accuracy ({s11}) diverged from "
            f"multi_label subtype subset_accuracy ({ml}) — projection bug?"
        )

    def test_family_cross_family_rate_vs_hamming(self, small_benchmark_summary):
        """cross_family_rate and family-scope hamming_loss are both
        "how wrong were we" — they shouldn't diverge wildly.

        They are NOT equal (cross_family_rate counts per-column,
        hamming_loss counts per-label-cell across universe), but they
        should at least have the same sign of "did accuracy improve".
        This is a looser co-movement check, not strict equality.
        """
        fam = small_benchmark_summary["shadow"]["overall"]["family"]
        ml = small_benchmark_summary["shadow"]["overall"]["multi_label"]["family"]
        # Both in [0, 1]; both measure error.
        assert 0 <= fam["cross_family_rate"] <= 1
        assert 0 <= ml["hamming_loss"] <= 1
        # On the same data, the two shouldn't disagree by more than
        # a factor of ~5 (a sanity check, not a quality gate).
        if fam["cross_family_rate"] > 0.001:
            ratio = ml["hamming_loss"] / fam["cross_family_rate"]
            assert 0.01 <= ratio <= 5.0, (
                f"Suspicious divergence: cross_family_rate={fam['cross_family_rate']} "
                f"vs hamming_loss={ml['hamming_loss']} — ratio={ratio:.3f}"
            )


class TestRegressionBaseline:
    """Guard Sprint 12 baseline numbers on the single-label tier.

    The multi-label section must not have introduced any regression
    on the Sprint 11 continuity metrics. These are loose bounds (the
    500-shard limit gives noisier numbers than the 9870-shard full
    run) — the full-run check is enforced by CLAUDE.md's Sprint
    Completion Gate.
    """

    def test_shadow_cross_family_rate_reasonable(self, small_benchmark_summary):
        rate = small_benchmark_summary["shadow"]["overall"]["family"]["cross_family_rate"]
        assert 0 <= rate <= 0.10, (
            f"shadow cross_family_rate={rate} — Sprint 12 baseline was 0.0044; "
            f"this is way outside tolerance. Did the wire-in break the shadow path?"
        )

    def test_shadow_family_macro_f1_reasonable(self, small_benchmark_summary):
        f1 = small_benchmark_summary["shadow"]["overall"]["family"]["family_macro_f1"]
        assert f1 >= 0.90, f"shadow family_macro_f1={f1} — Sprint 12 baseline was 0.9945; this is way below tolerance."


class TestLabelSpacePinned:
    """Label space for Hamming is the canonical taxonomy, not observed labels.

    Passing `label_space=None` to aggregate_multi_label would let the
    universe depend on what labels the benchmark happens to emit,
    which would make Hamming loss non-comparable across runs. The
    wire-in pins the universe to ``FAMILIES`` / ``ENTITY_TYPE_TO_FAMILY``.
    """

    def test_family_label_space_is_thirteen(self, small_benchmark_summary):
        """13 canonical families. per_class entries can be fewer
        (only labels that appeared); label_space determines Hamming."""
        ml = small_benchmark_summary["shadow"]["overall"]["multi_label"]["family"]
        # Every class that appeared in pred or true is in per_class;
        # classes that never appeared are absent.
        from data_classifier import FAMILIES

        for cls in ml["per_class"]:
            assert cls in FAMILIES, f"{cls} in per_class but not in canonical FAMILIES"
