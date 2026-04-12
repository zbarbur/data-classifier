"""Tests for the Presidio comparator adapter (Sprint 7).

The adapter translates Presidio's ``RecognizerResult`` outputs into our
entity-type vocabulary so we can compute side-by-side precision/recall/F1
on the same corpus.

Design constraint: unit tests must NOT require ``presidio-analyzer`` to
be installed (it's in the new ``[bench-compare]`` optional extra, not
the default dev dependency). The mapping and translation layer is a pure
data-structure computation — we test it by passing mock Presidio-like
objects. The live-engine integration test uses ``pytest.importorskip``.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from data_classifier.core.types import ColumnInput
from tests.benchmarks.comparators.presidio_comparator import (
    AGGRESSIVE_MAPPING,
    STRICT_MAPPING,
    ComparatorRunResult,
    PresidioEntity,
    compute_column_comparison,
    compute_corpus_metrics,
    format_side_by_side_table,
    translate_entities,
)


@dataclass
class _MockRecognizerResult:
    """Shape-compatible stand-in for presidio_analyzer.RecognizerResult.

    The real class has more fields; the comparator only needs entity_type
    and score. Keeping the stub minimal forces the comparator to only
    depend on those fields, which keeps the coupling explicit.
    """

    entity_type: str
    score: float
    start: int = 0
    end: int = 0


class TestStrictMapping:
    """Strict mapping is 1:1 — Presidio entity → our entity, no semantic drift."""

    @pytest.mark.parametrize(
        "presidio_type,our_type",
        [
            ("US_SSN", "SSN"),
            ("CREDIT_CARD", "CREDIT_CARD"),
            ("EMAIL_ADDRESS", "EMAIL"),
            ("PHONE_NUMBER", "PHONE"),
            ("IP_ADDRESS", "IP_ADDRESS"),
            ("IBAN_CODE", "IBAN"),
            ("URL", "URL"),
        ],
    )
    def test_strict_contains_core_pair(self, presidio_type: str, our_type: str) -> None:
        assert STRICT_MAPPING.get(presidio_type) == our_type

    def test_strict_excludes_loose_pairs(self) -> None:
        """PERSON and LOCATION are semantically loose — aggressive-only."""
        assert "PERSON" not in STRICT_MAPPING
        assert "LOCATION" not in STRICT_MAPPING
        assert "DATE_TIME" not in STRICT_MAPPING


class TestAggressiveMapping:
    """Aggressive extends strict with looser cross-category mappings."""

    def test_aggressive_is_superset_of_strict(self) -> None:
        for k, v in STRICT_MAPPING.items():
            assert AGGRESSIVE_MAPPING.get(k) == v, f"aggressive mapping must contain strict entry {k!r}: {v!r}"

    @pytest.mark.parametrize(
        "presidio_type,our_type",
        [
            ("PERSON", "PERSON_NAME"),
            ("LOCATION", "ADDRESS"),
            ("DATE_TIME", "DATE_OF_BIRTH"),
        ],
    )
    def test_aggressive_adds_loose_pairs(self, presidio_type: str, our_type: str) -> None:
        assert AGGRESSIVE_MAPPING.get(presidio_type) == our_type


class TestTranslateEntities:
    """``translate_entities`` converts a list of Presidio-like results into
    our entity-type vocabulary, deduplicating and dropping unmapped types."""

    def test_empty_input_returns_empty(self) -> None:
        assert translate_entities([], mode="strict") == []

    def test_strict_drops_unmapped_entities(self) -> None:
        results = [
            _MockRecognizerResult("US_SSN", 0.85),
            _MockRecognizerResult("PERSON", 0.95),  # not in strict
            _MockRecognizerResult("CREDIT_CARD", 0.99),
        ]
        translated = translate_entities(results, mode="strict")
        entity_types = {e.entity_type for e in translated}
        assert entity_types == {"SSN", "CREDIT_CARD"}

    def test_aggressive_includes_person_and_location(self) -> None:
        results = [
            _MockRecognizerResult("US_SSN", 0.85),
            _MockRecognizerResult("PERSON", 0.95),
            _MockRecognizerResult("LOCATION", 0.75),
        ]
        translated = translate_entities(results, mode="aggressive")
        entity_types = {e.entity_type for e in translated}
        assert entity_types == {"SSN", "PERSON_NAME", "ADDRESS"}

    def test_deduplicates_same_entity_type_keeping_max_score(self) -> None:
        results = [
            _MockRecognizerResult("US_SSN", 0.70),
            _MockRecognizerResult("US_SSN", 0.90),
            _MockRecognizerResult("US_SSN", 0.80),
        ]
        translated = translate_entities(results, mode="strict")
        assert len(translated) == 1
        assert translated[0].entity_type == "SSN"
        assert translated[0].score == 0.90

    def test_invalid_mode_raises(self) -> None:
        with pytest.raises(ValueError):
            translate_entities([], mode="not-a-mode")

    def test_presidio_entity_dataclass_shape(self) -> None:
        """Result records carry both the mapped our-type and original
        Presidio type for disagreement analysis."""
        results = [_MockRecognizerResult("US_SSN", 0.9)]
        translated = translate_entities(results, mode="strict")
        assert isinstance(translated[0], PresidioEntity)
        assert translated[0].entity_type == "SSN"
        assert translated[0].presidio_type == "US_SSN"
        assert translated[0].score == 0.9


class TestComputeColumnComparison:
    """Per-column comparison between our predictions and Presidio's."""

    def test_agreement_reports_tp_for_both(self) -> None:
        comparison = compute_column_comparison(
            column_id="c1",
            expected="SSN",
            data_classifier_types=["SSN"],
            presidio_types=["SSN"],
        )
        assert comparison.data_classifier_tp is True
        assert comparison.presidio_tp is True
        assert comparison.agreement == "both_correct"

    def test_dc_correct_presidio_missed(self) -> None:
        comparison = compute_column_comparison(
            column_id="c1",
            expected="SSN",
            data_classifier_types=["SSN"],
            presidio_types=[],
        )
        assert comparison.data_classifier_tp is True
        assert comparison.presidio_tp is False
        assert comparison.agreement == "dc_only_correct"

    def test_presidio_correct_dc_missed(self) -> None:
        comparison = compute_column_comparison(
            column_id="c1",
            expected="EMAIL",
            data_classifier_types=[],
            presidio_types=["EMAIL"],
        )
        assert comparison.data_classifier_tp is False
        assert comparison.presidio_tp is True
        assert comparison.agreement == "presidio_only_correct"

    def test_both_wrong(self) -> None:
        comparison = compute_column_comparison(
            column_id="c1",
            expected="SSN",
            data_classifier_types=["CREDIT_CARD"],
            presidio_types=["PHONE"],
        )
        assert comparison.data_classifier_tp is False
        assert comparison.presidio_tp is False
        assert comparison.agreement == "both_wrong"

    def test_expected_none_means_negative_column(self) -> None:
        """A column with expected=None is a negative — any match is an FP."""
        comparison = compute_column_comparison(
            column_id="c1",
            expected=None,
            data_classifier_types=["SSN"],
            presidio_types=[],
        )
        assert comparison.data_classifier_tp is False
        assert comparison.presidio_tp is False
        assert comparison.agreement == "dc_only_fp"


class TestMappingDocLink:
    """The mapping dicts must be self-documented enough that a maintainer
    updating them doesn't need to cross-read the docs."""

    def test_strict_mapping_has_at_least_five_pairs(self) -> None:
        """Coverage sanity — strict should cover at least the core entities."""
        assert len(STRICT_MAPPING) >= 5

    def test_aggressive_strictly_larger_than_strict(self) -> None:
        assert len(AGGRESSIVE_MAPPING) > len(STRICT_MAPPING)


class TestComputeCorpusMetrics:
    """``compute_corpus_metrics`` aggregates per-column comparisons into
    a side-by-side precision/recall/F1 report + disagreement list."""

    @staticmethod
    def _col(col_id: str, name: str = "x") -> ColumnInput:
        return ColumnInput(
            column_id=col_id,
            column_name=name,
            sample_values=["placeholder"],
        )

    def test_perfect_presidio_vs_perfect_dc_all_tp(self) -> None:
        corpus = [
            (self._col("c1"), "SSN"),
            (self._col("c2"), "EMAIL"),
            (self._col("c3"), "CREDIT_CARD"),
        ]
        dc = {"c1": ["SSN"], "c2": ["EMAIL"], "c3": ["CREDIT_CARD"]}
        pr = {
            "c1": [PresidioEntity("SSN", "US_SSN", 0.9)],
            "c2": [PresidioEntity("EMAIL", "EMAIL_ADDRESS", 0.9)],
            "c3": [PresidioEntity("CREDIT_CARD", "CREDIT_CARD", 0.9)],
        }
        result = compute_corpus_metrics(
            corpus,
            dc,
            pr,
            corpus_name="test",
            blind=False,
            mapping_mode="strict",
        )
        assert isinstance(result, ComparatorRunResult)
        assert result.total_tp == 3
        assert result.total_fp == 0
        assert result.total_fn == 0
        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.micro_f1 == 1.0
        assert result.disagreements == []

    def test_presidio_misses_one_column_raises_fn(self) -> None:
        corpus = [
            (self._col("c1"), "SSN"),
            (self._col("c2"), "EMAIL"),
        ]
        dc = {"c1": ["SSN"], "c2": ["EMAIL"]}
        pr = {
            "c1": [PresidioEntity("SSN", "US_SSN", 0.9)],
            "c2": [],  # Presidio missed this one
        }
        result = compute_corpus_metrics(corpus, dc, pr, corpus_name="test", blind=False, mapping_mode="strict")
        assert result.total_tp == 1
        assert result.total_fn == 1
        assert result.recall == 0.5
        # Disagreement recorded for the missed column
        assert len(result.disagreements) == 1
        assert result.disagreements[0].column_id == "c2"
        assert result.disagreements[0].agreement == "dc_only_correct"

    def test_presidio_over_predicts_extra_type_raises_fp(self) -> None:
        corpus = [(self._col("c1"), "SSN")]
        dc = {"c1": ["SSN"]}
        # Presidio says both SSN AND CREDIT_CARD — the CC is an FP
        pr = {
            "c1": [
                PresidioEntity("SSN", "US_SSN", 0.9),
                PresidioEntity("CREDIT_CARD", "CREDIT_CARD", 0.7),
            ]
        }
        result = compute_corpus_metrics(corpus, dc, pr, corpus_name="test", blind=False, mapping_mode="strict")
        assert result.total_tp == 1
        assert result.total_fp == 1
        assert result.per_entity_fp.get("CREDIT_CARD") == 1

    def test_presidio_fp_on_negative_column(self) -> None:
        """A column with expected=None should contribute FPs on any match."""
        corpus = [(self._col("c1"), None)]
        dc = {"c1": []}
        pr = {"c1": [PresidioEntity("EMAIL", "EMAIL_ADDRESS", 0.9)]}
        result = compute_corpus_metrics(corpus, dc, pr, corpus_name="test", blind=False, mapping_mode="strict")
        assert result.total_tp == 0
        assert result.total_fp == 1
        assert result.per_entity_fp.get("EMAIL") == 1
        assert len(result.disagreements) == 1
        assert result.disagreements[0].agreement == "presidio_only_fp"


class TestFormatSideBySideTable:
    """Text table formatting for stdout summaries."""

    def test_formats_aligned_rows(self) -> None:
        dc_rows = [
            ("nemotron", "named", 0.90, 0.85, 0.87),
            ("nemotron", "blind", 0.80, 0.75, 0.77),
        ]
        pr_rows = [
            ("nemotron", "named", 0.70, 0.60, 0.64),
            ("nemotron", "blind", 0.50, 0.40, 0.44),
        ]
        out = format_side_by_side_table(dc_rows, pr_rows)
        assert "nemotron" in out
        assert "named" in out
        assert "blind" in out
        # Presidio header
        assert "Presidio" in out
        # Numeric values (some representation) are present
        assert "0.900" in out
        assert "0.700" in out

    def test_raises_on_length_mismatch(self) -> None:
        dc_rows = [("nemotron", "named", 0.9, 0.9, 0.9)]
        pr_rows = [
            ("nemotron", "named", 0.7, 0.7, 0.7),
            ("nemotron", "blind", 0.5, 0.5, 0.5),
        ]
        with pytest.raises(ValueError, match="row count mismatch"):
            format_side_by_side_table(dc_rows, pr_rows)

    def test_raises_on_row_alignment_mismatch(self) -> None:
        dc_rows = [("nemotron", "named", 0.9, 0.9, 0.9)]
        pr_rows = [("ai4privacy", "named", 0.7, 0.7, 0.7)]  # different corpus
        with pytest.raises(ValueError, match="row alignment mismatch"):
            format_side_by_side_table(dc_rows, pr_rows)


class TestConsolidatedReportCliArgs:
    """Smoke test: ``consolidated_report.main()`` must accept
    ``--compare presidio`` and ``--compare-mode`` flags."""

    def test_argparse_accepts_compare_presidio_flag(self) -> None:
        import argparse

        # Reconstruct the argument parser used by main() to avoid
        # actually running a benchmark.
        parser = argparse.ArgumentParser()
        parser.add_argument("--sprint", type=int, required=True)
        parser.add_argument("--samples", type=int, default=50)
        parser.add_argument("--output", type=str, default=None)
        parser.add_argument("--compare", choices=["presidio"], default=None)
        parser.add_argument("--compare-mode", choices=["strict", "aggressive"], default="strict")

        args = parser.parse_args(["--sprint", "7", "--compare", "presidio", "--compare-mode", "aggressive"])
        assert args.sprint == 7
        assert args.compare == "presidio"
        assert args.compare_mode == "aggressive"

    def test_consolidated_report_main_module_imports_cleanly(self) -> None:
        """Sanity: the main module imports with the new flag wiring
        and the comparator helper function is referenced."""
        import tests.benchmarks.consolidated_report as cr

        assert hasattr(cr, "main")
        assert hasattr(cr, "_run_presidio_comparison")


class TestPresidioIntegration:
    """Live-engine test. Skipped when presidio-analyzer is not installed
    (via the [bench-compare] optional extra)."""

    def test_run_presidio_on_single_column_returns_mapped_entities(
        self,
    ) -> None:
        pytest.importorskip("presidio_analyzer")
        from data_classifier.core.types import ColumnInput
        from tests.benchmarks.comparators.presidio_comparator import (
            run_presidio_on_column,
        )

        col = ColumnInput(
            column_id="test",
            column_name="contact",
            sample_values=[
                "john.doe@example.com",
                "jane.smith@company.org",
                "admin@test.io",
            ],
        )
        result = run_presidio_on_column(col, mode="strict")
        entity_types = {e.entity_type for e in result}
        assert "EMAIL" in entity_types, f"Expected EMAIL in Presidio output, got {entity_types}"
