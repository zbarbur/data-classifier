"""Tests for sibling column analysis (two-pass classification).

Covers:
  - Table profile inference from sibling findings
  - Domain-based confidence adjustments
  - Two-pass orchestration: single column unchanged, multiple columns use sibling context
  - SSN/ABA/NPI disambiguation with sibling context
  - Backward compatibility: single-column classification unchanged
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import (
    ClassificationProfile,
    ColumnInput,
)
from data_classifier.orchestrator.orchestrator import Orchestrator
from data_classifier.orchestrator.table_profile import (
    TableProfile,
    build_table_profile,
    get_sibling_adjustment,
)

# Reuse stub engine from engine weighting tests
from tests.test_engine_weighting import StubEngine, _make_finding

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def empty_profile() -> ClassificationProfile:
    return ClassificationProfile(name="test", description="Test profile", rules=[])


# ── Table Profile Building ────────────────────────────────────────────────────


class TestBuildTableProfile:
    """Tests for build_table_profile() domain inference."""

    def test_healthcare_domain_from_npi(self):
        """Multiple healthcare findings signal healthcare domain."""
        findings = [
            _make_finding("NPI", 0.85, "regex", column_id="col1"),
            _make_finding("DIAGNOSIS", 0.90, "regex", column_id="col2"),
        ]
        profile = build_table_profile(findings)

        assert profile.primary_domain == "healthcare"
        assert "healthcare" in profile.domains
        assert profile.signal_count == 2

    def test_financial_domain_from_aba(self):
        """Multiple financial findings signal financial domain."""
        findings = [
            _make_finding("ABA_ROUTING", 0.85, "regex", column_id="col1"),
            _make_finding("CREDIT_CARD", 0.90, "regex", column_id="col2"),
        ]
        profile = build_table_profile(findings)

        assert profile.primary_domain == "financial"

    def test_customer_pii_domain(self):
        """Multiple PII findings signal customer_pii domain."""
        findings = [
            _make_finding("SSN", 0.90, "column_name", column_id="col1"),
            _make_finding("EMAIL", 0.90, "column_name", column_id="col2"),
            _make_finding("PHONE", 0.85, "regex", column_id="col3"),
        ]
        profile = build_table_profile(findings)

        assert profile.primary_domain == "customer_pii"
        assert profile.domains["customer_pii"] == 3

    def test_no_domain_when_below_threshold(self):
        """Low-confidence findings do not contribute to domain inference."""
        findings = [
            _make_finding("NPI", 0.50, "regex", column_id="col1"),
            _make_finding("EMAIL", 0.60, "column_name", column_id="col2"),
        ]
        profile = build_table_profile(findings)

        assert profile.primary_domain is None
        assert profile.signal_count == 0

    def test_exclude_column_id(self):
        """Excluded column's findings do not affect profile."""
        findings = [
            _make_finding("NPI", 0.90, "regex", column_id="col1"),
            _make_finding("SSN", 0.90, "column_name", column_id="col2"),
        ]
        profile = build_table_profile(findings, exclude_column_id="col1")

        # Only col2's SSN remains — customer_pii domain
        assert profile.primary_domain == "customer_pii"
        assert profile.signal_count == 1

    def test_empty_findings(self):
        """Empty findings produce empty profile."""
        profile = build_table_profile([])

        assert profile.primary_domain is None
        assert profile.signal_count == 0
        assert profile.domains == {}

    def test_tied_domains_no_primary(self):
        """When two domains are tied, no primary domain is set."""
        findings = [
            _make_finding("NPI", 0.90, "regex", column_id="col1"),
            _make_finding("ABA_ROUTING", 0.90, "regex", column_id="col2"),
        ]
        profile = build_table_profile(findings)

        assert profile.primary_domain is None
        assert profile.domains.get("healthcare") == 1
        assert profile.domains.get("financial") == 1


# ── Sibling Adjustments ──────────────────────────────────────────────────────


class TestSiblingAdjustment:
    """Tests for get_sibling_adjustment() domain-based adjustments."""

    def test_npi_boosted_in_healthcare(self):
        """NPI is boosted in healthcare domain."""
        profile = TableProfile(
            domains={"healthcare": 2},
            primary_domain="healthcare",
            signal_count=2,
        )
        adj = get_sibling_adjustment("NPI", profile)
        assert adj > 0

    def test_aba_suppressed_in_healthcare(self):
        """ABA_ROUTING is suppressed in healthcare domain."""
        profile = TableProfile(
            domains={"healthcare": 2},
            primary_domain="healthcare",
            signal_count=2,
        )
        adj = get_sibling_adjustment("ABA_ROUTING", profile)
        assert adj < 0

    def test_aba_boosted_in_financial(self):
        """ABA_ROUTING is boosted in financial domain."""
        profile = TableProfile(
            domains={"financial": 2},
            primary_domain="financial",
            signal_count=2,
        )
        adj = get_sibling_adjustment("ABA_ROUTING", profile)
        assert adj > 0

    def test_npi_suppressed_in_financial(self):
        """NPI is suppressed in financial domain."""
        profile = TableProfile(
            domains={"financial": 2},
            primary_domain="financial",
            signal_count=2,
        )
        adj = get_sibling_adjustment("NPI", profile)
        assert adj < 0

    def test_ssn_boosted_in_customer_pii(self):
        """SSN is boosted in customer_pii domain."""
        profile = TableProfile(
            domains={"customer_pii": 3},
            primary_domain="customer_pii",
            signal_count=3,
        )
        adj = get_sibling_adjustment("SSN", profile)
        assert adj > 0

    def test_no_adjustment_without_domain(self):
        """No adjustment when no primary domain."""
        profile = TableProfile(domains={}, primary_domain=None, signal_count=0)
        adj = get_sibling_adjustment("SSN", profile)
        assert adj == 0.0

    def test_no_adjustment_for_unknown_type(self):
        """Unknown entity types get no adjustment."""
        profile = TableProfile(
            domains={"healthcare": 2},
            primary_domain="healthcare",
            signal_count=2,
        )
        adj = get_sibling_adjustment("UNKNOWN_TYPE", profile)
        assert adj == 0.0


# ── Two-Pass Orchestration ────────────────────────────────────────────────────


class TestTwoPassOrchestration:
    """Tests for the orchestrator's two-pass classify_columns method."""

    def test_single_column_unchanged(self, empty_profile):
        """Single column classification is unchanged (no sibling context)."""
        engine = StubEngine(
            "regex",
            2,
            5,
            [_make_finding("SSN", 0.90, "regex", column_id="col1")],
        )
        orch = Orchestrator(engines=[engine])
        col = ColumnInput(column_name="ssn", column_id="col1")
        results = orch.classify_columns([col], empty_profile, min_confidence=0.0)

        assert len(results) == 1
        assert results[0].entity_type == "SSN"
        assert results[0].confidence == pytest.approx(0.90)

    def test_empty_columns_returns_empty(self, empty_profile):
        """Empty column list returns empty findings."""
        engine = StubEngine("regex", 2, 5, [])
        orch = Orchestrator(engines=[engine])
        results = orch.classify_columns([], empty_profile, min_confidence=0.0)

        assert results == []

    def test_multiple_columns_two_pass(self, empty_profile):
        """Multiple columns trigger two-pass with sibling context."""
        # Simulate healthcare table: col1=NPI, col2=DIAGNOSIS, col3=ambiguous SSN
        # col3 has SSN which should NOT be suppressed in healthcare (patients have SSNs)
        findings_map = {
            "col1": [_make_finding("NPI", 0.90, "regex", column_id="col1")],
            "col2": [_make_finding("DIAGNOSIS", 0.85, "regex", column_id="col2")],
            "col3": [_make_finding("SSN", 0.80, "regex", column_id="col3")],
        }

        class MultiColumnEngine(StubEngine):
            def classify_column(self, column, *, profile=None, min_confidence=0.5, **kwargs):
                return list(findings_map.get(column.column_id, []))

        engine = MultiColumnEngine("regex", 2, 5)
        orch = Orchestrator(engines=[engine])

        columns = [
            ColumnInput(column_name="npi_number", column_id="col1"),
            ColumnInput(column_name="diagnosis_code", column_id="col2"),
            ColumnInput(column_name="patient_ssn", column_id="col3"),
        ]
        results = orch.classify_columns(columns, empty_profile, min_confidence=0.0)

        # All three should be present
        types = {f.entity_type for f in results}
        assert "NPI" in types
        assert "DIAGNOSIS" in types
        assert "SSN" in types

        # SSN should be boosted in healthcare context
        ssn = [f for f in results if f.entity_type == "SSN"][0]
        assert ssn.confidence > 0.80  # Boosted by healthcare domain context


class TestSiblingDisambiguation:
    """Tests for SSN/ABA/NPI disambiguation using sibling context."""

    def test_aba_suppressed_in_healthcare_table(self, empty_profile):
        """ABA_ROUTING is suppressed when siblings indicate healthcare domain."""
        findings_map = {
            "col1": [_make_finding("NPI", 0.90, "regex", column_id="col1")],
            "col2": [_make_finding("DIAGNOSIS", 0.85, "regex", column_id="col2")],
            "col3": [_make_finding("ABA_ROUTING", 0.75, "regex", column_id="col3")],
        }

        class MultiColumnEngine(StubEngine):
            def classify_column(self, column, *, profile=None, min_confidence=0.5, **kwargs):
                return list(findings_map.get(column.column_id, []))

        engine = MultiColumnEngine("regex", 2, 5)
        orch = Orchestrator(engines=[engine])

        columns = [
            ColumnInput(column_name="npi_number", column_id="col1"),
            ColumnInput(column_name="diagnosis", column_id="col2"),
            ColumnInput(column_name="routing_number", column_id="col3"),
        ]
        results = orch.classify_columns(columns, empty_profile, min_confidence=0.0)

        # ABA should have reduced confidence in healthcare context
        aba = [f for f in results if f.entity_type == "ABA_ROUTING"]
        if aba:
            assert aba[0].confidence < 0.75  # Suppressed

    def test_npi_suppressed_in_financial_table(self, empty_profile):
        """NPI is suppressed when siblings indicate financial domain."""
        findings_map = {
            "col1": [_make_finding("ABA_ROUTING", 0.90, "regex", column_id="col1")],
            "col2": [_make_finding("CREDIT_CARD", 0.85, "regex", column_id="col2")],
            "col3": [_make_finding("NPI", 0.75, "regex", column_id="col3")],
        }

        class MultiColumnEngine(StubEngine):
            def classify_column(self, column, *, profile=None, min_confidence=0.5, **kwargs):
                return list(findings_map.get(column.column_id, []))

        engine = MultiColumnEngine("regex", 2, 5)
        orch = Orchestrator(engines=[engine])

        columns = [
            ColumnInput(column_name="routing_number", column_id="col1"),
            ColumnInput(column_name="card_number", column_id="col2"),
            ColumnInput(column_name="provider_id", column_id="col3"),
        ]
        results = orch.classify_columns(columns, empty_profile, min_confidence=0.0)

        # NPI should have reduced confidence in financial context
        npi = [f for f in results if f.entity_type == "NPI"]
        if npi:
            assert npi[0].confidence < 0.75  # Suppressed

    def test_ssn_boosted_in_customer_pii_table(self, empty_profile):
        """SSN is boosted when siblings indicate customer PII domain."""
        findings_map = {
            "col1": [_make_finding("EMAIL", 0.90, "column_name", column_id="col1")],
            "col2": [_make_finding("PHONE", 0.85, "column_name", column_id="col2")],
            "col3": [_make_finding("SSN", 0.80, "regex", column_id="col3")],
        }

        class MultiColumnEngine(StubEngine):
            def classify_column(self, column, *, profile=None, min_confidence=0.5, **kwargs):
                return list(findings_map.get(column.column_id, []))

        engine = MultiColumnEngine("regex", 2, 5)
        orch = Orchestrator(engines=[engine])

        columns = [
            ColumnInput(column_name="email", column_id="col1"),
            ColumnInput(column_name="phone", column_id="col2"),
            ColumnInput(column_name="tax_id", column_id="col3"),
        ]
        results = orch.classify_columns(columns, empty_profile, min_confidence=0.0)

        # SSN should be boosted in customer PII context
        ssn = [f for f in results if f.entity_type == "SSN"][0]
        assert ssn.confidence > 0.80

    def test_no_adjustment_without_clear_domain(self, empty_profile):
        """No adjustment when siblings don't establish a clear domain."""
        findings_map = {
            "col1": [_make_finding("EMAIL", 0.90, "column_name", column_id="col1")],
            "col2": [_make_finding("SSN", 0.80, "regex", column_id="col2")],
        }

        class MultiColumnEngine(StubEngine):
            def classify_column(self, column, *, profile=None, min_confidence=0.5, **kwargs):
                return list(findings_map.get(column.column_id, []))

        engine = MultiColumnEngine("regex", 2, 5)
        orch = Orchestrator(engines=[engine])

        columns = [
            ColumnInput(column_name="email", column_id="col1"),
            ColumnInput(column_name="ssn", column_id="col2"),
        ]
        results = orch.classify_columns(columns, empty_profile, min_confidence=0.0)

        # Both EMAIL and SSN are customer_pii, but when excluding each column
        # from the profile, there's only 1 signal — should still work
        ssn = [f for f in results if f.entity_type == "SSN"]
        assert len(ssn) == 1


# ── Backward Compatibility ────────────────────────────────────────────────────


class TestBackwardCompatibility:
    """Ensure classify_columns is backward compatible with existing behavior."""

    def test_classify_columns_matches_single_column_calls(self, empty_profile):
        """classify_columns with one column gives same result as classify_column."""
        engine = StubEngine(
            "regex",
            2,
            5,
            [_make_finding("EMAIL", 0.90, "regex", column_id="col1")],
        )
        orch = Orchestrator(engines=[engine])
        col = ColumnInput(column_name="email", column_id="col1")

        single_result = orch.classify_column(col, empty_profile, min_confidence=0.0)
        multi_result = orch.classify_columns([col], empty_profile, min_confidence=0.0)

        assert len(single_result) == len(multi_result)
        assert single_result[0].entity_type == multi_result[0].entity_type
        assert single_result[0].confidence == multi_result[0].confidence

    def test_min_confidence_filter_applied(self, empty_profile):
        """min_confidence filter works in two-pass mode."""
        findings_map = {
            "col1": [_make_finding("EMAIL", 0.90, "column_name", column_id="col1")],
            "col2": [_make_finding("SSN", 0.40, "regex", column_id="col2")],
        }

        class MultiColumnEngine(StubEngine):
            def classify_column(self, column, *, profile=None, min_confidence=0.5, **kwargs):
                return [f for f in findings_map.get(column.column_id, []) if f.confidence >= min_confidence]

        engine = MultiColumnEngine("regex", 2, 5)
        orch = Orchestrator(engines=[engine])

        columns = [
            ColumnInput(column_name="email", column_id="col1"),
            ColumnInput(column_name="ssn", column_id="col2"),
        ]
        results = orch.classify_columns(columns, empty_profile, min_confidence=0.5)

        # SSN at 0.40 should be filtered out by min_confidence
        types = {f.entity_type for f in results}
        assert "EMAIL" in types
        assert "SSN" not in types


# ── Parameterized Domain Scenarios ────────────────────────────────────────────


@pytest.mark.parametrize(
    "sibling_types,target_type,target_confidence,domain,should_boost",
    [
        (["NPI", "DIAGNOSIS"], "SSN", 0.80, "healthcare", True),
        (["NPI", "DIAGNOSIS"], "ABA_ROUTING", 0.80, "healthcare", False),
        (["ABA_ROUTING", "CREDIT_CARD"], "BANK_ACCOUNT", 0.80, "financial", True),
        (["ABA_ROUTING", "CREDIT_CARD"], "NPI", 0.80, "financial", False),
        (["SSN", "EMAIL", "PHONE"], "CANADIAN_SIN", 0.80, "customer_pii", True),
        (["SSN", "EMAIL", "PHONE"], "NPI", 0.80, "customer_pii", False),
    ],
    ids=[
        "SSN_boosted_healthcare",
        "ABA_suppressed_healthcare",
        "BANK_boosted_financial",
        "NPI_suppressed_financial",
        "SIN_boosted_pii",
        "NPI_suppressed_pii",
    ],
)
def test_domain_adjustment_direction(
    empty_profile,
    sibling_types,
    target_type,
    target_confidence,
    domain,
    should_boost,
):
    """Parameterized: verify boost/suppress direction for domain contexts."""
    col_id_counter = 0
    findings_map = {}

    for stype in sibling_types:
        col_id = f"sibling_{col_id_counter}"
        findings_map[col_id] = [_make_finding(stype, 0.90, "regex", column_id=col_id)]
        col_id_counter += 1

    target_col_id = "target"
    findings_map[target_col_id] = [_make_finding(target_type, target_confidence, "regex", column_id=target_col_id)]

    class MultiColumnEngine(StubEngine):
        def classify_column(self, column, *, profile=None, min_confidence=0.5, **kwargs):
            return list(findings_map.get(column.column_id, []))

    engine = MultiColumnEngine("regex", 2, 5)
    orch = Orchestrator(engines=[engine])

    columns = []
    for col_id in findings_map:
        columns.append(ColumnInput(column_name=col_id, column_id=col_id))

    results = orch.classify_columns(columns, empty_profile, min_confidence=0.0)
    target_findings = [f for f in results if f.column_id == target_col_id and f.entity_type == target_type]

    assert len(target_findings) == 1
    if should_boost:
        assert target_findings[0].confidence > target_confidence
    else:
        assert target_findings[0].confidence < target_confidence
