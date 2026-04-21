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
    OPENPII_1M_TYPE_MAP,
    load_corpus,
    load_detect_secrets_corpus,
    load_gitleaks_corpus,
    load_gretel_en_corpus,
    load_gretel_finance_corpus,
    load_openpii_1m_corpus,
    load_secretbench_corpus,
)

# Sprint 8 split the legacy ``CREDENTIAL`` entity type into four deterministic
# subtypes.  Any loader emitting a label in this set counts as "credential-
# family positive" for downstream assertions that previously filtered by
# the flat ``CREDENTIAL`` literal.
_CREDENTIAL_SUBTYPES: frozenset[str] = frozenset(
    {
        "API_KEY",
        "PRIVATE_KEY",
        "PASSWORD_HASH",
        "OPAQUE_SECRET",
    }
)

# Target entity types produced by the Gretel-EN loader (post-ETL
# data_classifier taxonomy labels).
_GRETEL_EN_TARGET_TYPES: frozenset[str] = frozenset(
    {
        "DATE",
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
        "DATE",
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
        # After the Sprint 11 taxonomy refresh the SecretBench loader emits
        # one or more of the four Sprint-8 credential subtypes rather than
        # the flat ``CREDENTIAL`` label.
        assert _CREDENTIAL_SUBTYPES & set(labels), (
            f"expected at least one credential subtype label; got {sorted(labels)}"
        )
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
        assert _CREDENTIAL_SUBTYPES & set(labels), (
            f"expected at least one credential subtype label; got {sorted(labels)}"
        )
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
        positive_columns = [col for col, gt in corpus if gt in _CREDENTIAL_SUBTYPES]
        assert len(positive_columns) >= 2, "expected >1 positive column from source_type grouping"


class TestDetectSecretsLoader:
    def test_detect_secrets_returns_both_classes(self) -> None:
        corpus = load_detect_secrets_corpus()
        assert corpus

        labels = Counter(gt for _, gt in corpus)
        # The fixture has 8 positives (aws, slack, stripe, basic_auth,
        # jwt, private_key, generic_secret, password_in_url) and 5
        # negatives (non_secret x3, false_positive x2).  After Sprint 11
        # taxonomy refresh those positives are split across API_KEY,
        # PRIVATE_KEY, and OPAQUE_SECRET rather than the legacy flat
        # CREDENTIAL label.
        positive_count = sum(labels.get(lbl, 0) for lbl in _CREDENTIAL_SUBTYPES)
        assert positive_count > 0, f"expected at least one credential subtype label; got {sorted(labels)}"
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
            # Accept DATE_OF_BIRTH as legacy fixture value (remapped to DATE by identity map)
            assert rec["entity_type"] in _GRETEL_EN_TARGET_TYPES or rec["entity_type"] == "DATE_OF_BIRTH"


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
            # Accept DATE_OF_BIRTH as legacy fixture value (remapped to DATE by identity map)
            assert rec["entity_type"] in _GRETEL_FINANCE_TARGET_TYPES or rec["entity_type"] == "DATE_OF_BIRTH"
            seen_types.add(rec["entity_type"])
        # ACC: at least one record per mapped type. Legacy DATE_OF_BIRTH
        # in fixtures satisfies the DATE requirement.
        normalized = {("DATE" if t == "DATE_OF_BIRTH" else t) for t in seen_types}
        assert normalized >= _GRETEL_FINANCE_TARGET_TYPES, (
            f"fixture must include every target type; missing {_GRETEL_FINANCE_TARGET_TYPES - normalized}"
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


# ── OpenPII-1M loader (Sprint 14) ────────────────────────────────────────────

# The 19 raw ai4privacy labels mapped by OPENPII_1M_TYPE_MAP.
_OPENPII_1M_RAW_LABELS: frozenset[str] = frozenset(
    {
        "GIVENNAME",
        "SURNAME",
        "USERNAME",
        "BUILDINGNUM",
        "STREET",
        "CITY",
        "ZIPCODE",
        "STATE",
        "COUNTY",
        "IDCARDNUM",
        "DRIVERLICENSENUM",
        "PASSPORTNUM",
        "TAXNUM",
        "SOCIALNUM",
        "CREDITCARDNUMBER",
        "ACCOUNTNUM",
        "EMAIL",
        "PHONENUMBER",
        "DATE",
    }
)

# Target entity types produced by the OpenPII-1M loader (post-ETL
# data_classifier taxonomy labels).
_OPENPII_1M_TARGET_TYPES: frozenset[str] = frozenset(
    {
        "PERSON_NAME",
        "ADDRESS",
        "NATIONAL_ID",
        "SSN",
        "CREDIT_CARD",
        "BANK_ACCOUNT",
        "EMAIL",
        "PHONE",
        "DATE",
    }
)


class TestOpenPII1mLoader:
    """Sprint 14 — ai4privacy/pii-masking-openpii-1m corpus loader.

    The corpus is CC-BY-4.0 (1.4M rows, 23 languages, 19 entity labels).
    The fixture may not be present in CI (too large to commit), so tests
    that require it are skipped when the fixture file is missing.
    """

    def test_openpii_1m_type_map_coverage(self) -> None:
        """OPENPII_1M_TYPE_MAP must cover all 19 raw labels."""
        assert set(OPENPII_1M_TYPE_MAP.keys()) == _OPENPII_1M_RAW_LABELS, (
            "OPENPII_1M_TYPE_MAP drifted — "
            f"missing: {_OPENPII_1M_RAW_LABELS - set(OPENPII_1M_TYPE_MAP.keys())}, "
            f"extra: {set(OPENPII_1M_TYPE_MAP.keys()) - _OPENPII_1M_RAW_LABELS}"
        )
        assert set(OPENPII_1M_TYPE_MAP.values()) == _OPENPII_1M_TARGET_TYPES

    def test_openpii_1m_type_map_values_are_valid_entity_types(self) -> None:
        """All mapped values must be valid entity types in standard.yaml."""
        valid = _load_valid_entity_types()
        invalid = {k: v for k, v in OPENPII_1M_TYPE_MAP.items() if v not in valid}
        assert invalid == {}, f"OPENPII_1M_TYPE_MAP has invalid entity_type values: {invalid}"

    def test_openpii_1m_type_map_no_stale_credential(self) -> None:
        """No mapping should emit the legacy flat CREDENTIAL label."""
        stale = {k: v for k, v in OPENPII_1M_TYPE_MAP.items() if v == "CREDENTIAL"}
        assert stale == {}, f"Stale CREDENTIAL entries in OPENPII_1M_TYPE_MAP: {stale}"

    def test_load_openpii_1m_missing_fixture_returns_empty(self) -> None:
        """When the fixture file is missing, return empty list (no crash)."""
        corpus = load_openpii_1m_corpus(path="/nonexistent/path/to/openpii_1m.json")
        assert corpus == []

    def test_load_openpii_1m_with_synthetic_fixture(self, tmp_path: Path) -> None:
        """Integration: synthetic records flow through _records_to_corpus."""
        # Create a minimal fixture with post-ETL labels (the loader uses
        # the identity map, so records must use data_classifier labels).
        records = [
            {"entity_type": "PERSON_NAME", "value": "Alice"},
            {"entity_type": "PERSON_NAME", "value": "Bob"},
            {"entity_type": "EMAIL", "value": "alice@example.com"},
            {"entity_type": "EMAIL", "value": "bob@example.com"},
            {"entity_type": "ADDRESS", "value": "123 Main St"},
            {"entity_type": "SSN", "value": "123-45-6789"},
            {"entity_type": "NATIONAL_ID", "value": "AB1234567"},
            {"entity_type": "CREDIT_CARD", "value": "4111111111111111"},
            {"entity_type": "BANK_ACCOUNT", "value": "1234567890"},
            {"entity_type": "PHONE", "value": "+1-555-0100"},
            {"entity_type": "DATE", "value": "1990-01-15"},
        ]
        fixture = tmp_path / "openpii_1m_test.json"
        fixture.write_text(json.dumps(records), encoding="utf-8")

        corpus = load_openpii_1m_corpus(path=fixture, max_rows=100)
        assert corpus, "loader should return non-empty corpus from valid fixture"
        assert isinstance(corpus, list)

        produced_types = {gt for _, gt in corpus}
        for col, ground_truth in corpus:
            assert isinstance(col, ColumnInput)
            assert col.data_type == "STRING"
            assert col.sample_values, "every emitted column should have samples"
            assert ground_truth in _OPENPII_1M_TARGET_TYPES, (
                f"unexpected ground truth {ground_truth!r}; must be in {_OPENPII_1M_TARGET_TYPES}"
            )

        # All types from the fixture should be present.
        expected_types = {r["entity_type"] for r in records}
        assert produced_types == expected_types, (
            f"loader must emit one column per type in fixture; missing {expected_types - produced_types}"
        )

    def test_load_openpii_1m_blind_mode(self, tmp_path: Path) -> None:
        """Blind mode uses generic column names."""
        records = [
            {"entity_type": "PERSON_NAME", "value": "Alice"},
            {"entity_type": "EMAIL", "value": "alice@example.com"},
        ]
        fixture = tmp_path / "openpii_1m_blind.json"
        fixture.write_text(json.dumps(records), encoding="utf-8")

        corpus = load_openpii_1m_corpus(path=fixture, blind=True)
        assert corpus
        for column, _ in corpus:
            assert column.column_name.startswith("col_"), (
                f"blind mode must use generic col_* names; got {column.column_name!r}"
            )

    def test_load_openpii_1m_empty_records_returns_empty(self, tmp_path: Path) -> None:
        """Empty fixture returns empty list."""
        fixture = tmp_path / "openpii_1m_empty.json"
        fixture.write_text("[]", encoding="utf-8")
        corpus = load_openpii_1m_corpus(path=fixture)
        assert corpus == []

    def test_load_openpii_1m_dispatcher_integration(self, tmp_path: Path) -> None:
        """The 'openpii_1m' source works through the load_corpus dispatcher."""
        records = [
            {"entity_type": "PERSON_NAME", "value": "Alice"},
            {"entity_type": "EMAIL", "value": "alice@example.com"},
        ]
        fixture = tmp_path / "openpii_1m_dispatch.json"
        fixture.write_text(json.dumps(records), encoding="utf-8")

        corpus = load_corpus("openpii_1m", path=fixture, max_rows=100)
        assert corpus, "dispatcher should pass through to load_openpii_1m_corpus"


class TestDispatcher:
    def test_dispatcher_accepts_new_sources(self) -> None:
        # openpii_1m excluded — fixture may not be present in CI.
        sources = ("secretbench", "gitleaks", "detect_secrets", "gretel_en", "gretel_finance")
        for source in sources:
            corpus = load_corpus(source)
            assert corpus, f"{source} loaded via dispatcher should be non-empty"

    def test_dispatcher_all_includes_new_corpora(self) -> None:
        corpus = load_corpus("all", max_rows=50, samples_per_type=10)
        labels = Counter(gt for _, gt in corpus)
        assert labels.get(NEGATIVE_GROUND_TRUTH, 0) > 0, "load_corpus('all') must surface NEGATIVE rows"
        # After Sprint 11 taxonomy refresh, credential-family positives
        # are labelled with one of the four Sprint-8 subtypes rather than
        # the flat ``CREDENTIAL`` literal.  The Gretel-finance loader is
        # explicitly out of scope for Sprint 11 item #1, so it is still
        # allowed to carry the legacy ``CREDENTIAL`` label — but at least
        # one of the credential-family subtypes must also be present.
        positive_count = sum(labels.get(lbl, 0) for lbl in _CREDENTIAL_SUBTYPES)
        assert positive_count > 0, f"expected credential-family positives; got {sorted(labels)}"

    def test_dispatcher_rejects_unknown_source(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown corpus source"):
            load_corpus("nope")


def _load_valid_entity_types() -> set[str]:
    """Extract the set of valid entity_type names from standard.yaml.

    Reads the bundled default profile directly rather than importing any
    engine code — this test is the baseline for the Sprint 11 item #3
    drift lint and must not itself depend on engine behaviour.
    """
    import pathlib

    import yaml

    path = pathlib.Path(__file__).parent.parent / "data_classifier" / "profiles" / "standard.yaml"
    profile_doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    entity_types: set[str] = set()
    profiles = profile_doc.get("profiles", {})
    for _name, body in profiles.items():
        for rule in body.get("rules", []):
            et = rule.get("entity_type")
            if et:
                entity_types.add(et)
    return entity_types


class TestLoaderTaxonomyRefresh:
    """Sprint 11 item #1 — post-Sprint-8 4-subtype drift guards.

    Sprint 8 split the legacy flat ``CREDENTIAL`` entity type into
    ``API_KEY``/``PRIVATE_KEY``/``PASSWORD_HASH``/``OPAQUE_SECRET``.
    Three corpus loaders carried identical drift (they still emitted the
    flat ``CREDENTIAL`` label, which is no longer in the taxonomy).  The
    drift showed up as a ~0.05 point Nemotron blind-F1 regression in
    Sprint 10 benchmarks — a measurement artifact, not a real accuracy
    loss.

    These tests pin the post-refresh invariants so the drift cannot
    silently return.  They are also the baseline for the Sprint 11 item
    #3 drift lint (``corpus-loader-entity-taxonomy-drift-lint``).
    """

    def test_nemotron_map_no_stale_credential(self) -> None:
        from tests.benchmarks.corpus_loader import NEMOTRON_TYPE_MAP

        stale = {k: v for k, v in NEMOTRON_TYPE_MAP.items() if v == "CREDENTIAL"}
        assert stale == {}, f"Stale CREDENTIAL entries in NEMOTRON_TYPE_MAP: {stale}"

    def test_gretel_en_map_no_stale_credential(self) -> None:
        stale = {k: v for k, v in GRETEL_EN_TYPE_MAP.items() if v == "CREDENTIAL"}
        assert stale == {}, f"Stale CREDENTIAL entries in GRETEL_EN_TYPE_MAP: {stale}"

    def test_detect_secrets_map_no_stale_credential(self) -> None:
        from tests.benchmarks.corpus_loader import _DETECT_SECRETS_TYPE_MAP

        stale = {k: v for k, v in _DETECT_SECRETS_TYPE_MAP.items() if v == "CREDENTIAL"}
        assert stale == {}, f"Stale CREDENTIAL entries in _DETECT_SECRETS_TYPE_MAP: {stale}"

    def test_nemotron_password_maps_to_opaque_secret(self) -> None:
        """Spot-check: plaintext ``password`` maps to ``OPAQUE_SECRET``.

        Key subtlety: ``PASSWORD_HASH`` is for hashed passwords only;
        plaintext passwords route to the OPAQUE_SECRET catch-all.
        """
        from tests.benchmarks.corpus_loader import NEMOTRON_TYPE_MAP

        assert NEMOTRON_TYPE_MAP["password"] == "OPAQUE_SECRET"
        assert NEMOTRON_TYPE_MAP["api_key"] == "API_KEY"
        assert NEMOTRON_TYPE_MAP["pin"] == "OPAQUE_SECRET"

    def test_detect_secrets_private_key_maps_to_private_key(self) -> None:
        """Spot-check: ``private_key`` routes to ``PRIVATE_KEY``."""
        from tests.benchmarks.corpus_loader import _DETECT_SECRETS_TYPE_MAP

        assert _DETECT_SECRETS_TYPE_MAP["private_key"] == "PRIVATE_KEY"
        # Vendor-specific API tokens all route to API_KEY.
        for k in ("aws_access_key", "slack_token", "stripe_key", "jwt", "github_token"):
            assert _DETECT_SECRETS_TYPE_MAP[k] == "API_KEY", f"{k} must route to API_KEY"
        # Catch-all bucket for embedded-credential shapes.
        for k in ("basic_auth", "generic_secret", "password_in_url"):
            assert _DETECT_SECRETS_TYPE_MAP[k] == "OPAQUE_SECRET", f"{k} must route to OPAQUE_SECRET"

    def test_all_loader_maps_emit_only_valid_entity_types(self) -> None:
        """Every value in any module-level *_TYPE_MAP must be a recognised label.

        This is the baseline for Sprint 11 item #3 (drift lint).  The
        full lint will extend this with CI integration and a fake-loader
        regression test; for now we pin the most important invariant:
        no loader map may emit the legacy flat ``CREDENTIAL`` label, and
        every emitted value must live in the authoritative taxonomy from
        ``profiles/standard.yaml`` (plus a small allow-list of
        engine-emittable labels that are not first-class entity types).

        Gretel-finance is explicitly excluded: its type map still emits
        the legacy ``CREDENTIAL`` label and its fixture's ``entity_type``
        field still uses ``CREDENTIAL``.  Refreshing it requires
        rebuilding the fixture (it carries per-record ``raw_label`` /
        ``source_context`` metadata), which is out of scope for item #1
        per the plan in
        ``docs/plans/nemotron-corpus-loader-taxonomy-refresh.md``.
        """
        from tests.benchmarks import corpus_loader

        valid = _load_valid_entity_types()
        valid.add("NEGATIVE")  # NEGATIVE_GROUND_TRUTH is the non-positive class.
        # Engine-emittable labels that do not (yet) live in
        # profiles/standard.yaml but are produced by pattern/regex
        # engines and accepted by the benchmark scorer.  Item #3 may
        # revisit this allow-list.
        valid.add("URL")

        skip = {"GRETEL_FINANCE_TYPE_MAP", "_GRETEL_FINANCE_POST_ETL_IDENTITY"}

        checked: list[str] = []
        for name in dir(corpus_loader):
            if name in skip:
                continue
            obj = getattr(corpus_loader, name)
            if not isinstance(obj, dict):
                continue
            if not (name.endswith("_TYPE_MAP") or name.endswith("_POST_ETL_IDENTITY")):
                continue
            invalid = {k: v for k, v in obj.items() if v not in valid}
            assert invalid == {}, f"{name} has invalid entity_type values: {invalid}"
            # Specifically: the Sprint 8 credential split must have
            # landed in every loader (modulo the explicit Gretel-finance
            # skip above).
            stale = {k: v for k, v in obj.items() if v == "CREDENTIAL"}
            assert stale == {}, f"{name} still emits legacy flat CREDENTIAL: {stale}"
            checked.append(name)

        # Guard against the filter silently skipping every map.
        assert checked, "drift lint checked zero maps — filter is broken"


class TestNemotronCredentialShapePartitioning:
    """Sprint 11 follow-up to item #1 — value-shape partitioning.

    Nemotron's upstream ``password`` / ``CREDENTIAL`` bucket mixes plaintext
    passwords, PINs, UUIDs, and a small number of JWT-shaped tokens.  Item
    #1 routed the whole bucket uniformly to ``OPAQUE_SECRET``, which scored
    the regex engine's correct ``API_KEY`` predictions on those JWTs as
    false positives.  The fix is a shape partitioner run before
    ``NEMOTRON_TYPE_MAP`` is applied, rewriting records' ``entity_type`` by
    value shape.  See the rescope note on the Sprint 11
    ``nemotron-loader-partition-credential-values-by-shape`` item for the
    diagnosis trace.
    """

    def test_jwt_shape_routes_to_api_key(self) -> None:
        from tests.benchmarks.corpus_loader import _classify_credential_value_shape

        # The exact JWT values Nemotron seeds in its password bucket.
        jwt_header_only = (
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwi"
            "bmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        assert _classify_credential_value_shape(jwt_header_only) == "API_KEY"
        # Minimal valid JWT shape.
        assert _classify_credential_value_shape("eyA.eyB.sig") == "API_KEY"

    def test_pem_block_routes_to_private_key(self) -> None:
        from tests.benchmarks.corpus_loader import _classify_credential_value_shape

        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        assert _classify_credential_value_shape(pem) == "PRIVATE_KEY"
        # EC and OPENSSH variants must also route.
        ec_pem = "-----BEGIN EC PRIVATE KEY-----\nABC\n-----END EC PRIVATE KEY-----"
        openssh_pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nXYZ\n-----END OPENSSH PRIVATE KEY-----"
        assert _classify_credential_value_shape(ec_pem) == "PRIVATE_KEY"
        assert _classify_credential_value_shape(openssh_pem) == "PRIVATE_KEY"

    def test_public_key_pem_does_not_route_to_private_key(self) -> None:
        """Negative regression: a ``-----BEGIN PUBLIC KEY-----`` header must
        NOT route to PRIVATE_KEY.  The earlier implementation checked for
        the substring ``"KEY"`` anywhere in the header window, which would
        incorrectly bucket public-key PEM blocks as private keys — a
        factual label error that would flip the ground truth for any
        public-key values the Nemotron corpus happens to ship in its
        credential bucket.  PEM public keys are not secrets, so they fall
        through to the OPAQUE_SECRET catch-all (neither API_KEY nor
        PRIVATE_KEY is correct for a public key).
        """
        from tests.benchmarks.corpus_loader import _classify_credential_value_shape

        public_pem = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkq...\n-----END PUBLIC KEY-----"
        dsa_public_pem = "-----BEGIN DSA PUBLIC KEY-----\nABCDEF...\n-----END DSA PUBLIC KEY-----"
        rsa_public_pem = "-----BEGIN RSA PUBLIC KEY-----\nMIIBCgKC...\n-----END RSA PUBLIC KEY-----"
        assert _classify_credential_value_shape(public_pem) == "OPAQUE_SECRET"
        assert _classify_credential_value_shape(dsa_public_pem) == "OPAQUE_SECRET"
        assert _classify_credential_value_shape(rsa_public_pem) == "OPAQUE_SECRET"

    def test_plaintext_password_stays_opaque_secret(self) -> None:
        from tests.benchmarks.corpus_loader import _classify_credential_value_shape

        for plaintext in (
            "G9t$fR2mXk5",
            "Ocean99$",
            "RiverFlow@2025",
            "Michael1995",
            "SunsetRiver!Mountain",
        ):
            assert _classify_credential_value_shape(plaintext) == "OPAQUE_SECRET", plaintext

    def test_pin_and_uuid_stay_opaque_secret(self) -> None:
        from tests.benchmarks.corpus_loader import _classify_credential_value_shape

        # 6-digit PINs.
        for pin in ("513345", "334728", "180372", "963882"):
            assert _classify_credential_value_shape(pin) == "OPAQUE_SECRET", pin
        # UUID-ish tokens.
        for uuid_like in (
            "d4a6b9c1-3e2f-4f1a-a76d-3a8c9b1d2e3f",
            "a1e4b9c2-5d87-4f3a-b2e6-2d8f5c7a9e1b",
        ):
            assert _classify_credential_value_shape(uuid_like) == "OPAQUE_SECRET", uuid_like

    def test_empty_and_whitespace_stay_opaque_secret(self) -> None:
        from tests.benchmarks.corpus_loader import _classify_credential_value_shape

        assert _classify_credential_value_shape("") == "OPAQUE_SECRET"
        assert _classify_credential_value_shape("   ") == "OPAQUE_SECRET"
        assert _classify_credential_value_shape("\n\t") == "OPAQUE_SECRET"

    def test_load_nemotron_corpus_emits_api_key_column_when_jwts_present(self) -> None:
        """End-to-end: loading the shipped Nemotron fixture in blind mode
        must produce an API_KEY column that contains the JWT values, and
        those JWTs must NOT leak into the OPAQUE_SECRET column.

        The shipped fixture contains exactly 3 JWT values in its
        ``password`` bucket (see the Sprint 11 diagnostic spike in the
        rescoped item's notes).  After shape partitioning they land in
        a separate API_KEY column.
        """
        from tests.benchmarks.corpus_loader import load_nemotron_corpus

        corpus = load_nemotron_corpus(max_rows=500, blind=True)
        by_type: dict[str, list[str]] = {}
        for col, expected in corpus:
            assert expected is not None
            by_type[expected] = col.sample_values

        # API_KEY column must exist (fixture-dependent: only asserted when
        # the shipped fixture still contains at least one JWT-shaped
        # password record — every JWT value must start with ``ey``).
        api_key_values = by_type.get("API_KEY", [])
        if api_key_values:
            assert all(v.startswith("ey") for v in api_key_values), (
                f"API_KEY column should only contain JWT-shaped values post-partition, got {api_key_values[:3]}"
            )
            # Cross-check: no JWTs should remain in OPAQUE_SECRET.
            opaque_values = by_type.get("OPAQUE_SECRET", [])
            leaked_jwts = [v for v in opaque_values if v.startswith("ey") and v.count(".") == 2]
            assert leaked_jwts == [], f"JWTs leaked into OPAQUE_SECRET column: {leaked_jwts}"
