"""Tests for the meta-classifier shard builder.

Currently focused on the Sprint 18 fail-loud guards
(``MIN_SHARDS_PER_CORPUS`` aggregator + ``REQUIRED_FIXTURES`` preflight).
The end-to-end build is exercised by the family-accuracy benchmark; this
test module specifically targets the failure modes those guards prevent.
"""

from __future__ import annotations

import pytest

from tests.benchmarks.meta_classifier import shard_builder
from tests.benchmarks.meta_classifier.shard_builder import (
    MIN_SHARDS_PER_CORPUS,
    ShardSpec,
    _assert_per_corpus_minimums,
    build_shards,
)

# ── Sprint 18: per-corpus minimum-shard assertion ────────────────────────


class TestPerCorpusMinimumAssertion:
    """``build_shards`` must raise when any registered corpus undershoots
    its minimum, with one aggregate error listing every deficit.
    """

    @staticmethod
    def _make_shard(corpus: str, idx: int) -> ShardSpec:
        from data_classifier.core.types import ColumnInput

        return ShardSpec(
            column=ColumnInput(
                column_name=f"col_{idx}",
                column_id=f"{corpus}_blind_test_shard{idx}",
                data_type="STRING",
                sample_values=["x"],
            ),
            ground_truth="EMAIL",
            corpus=corpus,
            mode="blind",
            source="real",
            shard_index=idx,
            column_id=f"{corpus}_blind_test_shard{idx}",
        )

    def test_passes_when_every_corpus_meets_minimum(self) -> None:
        shards: list[ShardSpec] = []
        for corpus, minimum in MIN_SHARDS_PER_CORPUS.items():
            for k in range(minimum):
                shards.append(self._make_shard(corpus, k))
        _assert_per_corpus_minimums(shards)

    def test_raises_when_one_corpus_undershoots(self) -> None:
        shards: list[ShardSpec] = []
        for corpus, minimum in MIN_SHARDS_PER_CORPUS.items():
            count = minimum - 1 if corpus == "nemotron" else minimum
            for k in range(count):
                shards.append(self._make_shard(corpus, k))
        with pytest.raises(AssertionError) as excinfo:
            _assert_per_corpus_minimums(shards)
        msg = str(excinfo.value)
        assert "nemotron" in msg
        assert f"expected ≥{MIN_SHARDS_PER_CORPUS['nemotron']}" in msg
        assert f"got {MIN_SHARDS_PER_CORPUS['nemotron'] - 1}" in msg
        assert "dvc pull" in msg, "Error must point at the regen command"

    def test_raises_listing_every_missing_corpus(self) -> None:
        shards = [self._make_shard("nemotron", k) for k in range(MIN_SHARDS_PER_CORPUS["nemotron"])]
        with pytest.raises(AssertionError) as excinfo:
            _assert_per_corpus_minimums(shards)
        msg = str(excinfo.value)
        for corpus in MIN_SHARDS_PER_CORPUS:
            if corpus == "nemotron":
                continue
            assert corpus in msg, f"Aggregate error must list missing corpus: {corpus}"
        assert "for 7 corpus/corpora" in msg

    def test_zero_count_appears_in_error(self) -> None:
        shards = [self._make_shard("nemotron", k) for k in range(MIN_SHARDS_PER_CORPUS["nemotron"])]
        with pytest.raises(AssertionError) as excinfo:
            _assert_per_corpus_minimums(shards)
        msg = str(excinfo.value)
        assert "got 0" in msg, "Missing corpus must surface as got=0, not absent from the error"


class TestBuildShardsAggregator:
    """End-to-end aggregator behaviour: build_shards triggers the
    minimum-count check after the unique-id invariant.
    """

    def test_build_shards_passes_with_full_fixture_set(self) -> None:
        """Healthy fixture set produces a valid build (smoke test)."""
        shards = build_shards()
        assert shards, "build_shards must emit shards on a healthy fixture set"

    def test_build_shards_raises_when_pool_is_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stub one PII pool function to {} and assert the aggregator
        catches the resulting deficit.  This simulates a fixture that
        loads (file present) but produces no usable rows after filters
        (e.g. all-Luhn-failing CC corpus, language-filter mismatch).
        """
        monkeypatch.setattr(shard_builder, "_nemotron_pool", lambda: {})
        with pytest.raises(AssertionError) as excinfo:
            build_shards()
        msg = str(excinfo.value)
        assert "nemotron" in msg
        assert f"expected ≥{MIN_SHARDS_PER_CORPUS['nemotron']}" in msg


class TestMinShardsPerCorpusRegistry:
    """Structural drift guard: every corpus that ``build_shards`` emits
    must have a registered minimum (otherwise the floor check skips it).
    """

    def test_registry_covers_every_emitted_corpus(self) -> None:
        shards = build_shards()
        emitted_corpora = {s.corpus for s in shards}
        registered = set(MIN_SHARDS_PER_CORPUS)
        missing = emitted_corpora - registered
        assert not missing, (
            f"Corpora emitted by build_shards but missing from MIN_SHARDS_PER_CORPUS: {sorted(missing)}. "
            "Add a minimum to the registry so the fail-loud aggregator covers it."
        )
