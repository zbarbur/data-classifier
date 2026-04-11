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


# NOTE: Three-way SSN/ABA/SIN, NPI/PHONE, and DEA/IBAN special resolution
# methods were replaced in Sprint 5 by engine authority weighting.
# See tests/test_engine_weighting.py and tests/test_sibling_analysis.py for
# the new collision resolution approach.


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
