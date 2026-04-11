"""Tests for engine priority weighting in the orchestrator.

Covers:
  - Column name engine overrides regex when entity types conflict
  - Agreement boost when both engines identify the same entity type
  - No change when only one engine produces findings
  - Authority-based merge (same entity_type, different engines)
  - Backward compatibility: single-engine behavior unchanged
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.orchestrator.orchestrator import (
    _AGREEMENT_BOOST,
    Orchestrator,
)

# ── Stub Engines ──────────────────────────────────────────────────────────────


class StubEngine(ClassificationEngine):
    """Configurable stub engine for testing orchestrator merge logic."""

    def __init__(
        self,
        engine_name: str,
        engine_order: int,
        engine_authority: int,
        findings: list[ClassificationFinding] | None = None,
    ) -> None:
        self.name = engine_name
        self.order = engine_order
        self.authority = engine_authority
        self.supported_modes = frozenset({"structured"})
        self._findings = findings or []

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        return list(self._findings)


def _make_finding(
    entity_type: str,
    confidence: float,
    engine: str,
    *,
    category: str = "PII",
    column_id: str = "test:col",
) -> ClassificationFinding:
    return ClassificationFinding(
        column_id=column_id,
        entity_type=entity_type,
        category=category,
        sensitivity="HIGH",
        confidence=confidence,
        regulatory=[],
        engine=engine,
        evidence=f"Stub {engine}: {entity_type}",
    )


@pytest.fixture
def empty_profile() -> ClassificationProfile:
    return ClassificationProfile(name="test", description="Test profile", rules=[])


@pytest.fixture
def column() -> ColumnInput:
    return ColumnInput(column_name="test_col", column_id="test:col")


# ── Conflict resolution: column_name overrides regex ─────────────────────────


class TestColumnNameOverridesRegex:
    """When column_name and regex disagree on entity type, column_name wins."""

    def test_column_name_wins_over_regex(self, empty_profile, column):
        """Column name says EMAIL, regex says SSN — EMAIL should win, SSN suppressed."""
        cn_engine = StubEngine(
            "column_name",
            1,
            10,
            [_make_finding("EMAIL", 0.90, "column_name")],
        )
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [_make_finding("SSN", 0.94, "regex")],
        )
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        entity_types = {f.entity_type for f in results}
        assert "EMAIL" in entity_types
        assert "SSN" not in entity_types, "Regex SSN should be suppressed when column_name says EMAIL"

    def test_column_name_wins_lower_confidence(self, empty_profile, column):
        """Column name engine wins even with lower confidence due to authority."""
        cn_engine = StubEngine(
            "column_name",
            1,
            10,
            [_make_finding("PHONE", 0.75, "column_name")],
        )
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [_make_finding("NPI", 0.94, "regex")],
        )
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        entity_types = {f.entity_type for f in results}
        assert "PHONE" in entity_types
        assert "NPI" not in entity_types

    def test_multiple_regex_findings_suppressed(self, empty_profile, column):
        """Multiple conflicting regex findings are all suppressed."""
        cn_engine = StubEngine(
            "column_name",
            1,
            10,
            [_make_finding("EMAIL", 0.90, "column_name")],
        )
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [
                _make_finding("SSN", 0.94, "regex"),
                _make_finding("PHONE", 0.85, "regex"),
            ],
        )
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        entity_types = {f.entity_type for f in results}
        assert entity_types == {"EMAIL"}


# ── Agreement boost ──────────────────────────────────────────────────────────


class TestAgreementBoost:
    """When column_name and regex agree on entity type, confidence is boosted."""

    def test_agreement_boosts_confidence(self, empty_profile, column):
        """Both engines say EMAIL — confidence should be boosted."""
        cn_engine = StubEngine(
            "column_name",
            1,
            10,
            [_make_finding("EMAIL", 0.90, "column_name")],
        )
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [_make_finding("EMAIL", 0.85, "regex")],
        )
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        assert len(results) == 1
        assert results[0].entity_type == "EMAIL"
        # Column name (0.90) is calibrated to 0.95, then boosted by agreement
        assert results[0].confidence == pytest.approx(min(1.0, 0.95 + _AGREEMENT_BOOST))

    def test_agreement_caps_at_1(self, empty_profile, column):
        """Boosted confidence is capped at 1.0."""
        cn_engine = StubEngine(
            "column_name",
            1,
            10,
            [_make_finding("EMAIL", 0.98, "column_name")],
        )
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [_make_finding("EMAIL", 0.94, "regex")],
        )
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        assert results[0].confidence <= 1.0

    def test_agreement_with_additional_regex_findings(self, empty_profile, column):
        """Regex agrees on EMAIL and also finds PHONE — only EMAIL kept."""
        cn_engine = StubEngine(
            "column_name",
            1,
            10,
            [_make_finding("EMAIL", 0.90, "column_name")],
        )
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [
                _make_finding("EMAIL", 0.85, "regex"),
                _make_finding("PHONE", 0.80, "regex"),
            ],
        )
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        entity_types = {f.entity_type for f in results}
        assert "EMAIL" in entity_types
        assert "PHONE" not in entity_types, "Conflicting PHONE from regex should be suppressed"


# ── Single engine behavior unchanged ─────────────────────────────────────────


class TestSingleEngineUnchanged:
    """Behavior when only one engine produces findings should be unchanged."""

    def test_regex_only(self, empty_profile, column):
        """When only regex matches, all findings are kept."""
        cn_engine = StubEngine("column_name", 1, 10, [])
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [
                _make_finding("SSN", 0.94, "regex"),
                _make_finding("PHONE", 0.80, "regex"),
            ],
        )
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        entity_types = {f.entity_type for f in results}
        assert entity_types == {"SSN", "PHONE"}

    def test_column_name_only(self, empty_profile, column):
        """When only column_name matches, finding is calibrated."""
        cn_engine = StubEngine(
            "column_name",
            1,
            10,
            [_make_finding("EMAIL", 0.90, "column_name")],
        )
        regex_engine = StubEngine("regex", 2, 5, [])
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        assert len(results) == 1
        assert results[0].entity_type == "EMAIL"
        # column_name at 0.90 is calibrated to 0.95 (strong match boost)
        assert results[0].confidence == pytest.approx(0.95)

    def test_no_findings(self, empty_profile, column):
        """When no engine matches, empty list returned."""
        cn_engine = StubEngine("column_name", 1, 10, [])
        regex_engine = StubEngine("regex", 2, 5, [])
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        assert results == []


# ── Authority-based merge for same entity type ───────────────────────────────


class TestAuthorityMerge:
    """When both engines produce the same entity_type, authority decides."""

    def test_higher_authority_wins_same_type(self, empty_profile, column):
        """Column name (auth=10) wins over regex (auth=5) for same entity type."""
        cn_engine = StubEngine(
            "column_name",
            1,
            10,
            [_make_finding("SSN", 0.85, "column_name")],
        )
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [_make_finding("SSN", 0.94, "regex")],
        )
        orch = Orchestrator(engines=[cn_engine, regex_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        ssn = [f for f in results if f.entity_type == "SSN"]
        assert len(ssn) == 1
        # Column name engine's finding is the base (higher authority),
        # then boosted by agreement
        assert ssn[0].engine == "column_name"

    def test_equal_authority_confidence_wins(self, empty_profile, column):
        """Equal authority engines: highest confidence wins."""
        engine_a = StubEngine(
            "engine_a",
            1,
            5,
            [_make_finding("EMAIL", 0.85, "engine_a")],
        )
        engine_b = StubEngine(
            "engine_b",
            2,
            5,
            [_make_finding("EMAIL", 0.90, "engine_b")],
        )
        orch = Orchestrator(engines=[engine_a, engine_b])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        assert len(results) == 1
        assert results[0].confidence == pytest.approx(0.90)


# ── Low-authority engines not suppressed by each other ───────────────────────


class TestLowAuthorityEngines:
    """Engines with similar authority levels do not suppress each other."""

    def test_heuristic_and_regex_both_kept(self, empty_profile, column):
        """Both regex (auth=5) and heuristic (auth=1) kept when no column_name."""
        regex_engine = StubEngine(
            "regex",
            2,
            5,
            [_make_finding("SSN", 0.94, "regex")],
        )
        heuristic_engine = StubEngine(
            "heuristic_stats",
            3,
            1,
            [_make_finding("PHONE", 0.70, "heuristic_stats")],
        )
        orch = Orchestrator(engines=[regex_engine, heuristic_engine])
        results = orch.classify_column(column, empty_profile, min_confidence=0.0)

        entity_types = {f.entity_type for f in results}
        assert "SSN" in entity_types
        assert "PHONE" in entity_types


# ── Parameterized conflict scenarios ─────────────────────────────────────────


@pytest.mark.parametrize(
    "cn_type,regex_type,expected_types",
    [
        ("SSN", "ABA_ROUTING", {"SSN"}),
        ("PHONE", "NPI", {"PHONE"}),
        ("EMAIL", "SSN", {"EMAIL"}),
        ("CREDIT_CARD", "PHONE", {"CREDIT_CARD"}),
        ("DATE_OF_BIRTH", "SSN", {"DATE_OF_BIRTH"}),
    ],
    ids=[
        "SSN_vs_ABA",
        "PHONE_vs_NPI",
        "EMAIL_vs_SSN",
        "CREDIT_CARD_vs_PHONE",
        "DOB_vs_SSN",
    ],
)
def test_conflict_scenarios(empty_profile, column, cn_type, regex_type, expected_types):
    """Parameterized: column_name type always wins over conflicting regex type."""
    cn_engine = StubEngine(
        "column_name",
        1,
        10,
        [_make_finding(cn_type, 0.90, "column_name")],
    )
    regex_engine = StubEngine(
        "regex",
        2,
        5,
        [_make_finding(regex_type, 0.94, "regex")],
    )
    orch = Orchestrator(engines=[cn_engine, regex_engine])
    results = orch.classify_column(column, empty_profile, min_confidence=0.0)

    entity_types = {f.entity_type for f in results}
    assert entity_types == expected_types
