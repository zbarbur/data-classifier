"""Tests for the Column Name Semantics Engine.

Tests cover:
  - Direct matching (exact variant lookup after normalization)
  - Normalization (case insensitive, hyphens, camelCase)
  - Abbreviation expansion (dob, cc, dl, etc.)
  - Multi-token subsequence matching (prefixed column names)
  - No-match cases (generic column names)
  - Confidence levels (direct vs abbreviation vs subsequence)
  - Golden fixture compatibility
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.engines.column_name_engine import ColumnNameEngine, _normalize

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> ColumnNameEngine:
    """Create and start a ColumnNameEngine."""
    e = ColumnNameEngine()
    e.startup()
    return e


def _classify(engine: ColumnNameEngine, name: str) -> list:
    """Helper to classify a column name with default settings."""
    column = ColumnInput(column_name=name, column_id=f"test:{name}")
    return engine.classify_column(column, min_confidence=0.0)


# ── TestDirectMatch ─────────────────────────────────────────────────────────


class TestDirectMatch:
    """Direct variant lookup after normalization."""

    def test_ssn(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "ssn")
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_email_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "email_address")
        assert len(findings) == 1
        assert findings[0].entity_type == "EMAIL"

    def test_credit_card_number(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "credit_card_number")
        assert len(findings) == 1
        assert findings[0].entity_type == "CREDIT_CARD"

    def test_phone_number(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "phone_number")
        assert len(findings) == 1
        assert findings[0].entity_type == "PHONE"

    def test_date_of_birth(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "date_of_birth")
        assert len(findings) == 1
        assert findings[0].entity_type == "DATE_OF_BIRTH"

    def test_password(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "password")
        assert len(findings) == 1
        # Sprint 8 Item 4: password → OPAQUE_SECRET subtype (Credential category)
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].category == "Credential"

    def test_salary(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "salary")
        assert len(findings) == 1
        assert findings[0].entity_type == "FINANCIAL"

    def test_diagnosis(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "diagnosis")
        assert len(findings) == 1
        assert findings[0].entity_type == "HEALTH"

    def test_bank_account(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "bank_account")
        assert len(findings) == 1
        assert findings[0].entity_type == "BANK_ACCOUNT"

    def test_first_name(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "first_name")
        assert len(findings) == 1
        assert findings[0].entity_type == "PERSON_NAME"

    def test_ip_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "ip_address")
        assert len(findings) == 1
        assert findings[0].entity_type == "IP_ADDRESS"

    def test_gender(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "gender")
        assert len(findings) == 1
        assert findings[0].entity_type == "DEMOGRAPHIC"

    def test_age(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "age")
        assert len(findings) == 1
        assert findings[0].entity_type == "AGE"

    def test_passport_number(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "passport_number")
        assert len(findings) == 1
        # passport_number is in NATIONAL_ID variants (first registered wins)
        assert findings[0].entity_type == "NATIONAL_ID"

    def test_street_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "street_address")
        assert len(findings) == 1
        assert findings[0].entity_type == "ADDRESS"

    def test_npi_number(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "npi_number")
        assert len(findings) == 1
        assert findings[0].entity_type == "NPI"

    def test_dea_number(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "dea_number")
        assert len(findings) == 1
        assert findings[0].entity_type == "DEA_NUMBER"

    def test_vin(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "vin")
        assert len(findings) == 1
        assert findings[0].entity_type == "VIN"

    def test_bitcoin_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "bitcoin_address")
        assert len(findings) == 1
        assert findings[0].entity_type == "BITCOIN_ADDRESS"

    def test_ethereum_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "ethereum_address")
        assert len(findings) == 1
        assert findings[0].entity_type == "ETHEREUM_ADDRESS"


# ── TestNormalization ───────────────────────────────────────────────────────


class TestNormalization:
    """Case insensitive, hyphen, camelCase normalization."""

    def test_uppercase(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "CUSTOMER_SSN")
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_hyphens(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "customer-ssn")
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_camel_case(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "CustomerSsn")
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_camel_case_email(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "emailAddress")
        assert len(findings) == 1
        assert findings[0].entity_type == "EMAIL"

    def test_mixed_case_with_underscores(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "Email_Address")
        assert len(findings) == 1
        assert findings[0].entity_type == "EMAIL"

    def test_all_caps_email(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "EMAIL_ADDRESS")
        assert len(findings) == 1
        assert findings[0].entity_type == "EMAIL"

    def test_normalize_function(self) -> None:
        assert _normalize("CustomerSsn") == "customer_ssn"
        assert _normalize("emailAddress") == "email_address"
        assert _normalize("CUSTOMER_SSN") == "customer_ssn"
        assert _normalize("customer-ssn") == "customer_ssn"
        assert _normalize("customer__ssn") == "customer_ssn"
        assert _normalize("_ssn_") == "ssn"
        assert _normalize("dateOfBirth") == "date_of_birth"


# ── TestAbbreviationExpansion ───────────────────────────────────────────────


class TestAbbreviationExpansion:
    """Abbreviation expansion matching."""

    def test_dob(self, engine: ColumnNameEngine) -> None:
        # "dob" is a direct variant in DATE_OF_BIRTH, so it hits direct match
        findings = _classify(engine, "dob")
        assert len(findings) == 1
        assert findings[0].entity_type == "DATE_OF_BIRTH"

    def test_cc_num(self, engine: ColumnNameEngine) -> None:
        # "cc_num" is a direct variant in CREDIT_CARD
        findings = _classify(engine, "cc_num")
        assert len(findings) == 1
        assert findings[0].entity_type == "CREDIT_CARD"

    def test_dl_abbreviation(self, engine: ColumnNameEngine) -> None:
        # "dl" is a direct variant in DRIVERS_LICENSE
        findings = _classify(engine, "dl")
        assert len(findings) == 1
        assert findings[0].entity_type == "DRIVERS_LICENSE"

    def test_pwd(self, engine: ColumnNameEngine) -> None:
        # Sprint 8 Item 4: "pwd" is a direct variant in OPAQUE_SECRET
        findings = _classify(engine, "pwd")
        assert len(findings) == 1
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].category == "Credential"

    def test_fname(self, engine: ColumnNameEngine) -> None:
        # "fname" is a direct variant in PERSON_NAME
        findings = _classify(engine, "fname")
        assert len(findings) == 1
        assert findings[0].entity_type == "PERSON_NAME"

    def test_lname(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "lname")
        assert len(findings) == 1
        assert findings[0].entity_type == "PERSON_NAME"

    def test_addr(self, engine: ColumnNameEngine) -> None:
        # "addr" is a direct variant in ADDRESS (also in abbreviations as fallback)
        findings = _classify(engine, "addr")
        assert len(findings) == 1
        assert findings[0].entity_type == "ADDRESS"

    def test_acct_abbreviation(self, engine: ColumnNameEngine) -> None:
        # "acct" is not a direct variant, expands to "account_number" which is in BANK_ACCOUNT
        findings = _classify(engine, "acct")
        assert len(findings) == 1
        assert findings[0].entity_type == "BANK_ACCOUNT"


# ── TestMultiTokenMatching ──────────────────────────────────────────────────


class TestMultiTokenMatching:
    """Multi-token contiguous subsequence matching."""

    def test_customer_social_security(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "customer_social_security")
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_employee_date_of_birth(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "employee_date_of_birth")
        assert len(findings) == 1
        assert findings[0].entity_type == "DATE_OF_BIRTH"

    def test_user_email(self, engine: ColumnNameEngine) -> None:
        # "user_email" is a direct variant in EMAIL
        findings = _classify(engine, "user_email")
        assert len(findings) == 1
        assert findings[0].entity_type == "EMAIL"

    def test_patient_diagnosis(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "patient_diagnosis")
        assert len(findings) == 1
        assert findings[0].entity_type == "HEALTH"

    def test_employee_salary(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "employee_salary")
        assert len(findings) == 1
        assert findings[0].entity_type == "FINANCIAL"

    def test_customer_ssn(self, engine: ColumnNameEngine) -> None:
        # "customer_ssn" is a direct variant in SSN
        findings = _classify(engine, "customer_ssn")
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_ssn_number(self, engine: ColumnNameEngine) -> None:
        # "ssn_number" is a direct variant in SSN
        findings = _classify(engine, "ssn_number")
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"


# ── TestNoMatch ─────────────────────────────────────────────────────────────


class TestNoMatch:
    """Generic column names should not match."""

    @pytest.mark.parametrize(
        "name",
        [
            "id",
            "value",
            "field1",
            "created_at",
            "status",
            "data",
            "record_id",
            "updated_at",
            "is_active",
            "count",
            "type",
            "feature_flag",
            "amount",
            "quantity",
            "description",
            "notes",
        ],
    )
    def test_no_match(self, engine: ColumnNameEngine, name: str) -> None:
        findings = _classify(engine, name)
        assert len(findings) == 0, f"Column '{name}' should have no findings, got: {[f.entity_type for f in findings]}"


# ── TestConfidenceLevels ────────────────────────────────────────────────────


class TestConfidenceLevels:
    """Confidence scaling by match type."""

    def test_direct_match_full_confidence(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "ssn")
        assert len(findings) == 1
        assert findings[0].confidence == 0.95  # SSN base confidence

    def test_direct_match_email_confidence(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "email")
        assert len(findings) == 1
        assert findings[0].confidence == 0.90  # EMAIL base confidence

    def test_abbreviation_match_reduced_confidence(self, engine: ColumnNameEngine) -> None:
        # "acct" is an abbreviation for "account_number", not a direct variant
        findings = _classify(engine, "acct")
        assert len(findings) == 1
        # BANK_ACCOUNT confidence is 0.90, abbreviation multiplier is 0.95
        assert findings[0].confidence == pytest.approx(0.90 * 0.95, abs=0.01)

    def test_subsequence_match_reduced_confidence(self, engine: ColumnNameEngine) -> None:
        # "employee_salary" — "salary" is a subsequence match
        findings = _classify(engine, "employee_salary")
        assert len(findings) == 1
        # FINANCIAL confidence is 0.85, subsequence multiplier is 0.85
        assert findings[0].confidence == pytest.approx(0.85 * 0.85, abs=0.01)

    def test_direct_higher_than_subsequence(self, engine: ColumnNameEngine) -> None:
        direct = _classify(engine, "salary")
        subseq = _classify(engine, "employee_salary")
        assert direct[0].confidence > subseq[0].confidence


# ── TestEngineMetadata ──────────────────────────────────────────────────────


class TestEngineMetadata:
    """Engine configuration and metadata."""

    def test_engine_name(self) -> None:
        engine = ColumnNameEngine()
        assert engine.name == "column_name"

    def test_engine_order(self) -> None:
        engine = ColumnNameEngine()
        assert engine.order == 1

    def test_supported_modes(self) -> None:
        engine = ColumnNameEngine()
        assert engine.supported_modes == frozenset({"structured"})

    def test_finding_engine_field(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "ssn")
        assert findings[0].engine == "column_name"

    def test_finding_has_evidence(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "ssn")
        assert "SSN" in findings[0].evidence
        assert "ssn" in findings[0].evidence

    def test_lazy_startup(self) -> None:
        """Engine starts lazily on first classify_column call."""
        engine = ColumnNameEngine()
        assert not engine._loaded
        column = ColumnInput(column_name="ssn", column_id="test:ssn")
        engine.classify_column(column, min_confidence=0.0)
        assert engine._loaded


# ── TestGoldenFixtureCompatibility ──────────────────────────────────────────


class TestGoldenFixtureCompatibility:
    """Verify that column name engine produces same entity types as the golden fixtures expect.

    The golden fixtures were built against the regex engine's profile-based column name
    matching. The new column_name engine should produce compatible results for all
    column names in the golden set.
    """

    @pytest.mark.parametrize(
        "column_name,expected_entity_type",
        [
            ("email", "EMAIL"),
            ("ssn", "SSN"),
            ("phone_number", "PHONE"),
            ("date_of_birth", "DATE_OF_BIRTH"),
            ("credit_card_number", "CREDIT_CARD"),
            ("password", "OPAQUE_SECRET"),  # Sprint 8 Item 4: CREDENTIAL split
            ("salary", "FINANCIAL"),
            ("diagnosis", "HEALTH"),
            ("bank_account", "BANK_ACCOUNT"),
            ("first_name", "PERSON_NAME"),
            ("ip_address", "IP_ADDRESS"),
            ("gender", "DEMOGRAPHIC"),
            ("age", "AGE"),
            ("passport_number", "NATIONAL_ID"),
            ("street_address", "ADDRESS"),
            # Case insensitive
            ("EMAIL_ADDRESS", "EMAIL"),
            # Compound names
            ("user_email", "EMAIL"),
            ("ssn_number", "SSN"),
            ("customer_ssn", "SSN"),
        ],
    )
    def test_golden_column_match(self, engine: ColumnNameEngine, column_name: str, expected_entity_type: str) -> None:
        findings = _classify(engine, column_name)
        assert len(findings) >= 1, f"Column '{column_name}' should match {expected_entity_type}"
        assert findings[0].entity_type == expected_entity_type

    @pytest.mark.parametrize(
        "column_name",
        ["id", "record_id", "created_at", "status", "data", "value"],
    )
    def test_golden_no_match(self, engine: ColumnNameEngine, column_name: str) -> None:
        findings = _classify(engine, column_name)
        assert len(findings) == 0, f"Column '{column_name}' should have no match"


# ── TestMinConfidenceFiltering ──────────────────────────────────────────────


class TestMinConfidenceFiltering:
    """Findings below min_confidence should be filtered out."""

    def test_low_confidence_filtered(self, engine: ColumnNameEngine) -> None:
        column = ColumnInput(column_name="ssn", column_id="test:ssn")
        findings = engine.classify_column(column, min_confidence=0.99)
        assert len(findings) == 0

    def test_high_confidence_passes(self, engine: ColumnNameEngine) -> None:
        column = ColumnInput(column_name="ssn", column_id="test:ssn")
        findings = engine.classify_column(column, min_confidence=0.5)
        assert len(findings) == 1


# ── TestCompoundTableMatching ───────────────────────────────────────────────


class TestCompoundTableMatching:
    """Compound matching: table_name provides context boost."""

    def test_employees_ssn_gets_boost(self, engine: ColumnNameEngine) -> None:
        """employees.ssn → SSN with boost vs ssn alone."""
        base = ColumnInput(column_name="ssn", column_id="no_table:ssn")
        boosted = ColumnInput(column_name="ssn", column_id="employees:ssn", table_name="employees")
        base_findings = engine.classify_column(base, min_confidence=0.0)
        boosted_findings = engine.classify_column(boosted, min_confidence=0.0)
        assert len(base_findings) == 1
        assert len(boosted_findings) == 1
        assert boosted_findings[0].entity_type == "SSN"
        assert boosted_findings[0].confidence > base_findings[0].confidence

    def test_patients_mrn_gets_boost(self, engine: ColumnNameEngine) -> None:
        """patients.mrn → MRN with boost vs mrn alone (health context)."""
        base = ColumnInput(column_name="mrn", column_id="no_table:mrn")
        boosted = ColumnInput(column_name="mrn", column_id="patients:mrn", table_name="patients")
        base_findings = engine.classify_column(base, min_confidence=0.0)
        boosted_findings = engine.classify_column(boosted, min_confidence=0.0)
        assert len(base_findings) == 1
        assert len(boosted_findings) == 1
        assert boosted_findings[0].confidence > base_findings[0].confidence

    def test_orders_id_no_boost(self, engine: ColumnNameEngine) -> None:
        """orders.id should produce no findings — 'id' is a no-match column."""
        column = ColumnInput(column_name="id", column_id="orders:id", table_name="orders")
        findings = engine.classify_column(column, min_confidence=0.0)
        assert len(findings) == 0

    def test_non_matching_table_no_boost(self, engine: ColumnNameEngine) -> None:
        """A table with no context keyword should yield unmodified confidence."""
        base = ColumnInput(column_name="ssn", column_id="no_table:ssn")
        no_boost = ColumnInput(column_name="ssn", column_id="widgets:ssn", table_name="widgets")
        base_findings = engine.classify_column(base, min_confidence=0.0)
        no_boost_findings = engine.classify_column(no_boost, min_confidence=0.0)
        assert base_findings[0].confidence == no_boost_findings[0].confidence

    def test_boost_capped_at_1(self, engine: ColumnNameEngine) -> None:
        """Confidence must never exceed 1.0 even with boost."""
        column = ColumnInput(column_name="ssn", column_id="employees:ssn", table_name="employees")
        findings = engine.classify_column(column, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].confidence <= 1.0

    def test_boost_evidence_mentions_table(self, engine: ColumnNameEngine) -> None:
        """Evidence string should mention table context when boost is applied."""
        column = ColumnInput(column_name="ssn", column_id="employees:ssn", table_name="employees")
        findings = engine.classify_column(column, min_confidence=0.0)
        assert len(findings) == 1
        assert "employees" in findings[0].evidence

    def test_boost_amount(self, engine: ColumnNameEngine) -> None:
        """Boost should be exactly +0.05, capped at 1.0."""
        base = ColumnInput(column_name="ssn", column_id="no_table:ssn")
        boosted = ColumnInput(column_name="ssn", column_id="employees:ssn", table_name="employees")
        base_findings = engine.classify_column(base, min_confidence=0.0)
        boosted_findings = engine.classify_column(boosted, min_confidence=0.0)
        expected = min(1.0, base_findings[0].confidence + 0.05)
        assert boosted_findings[0].confidence == pytest.approx(expected, abs=0.001)

    def test_payments_account_number_boost(self, engine: ColumnNameEngine) -> None:
        """payments.account_number → Financial context boost."""
        base = ColumnInput(column_name="account_number", column_id="no_table:acctnum")
        boosted = ColumnInput(column_name="account_number", column_id="payments:acctnum", table_name="payments")
        base_findings = engine.classify_column(base, min_confidence=0.0)
        boosted_findings = engine.classify_column(boosted, min_confidence=0.0)
        assert len(base_findings) == 1
        assert len(boosted_findings) == 1
        assert boosted_findings[0].confidence > base_findings[0].confidence

    @pytest.mark.parametrize(
        "table_name,column_name,expected_entity_type",
        [
            ("employees", "ssn", "SSN"),
            ("patients", "mrn", "HEALTH"),
            ("customers", "email", "EMAIL"),
            ("users", "date_of_birth", "DATE_OF_BIRTH"),
            ("billing", "credit_card_number", "CREDIT_CARD"),
            ("personnel", "first_name", "PERSON_NAME"),
        ],
    )
    def test_compound_preserves_entity_type(
        self, engine: ColumnNameEngine, table_name: str, column_name: str, expected_entity_type: str
    ) -> None:
        """Compound matching must not change the entity type, only the confidence."""
        column = ColumnInput(column_name=column_name, column_id=f"{table_name}:{column_name}", table_name=table_name)
        findings = engine.classify_column(column, min_confidence=0.0)
        assert len(findings) >= 1
        assert findings[0].entity_type == expected_entity_type


# ── TestSchemaNameField ─────────────────────────────────────────────────────


class TestSchemaNameField:
    """schema_name field on ColumnInput — backward compatible."""

    def test_schema_name_default_empty(self) -> None:
        col = ColumnInput(column_name="ssn")
        assert col.schema_name == ""

    def test_schema_name_accepted(self) -> None:
        col = ColumnInput(column_name="ssn", schema_name="public")
        assert col.schema_name == "public"

    def test_schema_name_does_not_affect_classification(self, engine: ColumnNameEngine) -> None:
        """schema_name is stored but does not alter classification output."""
        without = ColumnInput(column_name="ssn", column_id="a")
        with_schema = ColumnInput(column_name="ssn", column_id="b", schema_name="hr")
        f1 = engine.classify_column(without, min_confidence=0.0)
        f2 = engine.classify_column(with_schema, min_confidence=0.0)
        assert len(f1) == 1
        assert len(f2) == 1
        assert f1[0].entity_type == f2[0].entity_type
        assert f1[0].confidence == f2[0].confidence

    def test_backward_compat_no_schema_name(self, engine: ColumnNameEngine) -> None:
        """Existing code that omits schema_name continues to work."""
        col = ColumnInput(column_name="email_address", column_id="legacy")
        findings = engine.classify_column(col, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].entity_type == "EMAIL"


# ── TestDeviceIdMacAddressFix ─────────────────────────────────────────────


class TestDeviceIdMacAddressFix:
    """Regression: mac_address columns must return MAC_ADDRESS, not DEVICE_ID.

    Sprint 5 fix — mac-related variants were duplicated in DEVICE_ID and
    MAC_ADDRESS, with DEVICE_ID loaded first winning the first-come-first-served
    registration.
    """

    def test_mac_address_returns_mac_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "mac_address")
        assert len(findings) == 1
        assert findings[0].entity_type == "MAC_ADDRESS"

    def test_macaddress_returns_mac_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "macaddress")
        assert len(findings) == 1
        assert findings[0].entity_type == "MAC_ADDRESS"

    def test_mac_addr_returns_mac_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "mac_addr")
        assert len(findings) == 1
        assert findings[0].entity_type == "MAC_ADDRESS"

    def test_device_mac_returns_mac_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "device_mac")
        assert len(findings) == 1
        assert findings[0].entity_type == "MAC_ADDRESS"

    def test_wifi_mac_returns_mac_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "wifi_mac")
        assert len(findings) == 1
        assert findings[0].entity_type == "MAC_ADDRESS"

    def test_hardware_address_returns_mac_address(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "hardware_address")
        assert len(findings) == 1
        assert findings[0].entity_type == "MAC_ADDRESS"

    def test_device_id_still_returns_device_id(self, engine: ColumnNameEngine) -> None:
        """device_id column still correctly classified as DEVICE_ID."""
        findings = _classify(engine, "device_id")
        assert len(findings) == 1
        assert findings[0].entity_type == "DEVICE_ID"

    def test_deviceid_still_returns_device_id(self, engine: ColumnNameEngine) -> None:
        findings = _classify(engine, "deviceid")
        assert len(findings) == 1
        assert findings[0].entity_type == "DEVICE_ID"

    def test_imei_returns_device_id(self, engine: ColumnNameEngine) -> None:
        """imei is a DEVICE_ID variant, not MAC_ADDRESS."""
        findings = _classify(engine, "imei")
        assert len(findings) == 1
        assert findings[0].entity_type == "DEVICE_ID"


# ── get_variant_category tests (Sprint 13 scoping Q1) ──────────────────────


def test_get_variant_category_heterogeneous_hint() -> None:
    from data_classifier.engines.column_name_engine import ColumnNameEngine

    engine = ColumnNameEngine()
    assert engine.get_variant_category("log_line") == "heterogeneous"


def test_get_variant_category_structured_hint() -> None:
    from data_classifier.engines.column_name_engine import ColumnNameEngine

    engine = ColumnNameEngine()
    assert engine.get_variant_category("email") == "structured"


def test_get_variant_category_unknown() -> None:
    from data_classifier.engines.column_name_engine import ColumnNameEngine

    engine = ColumnNameEngine()
    assert engine.get_variant_category("some_random_name_xyz") is None
