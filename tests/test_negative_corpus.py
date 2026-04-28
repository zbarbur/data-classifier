"""Tests for the source-diverse NEGATIVE corpus (Sprint 17 item).

Per-source loader smoke tests, determinism check, and the load-bearing
PII-contamination sweep that gates each source against >5% positive hits
from the regex engine. A source that exceeds the threshold is treated
as contaminated and must be fixed in ``negative_corpus.py``.
"""

from __future__ import annotations

import pytest

from data_classifier import classify_columns, load_profile
from data_classifier.core.types import ColumnInput
from tests.benchmarks.negative_corpus import (
    DEFAULT_VALUES_PER_SOURCE,
    NEGATIVE_SOURCE_IDS,
    flatten_negative_corpus,
    load_diverse_negative_corpus,
)

#: Maximum acceptable rate of regex-engine positives per source. Above
#: this, the source is considered contaminated. Calibrated tight at 5%
#: because each NEGATIVE value is intended to be unambiguously not-PII;
#: occasional shape collisions (e.g., a 3-digit count looking like an
#: area code) are tolerated, but anything systematic is a generator bug.
_CONTAMINATION_CEILING = 0.05


@pytest.fixture(scope="module")
def standard_profile_module():
    """Module-scoped profile so the contamination sweep doesn't reload it 5×."""
    return load_profile("standard")


@pytest.fixture(scope="module")
def negative_corpus():
    """Module-scoped: 5 sources × 500 values, generated once per test run."""
    return load_diverse_negative_corpus()


class TestPerSourceLoaders:
    """Each source produces the configured value count with no obvious bugs."""

    @pytest.mark.parametrize("source", NEGATIVE_SOURCE_IDS)
    def test_source_returns_expected_count(self, source: str, negative_corpus) -> None:
        assert source in negative_corpus, f"Source {source!r} missing from corpus"
        assert len(negative_corpus[source]) == DEFAULT_VALUES_PER_SOURCE, (
            f"Source {source!r} produced {len(negative_corpus[source])} values; expected {DEFAULT_VALUES_PER_SOURCE}"
        )

    @pytest.mark.parametrize("source", NEGATIVE_SOURCE_IDS)
    def test_all_values_are_strings(self, source: str, negative_corpus) -> None:
        for value in negative_corpus[source]:
            assert isinstance(value, str), f"Source {source!r} returned non-str value: {value!r} (type {type(value)})"

    @pytest.mark.parametrize("source", NEGATIVE_SOURCE_IDS)
    def test_no_empty_values(self, source: str, negative_corpus) -> None:
        empties = [i for i, v in enumerate(negative_corpus[source]) if not v.strip()]
        assert not empties, f"Source {source!r} produced empty values at indices {empties[:5]}"

    @pytest.mark.parametrize("source", NEGATIVE_SOURCE_IDS)
    def test_reasonable_diversity(self, source: str, negative_corpus) -> None:
        """At least 50% unique values per source — catches degenerate generators."""
        values = negative_corpus[source]
        unique_ratio = len(set(values)) / len(values)
        assert unique_ratio >= 0.5, (
            f"Source {source!r} only {unique_ratio:.0%} unique values — generator may be too narrow"
        )


class TestDeterminism:
    """Same seed must produce same output — required for stable benchmarks."""

    def test_same_seed_same_output(self) -> None:
        a = load_diverse_negative_corpus(seed=42)
        b = load_diverse_negative_corpus(seed=42)
        for source in NEGATIVE_SOURCE_IDS:
            assert a[source] == b[source], f"Source {source!r} not deterministic at seed=42"

    def test_different_seeds_different_output(self) -> None:
        a = load_diverse_negative_corpus(seed=42)
        b = load_diverse_negative_corpus(seed=43)
        # At least one source must differ — sanity check the seed actually flows.
        any_differ = any(a[s] != b[s] for s in NEGATIVE_SOURCE_IDS)
        assert any_differ, "Different seeds produced identical output — seed plumbing broken"


class TestFlatten:
    def test_flatten_preserves_source_attribution(self, negative_corpus) -> None:
        flat = flatten_negative_corpus(negative_corpus)
        assert len(flat) == sum(len(v) for v in negative_corpus.values())
        # Every entry must carry a valid source id.
        for source, _value in flat:
            assert source in NEGATIVE_SOURCE_IDS

    def test_flatten_round_trips(self, negative_corpus) -> None:
        """Source-grouping reconstructs the original dict shape."""
        flat = flatten_negative_corpus(negative_corpus)
        regrouped: dict[str, list[str]] = {s: [] for s in NEGATIVE_SOURCE_IDS}
        for source, value in flat:
            regrouped[source].append(value)
        for source in NEGATIVE_SOURCE_IDS:
            assert regrouped[source] == negative_corpus[source]


class TestPIIContaminationSweep:
    """The load-bearing test: each source must stay below the 5% positive-hit ceiling.

    Failure mode being prevented: a generator that accidentally produces
    PII-shaped values pollutes the NEGATIVE pool. Downstream NEGATIVE-F1
    metrics would then over-credit the detector for "correctly missing"
    things that are actually PII. A source with >5% leak rate is a bug
    in ``negative_corpus.py``, not a tolerable artifact.
    """

    @pytest.mark.parametrize("source", NEGATIVE_SOURCE_IDS)
    def test_source_contamination_below_ceiling(self, source: str, negative_corpus, standard_profile_module) -> None:
        # Sample 100 random values per source — keeps the test fast (~1s) while
        # still giving 5% resolution. The full corpus is exercised by the
        # benchmark itself; this is a per-source unit-level guard.
        import random

        rng = random.Random(20260428)
        values = rng.sample(negative_corpus[source], k=min(100, len(negative_corpus[source])))
        columns = [
            ColumnInput(
                column_id=f"neg-{source}-{i}",
                column_name="value",
                sample_values=[v],
            )
            for i, v in enumerate(values)
        ]
        findings = classify_columns(columns, standard_profile_module, min_confidence=0.3)

        # A column-id that produces any finding above min_confidence is a hit.
        hit_ids = {f.column_id for f in findings}
        hit_rate = len(hit_ids) / len(columns)

        # Surface offending values in the failure message — speeds up
        # debugging when a generator regression slips through.
        if hit_rate > _CONTAMINATION_CEILING:
            offenders = [(f.column_id, f.entity_type, f.confidence) for f in findings[:10]]
            pytest.fail(
                f"Source {source!r}: {hit_rate:.1%} contamination "
                f"(ceiling {_CONTAMINATION_CEILING:.0%}); first offenders: {offenders}"
            )


class TestCombinedCorpusSize:
    def test_total_value_count(self, negative_corpus) -> None:
        total = sum(len(v) for v in negative_corpus.values())
        assert total == DEFAULT_VALUES_PER_SOURCE * len(NEGATIVE_SOURCE_IDS)
        assert total >= 2500  # Sprint 17 spec floor.
