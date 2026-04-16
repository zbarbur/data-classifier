"""Unit tests for multi_label_metrics.py.

Coverage: every edge case the M4a spec calls out (empty prediction,
empty ground truth, perfect match, total mismatch, partial overlap) at
the per-column layer, plus a handful of aggregation scenarios that
exercise the macro/micro/per-class contract.

Written to run fast (<100ms) so dev-loop feedback stays tight.
"""

from __future__ import annotations

import math

import pytest

from tests.benchmarks.meta_classifier.multi_label_metrics import (
    ColumnResult,
    aggregate_multi_label,
    collect_label_support,
    f1,
    hamming_loss,
    jaccard,
    precision,
    recall,
    subset_accuracy,
)

# --------------------------------------------------------------------------- #
# Jaccard — primary metric, most surface area
# --------------------------------------------------------------------------- #


class TestJaccard:
    def test_empty_empty_is_one(self):
        """POLICY #1: correctly-empty on correctly-empty = perfect."""
        assert jaccard([], []) == 1.0

    def test_empty_pred_nonempty_true_is_zero(self):
        assert jaccard([], ["EMAIL"]) == 0.0

    def test_nonempty_pred_empty_true_is_zero(self):
        assert jaccard(["EMAIL"], []) == 0.0

    def test_perfect_match(self):
        assert jaccard(["EMAIL", "PHONE"], ["EMAIL", "PHONE"]) == 1.0

    def test_order_independence(self):
        assert jaccard(["EMAIL", "PHONE"], ["PHONE", "EMAIL"]) == 1.0

    def test_duplicates_collapsed(self):
        """Multi-label sets are by definition unique — duplicates are ignored."""
        assert jaccard(["EMAIL", "EMAIL"], ["EMAIL"]) == 1.0

    def test_partial_overlap(self):
        # pred={A,B}, true={B,C} → inter={B}, union={A,B,C} → 1/3
        assert jaccard(["A", "B"], ["B", "C"]) == pytest.approx(1 / 3)

    def test_total_mismatch(self):
        assert jaccard(["A", "B"], ["C", "D"]) == 0.0

    def test_subset_pred(self):
        # pred={A}, true={A,B} → inter={A}, union={A,B} → 0.5
        assert jaccard(["A"], ["A", "B"]) == 0.5


# --------------------------------------------------------------------------- #
# Precision / Recall / F1
# --------------------------------------------------------------------------- #


class TestPrecisionRecallF1:
    def test_all_empty(self):
        assert precision([], []) == 1.0
        assert recall([], []) == 1.0
        assert f1([], []) == 1.0

    def test_empty_pred_nonempty_true(self):
        # precision is 0/0 → 1.0 (nothing predicted, nothing wrong);
        # recall is 0/1 → 0.0 (missed everything);
        # f1 collapses to ~0.
        assert precision([], ["A"]) == 1.0
        assert recall([], ["A"]) == 0.0
        assert f1([], ["A"]) == pytest.approx(0.0)

    def test_nonempty_pred_empty_true(self):
        # precision is 0/1 → 0.0; recall is 0/0 → 1.0
        assert precision(["A"], []) == 0.0
        assert recall(["A"], []) == 1.0
        assert f1(["A"], []) == pytest.approx(0.0)

    def test_partial_overlap(self):
        # pred={A,B}, true={B,C} → P=1/2, R=1/2, F1=0.5
        assert precision(["A", "B"], ["B", "C"]) == 0.5
        assert recall(["A", "B"], ["B", "C"]) == 0.5
        assert f1(["A", "B"], ["B", "C"]) == 0.5

    def test_perfect_match(self):
        assert f1(["A", "B"], ["A", "B"]) == 1.0


# --------------------------------------------------------------------------- #
# Hamming loss — requires label space
# --------------------------------------------------------------------------- #


class TestHammingLoss:
    def test_empty_label_space(self):
        assert hamming_loss(["A"], ["B"], []) == 0.0

    def test_perfect_match(self):
        assert hamming_loss(["A", "B"], ["A", "B"], ["A", "B", "C"]) == 0.0

    def test_total_mismatch(self):
        # universe={A,B}; pred={A}, true={B}; both labels disagree → 2/2
        assert hamming_loss(["A"], ["B"], ["A", "B"]) == 1.0

    def test_partial(self):
        # universe={A,B,C}; pred={A,B}, true={B,C}; disagree on A and C → 2/3
        assert hamming_loss(["A", "B"], ["B", "C"], ["A", "B", "C"]) == pytest.approx(2 / 3)

    def test_label_outside_universe_ignored(self):
        """Hamming only scores labels inside the declared universe."""
        assert hamming_loss(["A", "X"], ["A", "Y"], ["A", "B"]) == 0.0


# --------------------------------------------------------------------------- #
# Subset accuracy
# --------------------------------------------------------------------------- #


class TestSubsetAccuracy:
    def test_exact_match(self):
        assert subset_accuracy(["A", "B"], ["A", "B"]) == 1.0

    def test_one_off(self):
        assert subset_accuracy(["A", "B"], ["A"]) == 0.0

    def test_empty_empty(self):
        assert subset_accuracy([], []) == 1.0


# --------------------------------------------------------------------------- #
# aggregate_multi_label — benchmark-level roll-up
# --------------------------------------------------------------------------- #


class TestAggregate:
    def test_empty_benchmark(self):
        report = aggregate_multi_label([])
        assert report["n_columns"] == 0
        assert report["jaccard_macro"] == 1.0
        assert report["per_class"] == {}

    def test_single_perfect_column(self):
        rows = [ColumnResult("c1", ["EMAIL"], ["EMAIL"])]
        report = aggregate_multi_label(rows)
        assert report["jaccard_macro"] == 1.0
        assert report["micro_f1"] == 1.0
        assert report["macro_f1"] == 1.0
        assert report["subset_accuracy"] == 1.0
        assert report["per_class"]["EMAIL"]["support"] == 1

    def test_all_empty_columns(self):
        """Negative-control benchmark: no PII anywhere."""
        rows = [
            ColumnResult("c1", [], []),
            ColumnResult("c2", [], []),
        ]
        report = aggregate_multi_label(rows)
        assert report["jaccard_macro"] == 1.0
        assert report["n_columns_empty_pred"] == 2
        assert report["n_columns_empty_true"] == 2
        assert report["per_class"] == {}
        # macro-F1 falls back to 1.0 when no labels exist at all
        assert report["macro_f1"] == 1.0

    def test_partial_overlap_aggregation(self):
        """Two columns, both 1/3 Jaccard — macro should land at 1/3."""
        rows = [
            ColumnResult("c1", ["A", "B"], ["B", "C"]),
            ColumnResult("c2", ["X", "Y"], ["Y", "Z"]),
        ]
        report = aggregate_multi_label(rows)
        assert report["jaccard_macro"] == pytest.approx(1 / 3)
        # n_columns check — cheap sanity
        assert report["n_columns"] == 2

    def test_macro_vs_micro_divergence(self):
        """Class imbalance should cause macro < micro.

        Column 1: tiny column, 1 true label, pred wrong (hurts macro)
        Column 2-4: big columns, 10 labels each, all perfect (hurts nobody)

        Micro sees 1 miss out of 31 total labels → ~high.
        Macro sees "class A" with 0% recall dragging down average.
        """
        big = [f"L{i}" for i in range(10)]
        rows = [
            ColumnResult("c1", ["WRONG"], ["A"]),  # false positive + false negative
            ColumnResult("c2", big, big),
            ColumnResult("c3", big, big),
            ColumnResult("c4", big, big),
        ]
        report = aggregate_multi_label(rows)
        assert report["macro_f1"] < report["micro_f1"], (
            "macro should be dragged down by the failing class A "
            "while micro is anchored by the 30 perfect labels in c2-c4"
        )

    def test_per_class_diagnostic_structure(self):
        rows = [
            ColumnResult("c1", ["EMAIL", "PHONE"], ["EMAIL", "PERSON"]),
            ColumnResult("c2", ["EMAIL"], ["EMAIL"]),
        ]
        report = aggregate_multi_label(rows)
        pc = report["per_class"]
        # EMAIL: appears 2x in pred, 2x in true, all correct → P=R=F1=1.0
        assert pc["EMAIL"]["tp"] == 2
        assert pc["EMAIL"]["fp"] == 0
        assert pc["EMAIL"]["fn"] == 0
        assert pc["EMAIL"]["f1"] == 1.0
        # PHONE: predicted in c1 but never true → pure FP
        assert pc["PHONE"]["tp"] == 0
        assert pc["PHONE"]["fp"] == 1
        assert pc["PHONE"]["fn"] == 0
        # PERSON: true in c1 but never predicted → pure FN
        assert pc["PERSON"]["tp"] == 0
        assert pc["PERSON"]["fp"] == 0
        assert pc["PERSON"]["fn"] == 1

    def test_explicit_label_space_affects_hamming_only(self):
        """Passing an explicit universe should change hamming_loss but
        not any precision/recall/F1 quantity (those depend only on what
        actually appeared in pred ∪ true)."""
        rows = [ColumnResult("c1", ["A"], ["B"])]
        narrow = aggregate_multi_label(rows)
        wide = aggregate_multi_label(rows, label_space=["A", "B", "C", "D", "E"])
        assert narrow["jaccard_macro"] == wide["jaccard_macro"]
        assert narrow["micro_f1"] == wide["micro_f1"]
        # Hamming: narrow universe={A,B}, disagreement on both → 1.0.
        # Wide universe={A,B,C,D,E}, disagreement only on A and B → 2/5.
        assert narrow["hamming_loss"] == 1.0
        assert wide["hamming_loss"] == pytest.approx(2 / 5)


# --------------------------------------------------------------------------- #
# Label support diagnostic
# --------------------------------------------------------------------------- #


class TestLabelSupport:
    def test_counts_ground_truth_only(self):
        """Support counts *true* occurrences, not pred. A class that's
        only ever predicted (never labeled) has support=0 — which is
        exactly what a caller who wants to drop low-support classes
        needs to see."""
        rows = [
            ColumnResult("c1", ["PHONE"], ["EMAIL"]),  # PHONE in pred only
            ColumnResult("c2", ["EMAIL"], ["EMAIL"]),
        ]
        support = collect_label_support(rows)
        assert support["EMAIL"] == 2
        assert support["PHONE"] == 0  # never in ground truth


# --------------------------------------------------------------------------- #
# Invariants — these catch refactors that silently break the contract
# --------------------------------------------------------------------------- #


class TestInvariants:
    @pytest.mark.parametrize(
        ("pred", "true"),
        [
            ([], []),
            (["A"], ["A"]),
            (["A", "B"], ["B", "C"]),
            (["A"], ["B"]),
            (["A", "B", "C"], ["A"]),
        ],
    )
    def test_jaccard_symmetric(self, pred, true):
        """Jaccard is symmetric by definition — if this ever fails, the
        helper has gotten confused about pred vs true ordering."""
        assert jaccard(pred, true) == jaccard(true, pred)

    @pytest.mark.parametrize(
        ("pred", "true"),
        [
            (["A"], ["A"]),
            (["A", "B"], ["B", "C"]),
            (["A", "B", "C"], ["A"]),
        ],
    )
    def test_f1_between_zero_and_one(self, pred, true):
        val = f1(pred, true)
        assert 0.0 <= val <= 1.0 and not math.isnan(val)

    @pytest.mark.parametrize(
        ("pred", "true"),
        [
            ([], ["A"]),
            (["A"], []),
            (["A", "B"], ["B"]),
        ],
    )
    def test_jaccard_bounded(self, pred, true):
        val = jaccard(pred, true)
        assert 0.0 <= val <= 1.0
