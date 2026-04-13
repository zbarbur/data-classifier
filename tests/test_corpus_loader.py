"""Unit tests for benchmark corpus loaders.

Focuses on the three Phase 2 loaders (SecretBench, gitleaks,
detect_secrets) and the ``NEGATIVE`` ground-truth plumbing they emit.
The Nemotron loader remains covered by the end-to-end benchmarks.

Also covers the Sprint 9 Gretel-EN loader (mixed-label corpus), which
replaced a retired 300k-row corpus whose license was verified as
non-OSS; see ``docs/process/LICENSE_AUDIT.md``.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from data_classifier.core.types import ColumnInput
from tests.benchmarks.corpus_loader import (
    GRETEL_EN_TYPE_MAP,
    NEGATIVE_GROUND_TRUTH,
    load_corpus,
    load_detect_secrets_corpus,
    load_gitleaks_corpus,
    load_gretel_en_corpus,
    load_secretbench_corpus,
)

# Target entity types produced by the Gretel-EN loader (post-ETL
# data_classifier taxonomy labels).
_GRETEL_EN_TARGET_TYPES: frozenset[str] = frozenset(
    {
        "DATE_OF_BIRTH",
        "SSN",
        "PERSON_NAME",
        "EMAIL",
        "PHONE",
        "ADDRESS",
        "CREDIT_CARD",
        "ABA_ROUTING",
        "BANK_ACCOUNT",
        "IP_ADDRESS",
        "VIN",
        "HEALTH",
    }
)

# Exact Gretel raw labels pre-locked by the Sprint 9 path-(d) decision.
_GRETEL_EN_EXPECTED_RAW_LABELS: frozenset[str] = frozenset(
    {
        "date_of_birth",
        "ssn",
        "first_name",
        "name",
        "last_name",
        "email",
        "phone_number",
        "address",
        "street_address",
        "credit_card_number",
        "bank_routing_number",
        "account_number",
        "ipv4",
        "ipv6",
        "vehicle_identifier",
        "medical_record_number",
    }
)


class TestSecretBenchLoader:
    def test_secretbench_returns_credential_and_negative_rows(self) -> None:
        corpus = load_secretbench_corpus()
        assert corpus, "SecretBench sample fixture should not be empty"

        labels = Counter(gt for _, gt in corpus)
        assert "CREDENTIAL" in labels
        assert NEGATIVE_GROUND_TRUTH in labels
        # sample is balanced 516 TP / 552 TN
        total_values = sum(len(col.sample_values) for col, _ in corpus)
        assert total_values == 1068

    def test_secretbench_columns_are_column_input(self) -> None:
        corpus = load_secretbench_corpus()
        for column, _ in corpus:
            assert isinstance(column, ColumnInput)
            assert column.data_type == "STRING"
            assert column.sample_values, "every emitted column should have samples"

    def test_secretbench_blind_mode_uses_generic_names(self) -> None:
        corpus = load_secretbench_corpus(blind=True)
        assert corpus
        for column, _ in corpus:
            assert column.column_name.startswith("col_")


class TestGitleaksLoader:
    def test_gitleaks_returns_both_classes(self) -> None:
        corpus = load_gitleaks_corpus()
        assert corpus

        labels = Counter(gt for _, gt in corpus)
        assert "CREDENTIAL" in labels
        assert NEGATIVE_GROUND_TRUTH in labels

        total_values = sum(len(col.sample_values) for col, _ in corpus)
        assert total_values == 171

    def test_gitleaks_preserves_hashicorp_row_as_negative(self) -> None:
        corpus = load_gitleaks_corpus()
        # Hashicorp row ships with is_secret=False so it must land on a
        # NEGATIVE column.  We don't care which column — just that it is
        # reachable and mapped to the negative class.
        negative_values: list[str] = []
        for column, label in corpus:
            if label == NEGATIVE_GROUND_TRUTH:
                negative_values.extend(column.sample_values)
        assert any(".atlasv1." in v for v in negative_values), (
            "hashicorp row (xor-suppression alignment) must land on NEGATIVE"
        )

    def test_gitleaks_source_type_groups_positives(self) -> None:
        # Positive rows should be split across multiple columns, one per
        # source_type (gcp, aws, azure, ...), so that the meta-classifier
        # sees per-vendor KV shapes instead of a monolithic credential
        # bucket.
        corpus = load_gitleaks_corpus()
        positive_columns = [col for col, gt in corpus if gt == "CREDENTIAL"]
        assert len(positive_columns) >= 2, "expected >1 positive column from source_type grouping"


class TestDetectSecretsLoader:
    def test_detect_secrets_returns_both_classes(self) -> None:
        corpus = load_detect_secrets_corpus()
        assert corpus

        labels = Counter(gt for _, gt in corpus)
        # The fixture has 8 positives (aws, slack, stripe, basic_auth,
        # jwt, private_key, generic_secret, password_in_url) and 5
        # negatives (non_secret x3, false_positive x2).
        assert labels.get("CREDENTIAL", 0) > 0
        assert labels.get(NEGATIVE_GROUND_TRUTH, 0) > 0

    def test_detect_secrets_value_count(self) -> None:
        corpus = load_detect_secrets_corpus()
        total = sum(len(col.sample_values) for col, _ in corpus)
        assert total == 13


class TestGretelEnLoader:
    def test_load_gretel_en_corpus(self) -> None:
        corpus = load_gretel_en_corpus()
        assert corpus, "Gretel-EN sample fixture should not be empty"
        assert isinstance(corpus, list)
        for column, ground_truth in corpus:
            assert isinstance(column, ColumnInput)
            assert column.data_type == "STRING"
            assert column.sample_values, "every emitted column should have samples"
            assert ground_truth in _GRETEL_EN_TARGET_TYPES, (
                f"unexpected Gretel-EN ground truth {ground_truth!r}; must be in {_GRETEL_EN_TARGET_TYPES}"
            )

    def test_gretel_en_type_map_coverage(self) -> None:
        # The Sprint 9 path-(d) decision locked exactly 16 raw Gretel
        # labels -> 12 data_classifier targets.  No more, no less: any
        # widening needs a new backlog item (Sprint 10 taxonomy expansion).
        assert set(GRETEL_EN_TYPE_MAP.keys()) == _GRETEL_EN_EXPECTED_RAW_LABELS, (
            "GRETEL_EN_TYPE_MAP drifted — update Sprint 9 backlog doc before changing"
        )
        assert set(GRETEL_EN_TYPE_MAP.values()) == _GRETEL_EN_TARGET_TYPES

    def test_load_gretel_en_blind_mode(self) -> None:
        corpus = load_gretel_en_corpus(blind=True)
        assert corpus
        for column, _ in corpus:
            assert column.column_name.startswith("col_"), (
                f"blind mode must use generic col_* names; got {column.column_name!r}"
            )

    def test_gretel_en_sample_fixture_exists(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "corpora" / "gretel_en_sample.json"
        assert fixture.exists(), f"Gretel-EN fixture missing at {fixture}"
        assert fixture.stat().st_size > 0
        assert fixture.stat().st_size < 100 * 1024, "fixture must stay under 100KB for git"
        with fixture.open(encoding="utf-8") as f:
            records = json.load(f)
        assert isinstance(records, list)
        assert records, "fixture must contain at least one record"
        # Every record must already be in the flattened schema.
        for rec in records:
            assert "entity_type" in rec
            assert "value" in rec
            assert rec["entity_type"] in _GRETEL_EN_TARGET_TYPES


class TestDispatcher:
    def test_dispatcher_accepts_new_sources(self) -> None:
        sources = ("secretbench", "gitleaks", "detect_secrets", "gretel_en")
        for source in sources:
            corpus = load_corpus(source)
            assert corpus, f"{source} loaded via dispatcher should be non-empty"

    def test_dispatcher_all_includes_new_corpora(self) -> None:
        corpus = load_corpus("all", max_rows=50, samples_per_type=10)
        labels = Counter(gt for _, gt in corpus)
        assert labels.get(NEGATIVE_GROUND_TRUTH, 0) > 0, "load_corpus('all') must surface NEGATIVE rows"
        assert labels.get("CREDENTIAL", 0) > 0

    def test_dispatcher_rejects_unknown_source(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown corpus source"):
            load_corpus("nope")
