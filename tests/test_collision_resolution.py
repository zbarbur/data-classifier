"""Tests for orchestrator collision resolution logic.

Comprehensive tests for all collision pairs, three-way collisions,
and the CREDENTIAL suppression logic.
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import ClassificationFinding, SampleAnalysis
from data_classifier.orchestrator.orchestrator import _COLLISION_GAP_THRESHOLD, Orchestrator

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_finding(
    entity_type: str,
    confidence: float,
    *,
    engine: str = "regex",
    column_id: str = "test:table:col",
    category: str = "PII",
    sensitivity: str = "CRITICAL",
    regulatory: list[str] | None = None,
    evidence: str = "",
    sample_analysis: SampleAnalysis | None = None,
) -> ClassificationFinding:
    """Create a mock ClassificationFinding for testing."""
    return ClassificationFinding(
        column_id=column_id,
        entity_type=entity_type,
        category=category,
        sensitivity=sensitivity,
        confidence=confidence,
        regulatory=regulatory or [],
        engine=engine,
        evidence=evidence,
        sample_analysis=sample_analysis,
    )


def _findings_dict(*findings: ClassificationFinding) -> dict[str, ClassificationFinding]:
    """Build a findings dict from a list of findings."""
    return {f.entity_type: f for f in findings}


def _make_orchestrator() -> Orchestrator:
    """Create an Orchestrator with no engines (for testing resolution methods directly)."""
    return Orchestrator(engines=[], mode="structured")


# ── Pairwise Collision Tests ────────────────────────────────────────────────


class TestPairwiseCollisionResolution:
    """Tests for _resolve_collisions() with known collision pairs."""

    @pytest.mark.parametrize(
        "type_a, type_b",
        [
            ("SSN", "ABA_ROUTING"),
            ("SSN", "CANADIAN_SIN"),
            ("ABA_ROUTING", "CANADIAN_SIN"),
            ("NPI", "PHONE"),
            ("DEA_NUMBER", "IBAN"),
        ],
        ids=["SSN-ABA", "SSN-SIN", "ABA-SIN", "NPI-PHONE", "DEA-IBAN"],
    )
    def test_higher_confidence_wins_when_gap_exceeds_threshold(self, type_a, type_b):
        """When confidence gap > threshold, higher confidence finding survives."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding(type_a, 0.90),
            _make_finding(type_b, 0.60),
        )
        result = orch._resolve_collisions(findings)
        assert type_a in result
        assert type_b not in result

    @pytest.mark.parametrize(
        "type_a, type_b",
        [
            ("SSN", "ABA_ROUTING"),
            ("SSN", "CANADIAN_SIN"),
            ("ABA_ROUTING", "CANADIAN_SIN"),
            ("NPI", "PHONE"),
            ("DEA_NUMBER", "IBAN"),
        ],
        ids=["SSN-ABA", "SSN-SIN", "ABA-SIN", "NPI-PHONE", "DEA-IBAN"],
    )
    def test_both_kept_when_gap_below_threshold(self, type_a, type_b):
        """When confidence gap < threshold, both findings are kept (ambiguous)."""
        orch = _make_orchestrator()
        # Gap of 0.10 is below default threshold of 0.15
        findings = _findings_dict(
            _make_finding(type_a, 0.80),
            _make_finding(type_b, 0.75),
        )
        result = orch._resolve_collisions(findings)
        assert type_a in result
        assert type_b in result

    @pytest.mark.parametrize(
        "type_a, type_b",
        [
            ("SSN", "ABA_ROUTING"),
            ("SSN", "CANADIAN_SIN"),
            ("ABA_ROUTING", "CANADIAN_SIN"),
            ("NPI", "PHONE"),
            ("DEA_NUMBER", "IBAN"),
        ],
        ids=["SSN-ABA", "SSN-SIN", "ABA-SIN", "NPI-PHONE", "DEA-IBAN"],
    )
    def test_exact_threshold_gap_suppresses(self, type_a, type_b):
        """Gap exactly at threshold should suppress (>= comparison)."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding(type_a, 0.80),
            _make_finding(type_b, 0.80 - _COLLISION_GAP_THRESHOLD),
        )
        result = orch._resolve_collisions(findings)
        assert type_a in result
        assert type_b not in result

    @pytest.mark.parametrize(
        "type_a, type_b",
        [
            ("SSN", "ABA_ROUTING"),
            ("SSN", "CANADIAN_SIN"),
            ("ABA_ROUTING", "CANADIAN_SIN"),
        ],
        ids=["SSN-ABA", "SSN-SIN", "ABA-SIN"],
    )
    def test_reverse_confidence_order_suppresses_correctly(self, type_a, type_b):
        """Lower type_a confidence should be suppressed when type_b is higher."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding(type_a, 0.50),
            _make_finding(type_b, 0.85),
        )
        result = orch._resolve_collisions(findings)
        assert type_b in result
        assert type_a not in result

    def test_equal_confidence_both_kept(self):
        """Equal confidence means gap=0 < threshold, so both kept."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("SSN", 0.80),
            _make_finding("ABA_ROUTING", 0.80),
        )
        result = orch._resolve_collisions(findings)
        assert "SSN" in result
        assert "ABA_ROUTING" in result


# ── Three-way SSN/ABA/SIN Collision Tests ───────────────────────────────────


class TestThreeWayCollisionResolution:
    """Tests for _resolve_three_way_collisions() — SSN + ABA_ROUTING + CANADIAN_SIN."""

    def test_three_way_with_clear_winner_by_confidence(self):
        """When one type has much higher confidence, it wins and others are removed."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("SSN", 0.90),
            _make_finding("ABA_ROUTING", 0.55),
            _make_finding("CANADIAN_SIN", 0.50),
        )
        result = orch._resolve_three_way_collisions(findings)
        assert "SSN" in result
        assert "ABA_ROUTING" not in result
        assert "CANADIAN_SIN" not in result

    def test_three_way_aba_wins(self):
        """ABA_ROUTING can win the three-way collision."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("SSN", 0.50),
            _make_finding("ABA_ROUTING", 0.90),
            _make_finding("CANADIAN_SIN", 0.55),
        )
        result = orch._resolve_three_way_collisions(findings)
        assert "ABA_ROUTING" in result
        assert "SSN" not in result
        assert "CANADIAN_SIN" not in result

    def test_three_way_sin_wins(self):
        """CANADIAN_SIN can win the three-way collision."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("SSN", 0.50),
            _make_finding("ABA_ROUTING", 0.55),
            _make_finding("CANADIAN_SIN", 0.90),
        )
        result = orch._resolve_three_way_collisions(findings)
        assert "CANADIAN_SIN" in result
        assert "SSN" not in result
        assert "ABA_ROUTING" not in result

    def test_three_way_column_name_engine_signal(self):
        """When column_name engine produced a finding, it should be the winner."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("SSN", 0.70, engine="regex"),
            _make_finding("ABA_ROUTING", 0.70, engine="column_name"),
            _make_finding("CANADIAN_SIN", 0.65, engine="regex"),
        )
        result = orch._resolve_three_way_collisions(findings)
        assert "ABA_ROUTING" in result
        assert "SSN" not in result
        assert "CANADIAN_SIN" not in result

    def test_three_way_close_confidence_keeps_all(self):
        """When all three are very close in confidence, keep all (ambiguous)."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("SSN", 0.70),
            _make_finding("ABA_ROUTING", 0.68),
            _make_finding("CANADIAN_SIN", 0.66),
        )
        result = orch._resolve_three_way_collisions(findings)
        # Gap between best and worst is only 0.04 — below threshold
        assert "SSN" in result
        assert "ABA_ROUTING" in result
        assert "CANADIAN_SIN" in result

    def test_three_way_only_runs_when_all_three_present(self):
        """If only two of three are present, three-way resolution is a no-op."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("SSN", 0.90),
            _make_finding("ABA_ROUTING", 0.55),
        )
        result = orch._resolve_three_way_collisions(findings)
        # Both still present — pairwise resolution handles this
        assert "SSN" in result
        assert "ABA_ROUTING" in result

    def test_three_way_heuristic_cardinality_signal(self):
        """Heuristic engine with cardinality info should influence winner."""
        orch = _make_orchestrator()
        # ABA_ROUTING from heuristic engine suggests cardinality analysis
        findings = _findings_dict(
            _make_finding("SSN", 0.70, engine="regex"),
            _make_finding("ABA_ROUTING", 0.72, engine="heuristic"),
            _make_finding("CANADIAN_SIN", 0.65, engine="regex"),
        )
        result = orch._resolve_three_way_collisions(findings)
        # Heuristic engine signal boosts ABA_ROUTING
        assert "ABA_ROUTING" in result


# ── NPI vs PHONE Collision Tests ────────────────────────────────────────────


class TestNpiPhoneCollision:
    """Tests for NPI vs PHONE special resolution logic."""

    def test_phone_wins_by_default(self):
        """Without specific NPI signals, PHONE wins (far more common)."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("NPI", 0.70),
            _make_finding("PHONE", 0.70),
        )
        result = orch._resolve_npi_phone(findings, column_name="some_number")
        assert "PHONE" in result
        assert "NPI" not in result

    def test_npi_wins_with_column_name_npi(self):
        """Column name containing 'npi' strongly favors NPI."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("NPI", 0.70),
            _make_finding("PHONE", 0.75),
        )
        result = orch._resolve_npi_phone(findings, column_name="provider_npi")
        assert "NPI" in result
        assert "PHONE" not in result

    def test_npi_wins_with_column_name_provider(self):
        """Column name containing 'provider' favors NPI."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("NPI", 0.70),
            _make_finding("PHONE", 0.75),
        )
        result = orch._resolve_npi_phone(findings, column_name="provider_id")
        assert "NPI" in result
        assert "PHONE" not in result

    def test_npi_wins_with_column_name_prescriber(self):
        """Column name containing 'prescriber' favors NPI."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("NPI", 0.65),
            _make_finding("PHONE", 0.70),
        )
        result = orch._resolve_npi_phone(findings, column_name="prescriber_number")
        assert "NPI" in result
        assert "PHONE" not in result

    def test_npi_wins_with_validator_confirmation(self):
        """NPI with validator confirmation (evidence mentions 'validated') boosts NPI."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("NPI", 0.70, evidence="NPI check digit validated"),
            _make_finding("PHONE", 0.70),
        )
        result = orch._resolve_npi_phone(findings, column_name="id_number")
        assert "NPI" in result
        assert "PHONE" not in result

    def test_npi_wins_with_sample_validation(self):
        """NPI with samples_validated > 0 indicates validator confirmation."""
        orch = _make_orchestrator()
        npi_analysis = SampleAnalysis(samples_scanned=10, samples_matched=8, samples_validated=7, match_ratio=0.8)
        findings = _findings_dict(
            _make_finding("NPI", 0.70, sample_analysis=npi_analysis),
            _make_finding("PHONE", 0.70),
        )
        result = orch._resolve_npi_phone(findings, column_name="id_number")
        assert "NPI" in result
        assert "PHONE" not in result

    def test_no_resolution_when_only_one_present(self):
        """If only NPI or only PHONE, no change."""
        orch = _make_orchestrator()
        findings = _findings_dict(_make_finding("NPI", 0.80))
        result = orch._resolve_npi_phone(findings, column_name="npi_col")
        assert "NPI" in result


# ── DEA vs IBAN Collision Tests ─────────────────────────────────────────────


class TestDeaIbanCollision:
    """Tests for DEA_NUMBER vs IBAN special resolution logic."""

    def test_short_value_favors_dea(self):
        """9-character values strongly suggest DEA number."""
        orch = _make_orchestrator()
        dea_analysis = SampleAnalysis(
            samples_scanned=10,
            samples_matched=8,
            samples_validated=0,
            match_ratio=0.8,
            sample_matches=["AB1234563"],
        )
        findings = _findings_dict(
            _make_finding("DEA_NUMBER", 0.70, sample_analysis=dea_analysis),
            _make_finding("IBAN", 0.70),
        )
        result = orch._resolve_dea_iban(findings, column_name="dea_col")
        assert "DEA_NUMBER" in result
        assert "IBAN" not in result

    def test_long_value_favors_iban(self):
        """15+ character values strongly suggest IBAN."""
        orch = _make_orchestrator()
        iban_analysis = SampleAnalysis(
            samples_scanned=10,
            samples_matched=8,
            samples_validated=0,
            match_ratio=0.8,
            sample_matches=["GB29NWBK60161331926819"],
        )
        findings = _findings_dict(
            _make_finding("DEA_NUMBER", 0.70),
            _make_finding("IBAN", 0.70, sample_analysis=iban_analysis),
        )
        result = orch._resolve_dea_iban(findings, column_name="account_number")
        assert "IBAN" in result
        assert "DEA_NUMBER" not in result

    def test_dea_validator_confirmation(self):
        """DEA with validator confirmation (samples_validated > 0) wins."""
        orch = _make_orchestrator()
        dea_analysis = SampleAnalysis(
            samples_scanned=10,
            samples_matched=8,
            samples_validated=6,
            match_ratio=0.8,
        )
        findings = _findings_dict(
            _make_finding("DEA_NUMBER", 0.70, sample_analysis=dea_analysis),
            _make_finding("IBAN", 0.75),
        )
        result = orch._resolve_dea_iban(findings, column_name="some_id")
        assert "DEA_NUMBER" in result
        assert "IBAN" not in result

    def test_iban_validator_confirmation(self):
        """IBAN with validator confirmation (samples_validated > 0) wins."""
        orch = _make_orchestrator()
        iban_analysis = SampleAnalysis(
            samples_scanned=10,
            samples_matched=8,
            samples_validated=6,
            match_ratio=0.8,
        )
        findings = _findings_dict(
            _make_finding("DEA_NUMBER", 0.75),
            _make_finding("IBAN", 0.70, sample_analysis=iban_analysis),
        )
        result = orch._resolve_dea_iban(findings, column_name="some_id")
        assert "IBAN" in result
        assert "DEA_NUMBER" not in result

    def test_column_name_dea_tiebreaker(self):
        """Column name containing 'dea' breaks ties toward DEA."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("DEA_NUMBER", 0.70),
            _make_finding("IBAN", 0.70),
        )
        result = orch._resolve_dea_iban(findings, column_name="dea_number")
        assert "DEA_NUMBER" in result
        assert "IBAN" not in result

    def test_column_name_iban_tiebreaker(self):
        """Column name containing 'iban' breaks ties toward IBAN."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("DEA_NUMBER", 0.70),
            _make_finding("IBAN", 0.70),
        )
        result = orch._resolve_dea_iban(findings, column_name="customer_iban")
        assert "IBAN" in result
        assert "DEA_NUMBER" not in result

    def test_no_resolution_when_only_one_present(self):
        """If only one type present, no change."""
        orch = _make_orchestrator()
        findings = _findings_dict(_make_finding("DEA_NUMBER", 0.80))
        result = orch._resolve_dea_iban(findings, column_name="dea_col")
        assert "DEA_NUMBER" in result

    def test_dea_keyword_does_not_match_idea(self):
        """Column name 'idea_status' should NOT trigger DEA keyword match."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("DEA_NUMBER", 0.70),
            _make_finding("IBAN", 0.70),
        )
        # "idea" contains "dea" as substring but should NOT match
        result = orch._resolve_dea_iban(findings, column_name="idea_status")
        assert "DEA_NUMBER" in result
        assert "IBAN" in result  # Both kept — no decisive signal

    def test_dea_keyword_does_not_match_deadline(self):
        """Column name 'deadline' should NOT trigger DEA keyword match."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("DEA_NUMBER", 0.70),
            _make_finding("IBAN", 0.70),
        )
        result = orch._resolve_dea_iban(findings, column_name="deadline")
        assert "DEA_NUMBER" in result
        assert "IBAN" in result  # Both kept — no decisive signal


# ── CREDENTIAL Suppression Tests ────────────────────────────────────────────


class TestCredentialSuppression:
    """Tests for _suppress_generic_credential()."""

    def test_credential_suppressed_when_specific_type_higher(self):
        """CREDENTIAL removed when a more specific type has higher confidence."""
        findings = _findings_dict(
            _make_finding("CREDENTIAL", 0.60, category="Credential"),
            _make_finding("SSN", 0.80),
        )
        result = Orchestrator._suppress_generic_credential(findings)
        assert "CREDENTIAL" not in result
        assert "SSN" in result

    def test_credential_suppressed_when_equal_confidence(self):
        """CREDENTIAL removed when a specific type has equal confidence."""
        findings = _findings_dict(
            _make_finding("CREDENTIAL", 0.80, category="Credential"),
            _make_finding("EMAIL", 0.80),
        )
        result = Orchestrator._suppress_generic_credential(findings)
        assert "CREDENTIAL" not in result
        assert "EMAIL" in result

    def test_credential_kept_when_highest(self):
        """CREDENTIAL kept when it has higher confidence than all others."""
        findings = _findings_dict(
            _make_finding("CREDENTIAL", 0.90, category="Credential"),
            _make_finding("EMAIL", 0.50),
        )
        result = Orchestrator._suppress_generic_credential(findings)
        assert "CREDENTIAL" in result
        assert "EMAIL" in result

    def test_credential_alone_kept(self):
        """CREDENTIAL kept when it's the only finding."""
        findings = _findings_dict(
            _make_finding("CREDENTIAL", 0.80, category="Credential"),
        )
        result = Orchestrator._suppress_generic_credential(findings)
        assert "CREDENTIAL" in result

    def test_no_credential_no_change(self):
        """No CREDENTIAL in findings — nothing to suppress."""
        findings = _findings_dict(
            _make_finding("SSN", 0.80),
            _make_finding("EMAIL", 0.70),
        )
        result = Orchestrator._suppress_generic_credential(findings)
        assert len(result) == 2


# ── Edge Cases ──────────────────────────────────────────────────────────────


class TestCollisionEdgeCases:
    """Edge cases for collision resolution."""

    def test_single_finding_unchanged(self):
        """Single finding passes through collision resolution untouched."""
        orch = _make_orchestrator()
        findings = _findings_dict(_make_finding("SSN", 0.90))
        result = orch._resolve_collisions(findings)
        assert "SSN" in result
        assert len(result) == 1

    def test_empty_findings_unchanged(self):
        """Empty findings dict passes through unchanged."""
        orch = _make_orchestrator()
        result = orch._resolve_collisions({})
        assert len(result) == 0

    def test_non_colliding_types_unchanged(self):
        """Types that are NOT in collision pairs are never suppressed."""
        orch = _make_orchestrator()
        findings = _findings_dict(
            _make_finding("SSN", 0.90),
            _make_finding("EMAIL", 0.85),
            _make_finding("CREDIT_CARD", 0.70),
        )
        result = orch._resolve_collisions(findings)
        assert len(result) == 3

    def test_gap_just_below_threshold_keeps_both(self):
        """Gap one epsilon below threshold keeps both findings."""
        orch = _make_orchestrator()
        gap = _COLLISION_GAP_THRESHOLD - 0.001
        findings = _findings_dict(
            _make_finding("SSN", 0.80),
            _make_finding("ABA_ROUTING", 0.80 - gap),
        )
        result = orch._resolve_collisions(findings)
        assert "SSN" in result
        assert "ABA_ROUTING" in result
