"""Tests for the finding-level credential noise gate (F2).

Covers:
1. Placeholder values → CREDENTIAL finding suppressed
2. Real credential values → CREDENTIAL finding kept
3. Mixed column (placeholder + real) → only real finding kept
4. Non-CREDENTIAL findings never suppressed even if values look placeholder-y
5. Findings with no sample_analysis never suppressed (safety)
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import ClassificationFinding, SampleAnalysis
from data_classifier.orchestrator.credential_gate import (
    BRACKET_PH,
    CONFIG_LITERAL,
    PLACEHOLDER_X,
    filter_credential_noise,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_finding(
    entity_type: str,
    sample_matches: list[str] | None = None,
    *,
    family: str = "",
    category: str = "Credential",
    engine: str = "regex",
    confidence: float = 0.9,
    column_id: str = "col_1",
    no_sample_analysis: bool = False,
) -> ClassificationFinding:
    """Build a ClassificationFinding with optional sample_analysis."""
    sa = None
    if not no_sample_analysis and sample_matches is not None:
        sa = SampleAnalysis(
            samples_scanned=10,
            samples_matched=len(sample_matches),
            samples_validated=len(sample_matches),
            match_ratio=len(sample_matches) / 10,
            sample_matches=sample_matches,
        )
    return ClassificationFinding(
        column_id=column_id,
        entity_type=entity_type,
        category=category,
        sensitivity="CRITICAL",
        confidence=confidence,
        regulatory=["SOC2"],
        engine=engine,
        evidence="test",
        sample_analysis=sa,
        family=family,
    )


# ── 1. Placeholder values suppress CREDENTIAL findings ──────────────────────


class TestPlaceholderSuppression:
    """Values that are clearly placeholders should cause suppression."""

    @pytest.mark.parametrize(
        "value",
        [
            "SUMO_ACCESS_KEY=xxxxxxxxxx",
            "api_key=XXXXXXXXXXXX",
            "secret=****",
            "token=################",
            "pass=~~~~",
            "[PASSWORD]",
            "[TOKEN]",
            "[REDACTED]",
            "<API_KEY>",
            "<SECRET_TOKEN>",
        ],
        ids=lambda v: v[:30],
    )
    def test_placeholder_values_suppressed(self, value: str) -> None:
        findings = [_make_finding("OPAQUE_SECRET", [value])]
        result = filter_credential_noise(findings)
        assert len(result) == 0, f"Expected suppression for value: {value!r}"

    @pytest.mark.parametrize(
        "entity_type",
        ["API_KEY", "OPAQUE_SECRET", "PRIVATE_KEY", "PASSWORD", "PASSWORD_HASH", "CREDENTIAL"],
    )
    def test_all_credential_subtypes_suppressed(self, entity_type: str) -> None:
        findings = [_make_finding(entity_type, ["xxxxxxxxxxxx"])]
        result = filter_credential_noise(findings)
        assert len(result) == 0

    def test_config_literal_suppressed(self) -> None:
        findings = [_make_finding("API_KEY", ["LOG_LEVEL= INFO", "DEBUG_MODE= true"])]
        result = filter_credential_noise(findings)
        assert len(result) == 0


# ── 2. Real credential values are kept ──────────────────────────────────────


class TestRealCredentialsKept:
    """Genuine credentials must survive the gate."""

    @pytest.mark.parametrize(
        "value",
        [
            "meraki_token=5cb4a5f0abc123def456",
            "sk-proj-abc123def456ghi789",
            "ghp_1234567890abcdefghijklmnopqrstuv",
            "AKIAIOSFODNN7EXAMPLE",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        ],
        ids=lambda v: v[:30],
    )
    def test_real_credential_kept(self, value: str) -> None:
        findings = [_make_finding("OPAQUE_SECRET", [value])]
        result = filter_credential_noise(findings)
        assert len(result) == 1
        assert result[0].entity_type == "OPAQUE_SECRET"


# ── 3. Mixed column: real + placeholder → only real kept ────────────────────


class TestMixedColumn:
    """Column with both real and placeholder credentials."""

    def test_mixed_column_keeps_real_drops_placeholder(self) -> None:
        """Two separate findings: one with placeholder match, one with real match."""
        placeholder_finding = _make_finding(
            "OPAQUE_SECRET",
            ["SUMO_ACCESS_KEY=xxxxxxxxxxxx"],
            column_id="col_mixed",
        )
        real_finding = _make_finding(
            "API_KEY",
            ["meraki_token=5cb4a5f0abc123def456"],
            column_id="col_mixed",
        )
        result = filter_credential_noise([placeholder_finding, real_finding])
        assert len(result) == 1
        assert result[0].entity_type == "API_KEY"

    def test_finding_with_mixed_matches_kept(self) -> None:
        """A single finding whose sample_matches contain both noise and real values is kept.

        The gate suppresses only when ALL matched values are noise.
        """
        finding = _make_finding(
            "OPAQUE_SECRET",
            ["xxxxxxxxxxxx", "5cb4a5f0abc123def456"],
        )
        result = filter_credential_noise([finding])
        assert len(result) == 1


# ── 4. Non-CREDENTIAL findings never suppressed ────────────────────────────


class TestNonCredentialNotSuppressed:
    """Non-CREDENTIAL findings pass through even if values look like placeholders."""

    @pytest.mark.parametrize(
        "entity_type,category,family",
        [
            ("URL", "PII", "URL"),
            ("EMAIL", "PII", "CONTACT"),
            ("PHONE", "PII", "CONTACT"),
            ("SSN", "PII", "GOVERNMENT_ID"),
            ("IP_ADDRESS", "PII", "NETWORK"),
        ],
    )
    def test_non_credential_kept(self, entity_type: str, category: str, family: str) -> None:
        findings = [
            _make_finding(
                entity_type,
                ["xxxxxxxxxxxx", "[PASSWORD]"],
                family=family,
                category=category,
            )
        ]
        result = filter_credential_noise(findings)
        assert len(result) == 1
        assert result[0].entity_type == entity_type


# ── 5. No sample_analysis → never suppressed (safety) ──────────────────────


class TestSafetyNoSampleAnalysis:
    """Findings with no sample_analysis must never be suppressed."""

    def test_no_sample_analysis_kept(self) -> None:
        finding = _make_finding("OPAQUE_SECRET", None, no_sample_analysis=True)
        result = filter_credential_noise([finding])
        assert len(result) == 1

    def test_empty_sample_matches_kept(self) -> None:
        """sample_analysis exists but sample_matches is empty → kept."""
        finding = _make_finding("OPAQUE_SECRET", [])
        result = filter_credential_noise([finding])
        assert len(result) == 1


# ── Pattern unit tests ──────────────────────────────────────────────────────


class TestPatterns:
    """Verify pattern correctness independently."""

    @pytest.mark.parametrize(
        "value",
        [
            "= 42",
            "= true",
            "= false",
            "= null",
            "= None",
            "= INFO",
            "= DEBUG;",
            "= WARN,",
            '= "hello world"',
            "=ERROR",
        ],
    )
    def test_config_literal_matches(self, value: str) -> None:
        assert CONFIG_LITERAL.search(value), f"CONFIG_LITERAL should match: {value!r}"

    @pytest.mark.parametrize(
        "value",
        [
            "= sk-proj-abc123def456",
            "= eyJhbGciOiJIUzI1NiJ9",
            "= ghp_1234567890abcdef",
        ],
    )
    def test_config_literal_no_match(self, value: str) -> None:
        assert not CONFIG_LITERAL.search(value), f"CONFIG_LITERAL should NOT match: {value!r}"

    @pytest.mark.parametrize(
        "value",
        ["xxxx", "XXXX", "****", "####", "~~~~", "xxxxxxxxxxxxxxxx"],
    )
    def test_placeholder_x_matches(self, value: str) -> None:
        assert PLACEHOLDER_X.search(value), f"PLACEHOLDER_X should match: {value!r}"

    @pytest.mark.parametrize(
        "value",
        ["xxx", "***", "###", "~~~"],  # too short (< 4)
    )
    def test_placeholder_x_no_match(self, value: str) -> None:
        assert not PLACEHOLDER_X.search(value), f"PLACEHOLDER_X should NOT match: {value!r}"

    @pytest.mark.parametrize(
        "value",
        ["[PASSWORD]", "[TOKEN]", "[KEY]", "[REDACTED]", "<API_KEY>", "<SECRET>"],
    )
    def test_bracket_ph_matches(self, value: str) -> None:
        assert BRACKET_PH.search(value), f"BRACKET_PH should match: {value!r}"
