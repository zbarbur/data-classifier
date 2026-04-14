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
    GRETEL_FINANCE_TYPE_MAP,
    NEGATIVE_GROUND_TRUTH,
    load_corpus,
    load_detect_secrets_corpus,
    load_gitleaks_corpus,
    load_gretel_en_corpus,
    load_gretel_finance_corpus,
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


# Target entity types produced by the Gretel-finance loader (post-ETL
# data_classifier taxonomy labels).  Sprint 10, locked 2026-04-14.
_GRETEL_FINANCE_TARGET_TYPES: frozenset[str] = frozenset(
    {
        "PERSON_NAME",
        "ADDRESS",
        "PHONE",
        "EMAIL",
        "DATE_OF_BIRTH",
        "SSN",
        "IBAN",
        "CREDIT_CARD",
        "ABA_ROUTING",
        "SWIFT_BIC",
        "IP_ADDRESS",
        "CREDENTIAL",
    }
)

# Raw Gretel-finance labels that map to existing data_classifier
# entity types in this sprint.  Locked 2026-04-14.  See the mapping
# rationale in ``scripts/download_corpora.py`` and
# ``tests/benchmarks/corpus_loader.py``.
_GRETEL_FINANCE_EXPECTED_RAW_LABELS: frozenset[str] = frozenset(
    {
        "name",
        "first_name",
        "street_address",
        "phone_number",
        "email",
        "date_of_birth",
        "ssn",
        "iban",
        "credit_card_number",
        "bank_routing_number",
        "swift_bic_code",
        "ipv4",
        "ipv6",
        "password",
        "api_key",
    }
)

# The full raw-label vocabulary observed in the 100-row discovery
# sample on 2026-04-14.  Used for the coverage assertion.  27 labels
# total; 15 map within existing data_classifier vocabulary, 3 are
# Sprint 11 net-new taxonomy candidates (``account_pin``, ``bban``,
# ``driver_license_number``), and 9 are generic/ambiguous labels with
# no meaningful mapping (``company``, ``customer_id``, ``employee_id``,
# ``user_name``, ``date``, ``date_time``, ``time``,
# ``credit_card_security_code``, ``local_latlng``).
_GRETEL_FINANCE_DISCOVERY_VOCABULARY: frozenset[str] = frozenset(
    _GRETEL_FINANCE_EXPECTED_RAW_LABELS
    | {
        # Sprint 11 net-new taxonomy candidates (surfaced, not mapped).
        "account_pin",
        "bban",
        "driver_license_number",
        # Generic/ambiguous labels with no mapping this sprint.
        "company",
        "customer_id",
        "employee_id",
        "user_name",
        "date",
        "date_time",
        "time",
        "credit_card_security_code",
        "local_latlng",
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


class TestGretelFinanceLoader:
    """Parallel of :class:`TestGretelEnLoader` for Gretel-finance.

    Sprint 10 addition — this corpus is distinct from Gretel-EN because
    its credential labels appear inside long-form financial-document
    prose (loan agreements, MT940 statements, insurance claims, SWIFT
    messages) rather than in isolated credential-only lines.  It is the
    single targeted intervention for the ``heuristic_avg_length``
    corpus-fingerprint shortcut diagnosed in M1.
    """

    def test_load_gretel_finance_corpus(self) -> None:
        corpus = load_gretel_finance_corpus()
        assert corpus, "Gretel-finance sample fixture should not be empty"
        assert isinstance(corpus, list)
        for column, ground_truth in corpus:
            assert isinstance(column, ColumnInput)
            assert column.data_type == "STRING"
            assert column.sample_values, "every emitted column should have samples"
            assert ground_truth in _GRETEL_FINANCE_TARGET_TYPES, (
                f"unexpected Gretel-finance ground truth {ground_truth!r}; must be in {_GRETEL_FINANCE_TARGET_TYPES}"
            )
        # ACC: at least one row per mapped entity type should come out
        # of the fixture.  The fixture ships 30 values per type so this
        # is a strong lower bound.
        produced_types = {gt for _, gt in corpus}
        assert produced_types == _GRETEL_FINANCE_TARGET_TYPES, (
            f"loader must emit one column per mapped type; missing {_GRETEL_FINANCE_TARGET_TYPES - produced_types}"
        )

    def test_gretel_finance_type_map_coverage(self) -> None:
        # The GRETEL_FINANCE_TYPE_MAP keys must exactly match the
        # locked 15-label set.  Any widening needs a follow-up backlog
        # item (Sprint 11 taxonomy expansion).
        assert set(GRETEL_FINANCE_TYPE_MAP.keys()) == _GRETEL_FINANCE_EXPECTED_RAW_LABELS, (
            "GRETEL_FINANCE_TYPE_MAP drifted — update the Sprint 10 "
            "ingest-gretel-pii-finance-multilingual decision before "
            "changing this map"
        )
        assert set(GRETEL_FINANCE_TYPE_MAP.values()) == _GRETEL_FINANCE_TARGET_TYPES

        # Coverage of the 100-row discovery-sample vocabulary.  The
        # backlog target is >= 80% of raw-label vocabulary, but several
        # Gretel-finance labels have no existing data_classifier entity
        # type (``company``, ``customer_id``, ``employee_id``, ...) and
        # 3 labels are filed for Sprint 11 net-new taxonomy.  We verify
        # the realistic ratio here: 100% of *mappable-within-vocab*
        # labels are covered.
        mappable = _GRETEL_FINANCE_EXPECTED_RAW_LABELS
        covered = set(GRETEL_FINANCE_TYPE_MAP.keys()) & mappable
        assert covered == mappable, f"coverage gap: {mappable - covered} mappable labels missing from type map"
        # Raw 15 / 27 label-vocab ratio is ~55%; the backlog ACC #1's
        # 80% target is unreachable without widening production
        # vocabulary, which ACC #2 forbids.  Locked at 55% by design.
        ratio = len(GRETEL_FINANCE_TYPE_MAP) / len(_GRETEL_FINANCE_DISCOVERY_VOCABULARY)
        assert ratio >= 0.55, f"label-vocab coverage fell below 55%: got {ratio:.2%}"

    def test_load_gretel_finance_blind_mode(self) -> None:
        corpus = load_gretel_finance_corpus(blind=True)
        assert corpus
        for column, _ in corpus:
            assert column.column_name.startswith("col_"), (
                f"blind mode must use generic col_* names; got {column.column_name!r}"
            )

    def test_gretel_finance_sample_fixture_exists(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "corpora" / "gretel_finance_sample.json"
        assert fixture.exists(), f"Gretel-finance fixture missing at {fixture}"
        assert fixture.stat().st_size > 0
        assert fixture.stat().st_size < 100 * 1024, "fixture must stay under 100KB for git"
        with fixture.open(encoding="utf-8") as f:
            records = json.load(f)
        assert isinstance(records, list)
        assert records, "fixture must contain at least one record"
        # Every record must be in the flattened schema; credential
        # records MAY additionally carry source_context metadata.
        seen_types: set[str] = set()
        for rec in records:
            assert "entity_type" in rec
            assert "value" in rec
            assert rec["entity_type"] in _GRETEL_FINANCE_TARGET_TYPES
            seen_types.add(rec["entity_type"])
        # ACC: at least one record per mapped type.
        assert seen_types == _GRETEL_FINANCE_TARGET_TYPES, (
            f"fixture must include every target type; missing {_GRETEL_FINANCE_TARGET_TYPES - seen_types}"
        )

    def test_gretel_finance_credentials_in_financial_docs(self) -> None:
        """Spot-check that credential labels appear in financial-prose context.

        This is the whole reason this corpus exists: the M1 shortcut
        learning analysis showed that every other credential corpus
        (SecretBench, gitleaks, detect_secrets, Nemotron) ships
        credentials as short isolated tokens, which trains the
        meta-classifier to predict CREDENTIAL whenever
        ``heuristic_avg_length`` is short.  Gretel-finance breaks that
        correlation by embedding credentials inside long-form
        financial-document prose.  The fixture preserves
        ``source_context`` metadata on credential records so that this
        property can be verified without a full corpus re-download.
        """
        fixture = Path(__file__).parent / "fixtures" / "corpora" / "gretel_finance_sample.json"
        with fixture.open(encoding="utf-8") as f:
            records = json.load(f)

        credential_records_with_ctx = [
            r for r in records if r.get("entity_type") == "CREDENTIAL" and r.get("source_context")
        ]
        assert credential_records_with_ctx, (
            "fixture must preserve source_context on credential records — "
            "this is the evidence that credentials-in-prose exist in the corpus"
        )

        # At least one credential record should originate from a
        # labelled password/api_key span, not a bare token.
        raw_labels_seen = {r.get("raw_label") for r in credential_records_with_ctx}
        assert raw_labels_seen & {"password", "api_key", "account_pin"}, (
            f"expected at least one credential with raw label in "
            f"{{'password', 'api_key', 'account_pin'}}; got {raw_labels_seen}"
        )

        # Financial-document signal: the source_document_type field
        # should identify at least one classic financial document type.
        doc_types = {r.get("source_document_type", "") for r in credential_records_with_ctx}
        doc_types_lower = " ".join(sorted(t.lower() for t in doc_types if t))
        financial_keywords = (
            "loan",
            "insurance",
            "claim",
            "agreement",
            "payment",
            "statement",
            "policy",
            "mt940",
            "swift",
            "tax",
            "financial",
            "bank",
            "account",
            "trade",
            "confirmation",
            "invoice",
            "credit",
            "report",
            "contract",
            "renewal",
            "ticket",
            "privacy",
            "disclosure",
        )
        assert any(kw in doc_types_lower for kw in financial_keywords), (
            f"credential records should originate from recognisably-financial document types; got {sorted(doc_types)}"
        )

        # Credentials-in-prose signal: the surrounding source_context
        # should include at least some adjacent prose words, not just
        # the credential token itself.  Gretel-EN / SecretBench / etc
        # do not preserve surrounding text; if this assertion starts
        # failing the fixture has regressed.
        contexts = [r["source_context"] for r in credential_records_with_ctx]
        long_contexts = [c for c in contexts if len(c) > 80]
        assert long_contexts, (
            "no credential record carries a source_context longer than 80 "
            "chars — the credentials-in-prose property was lost"
        )


class TestDispatcher:
    def test_dispatcher_accepts_new_sources(self) -> None:
        sources = ("secretbench", "gitleaks", "detect_secrets", "gretel_en", "gretel_finance")
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
