"""Tests for column-name-gated random password pattern (Sprint 7).

Sprint 4/5 benchmarks showed the Ai4Privacy CREDENTIAL column (37,738 rows
of short random passwords like ``r]iD1#8``, ``q4R\\``, ``2iGk^``) at 0%
content regex match rate. The 18 existing Sprint 3/5 CREDENTIAL patterns
target specific formats (AWS keys, GitHub tokens, JWTs) — none catch
generic random passwords.

Sprint 7 adds a new ``random_password`` pattern gated by the column name
hint. It only fires when the column name contains a keyword like
``password``, ``pwd``, ``passphrase``, ``secret``, etc. This prevents
FPs on mixed-class content in other columns (UUIDs, tokens in notes,
emails with digits).

The gate is a new ``ContentPattern.requires_column_hint`` mechanism:
- ``requires_column_hint: bool = False`` (default preserves existing behavior)
- ``column_hint_keywords: list[str]`` — substrings to look for in column name
- Checked before validator runs in ``_match_sample_values`` Phase 2

Real samples come from ``tests/fixtures/corpora/ai4privacy_sample.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_classifier import ColumnInput, classify_columns, load_profile
from data_classifier.engines.validators import VALIDATORS
from data_classifier.patterns import load_default_patterns


@pytest.fixture(scope="module")
def profile():
    return load_profile("standard")


@pytest.fixture(scope="module")
def ai4privacy_credentials() -> list[str]:
    fixture = Path(__file__).parent / "fixtures" / "corpora" / "ai4privacy_sample.json"
    data = json.loads(fixture.read_text())
    return [r["value"] for r in data if r.get("entity_type") == "CREDENTIAL"]


class TestRandomPasswordPatternExists:
    """The ``random_password`` pattern must be registered in the pattern library."""

    def test_pattern_loaded(self) -> None:
        patterns = {p.name: p for p in load_default_patterns()}
        assert "random_password" in patterns, "Pattern 'random_password' must be added to default_patterns.json"
        p = patterns["random_password"]
        # Sprint 8 Item 4: random_password retargeted to OPAQUE_SECRET subtype
        # (shape-detector, not a specific credential format).
        assert p.entity_type == "OPAQUE_SECRET"
        assert p.category == "Credential"

    def test_pattern_is_column_gated(self) -> None:
        patterns = {p.name: p for p in load_default_patterns()}
        p = patterns["random_password"]
        assert getattr(p, "requires_column_hint", False) is True, (
            "random_password must set requires_column_hint=True to prevent "
            "FPs on mixed-class content in non-password columns"
        )
        keywords = getattr(p, "column_hint_keywords", [])
        assert keywords, "random_password needs column_hint_keywords list"
        # Essential keywords that must be covered
        lower_kws = {k.lower() for k in keywords}
        for essential in ("password", "passphrase", "secret"):
            assert essential in lower_kws, f"column_hint_keywords missing essential keyword {essential!r}"


class TestRandomPasswordValidator:
    """The ``random_password`` validator must accept real passwords and
    reject common non-password strings."""

    def test_validator_registered(self) -> None:
        assert "random_password" in VALIDATORS, "random_password validator must be registered in VALIDATORS dict"

    @pytest.mark.parametrize(
        "value",
        [
            # Real Ai4Privacy samples — all have upper+lower+digit+symbol
            "r]iD1#8",
            "q4R\\",  # raw backslash
            'Be~o}.zq8^1"',
            "2iGk^",
            "?/Uq.9EP9tR",
            "7v.Pn,",
            "V9R#w7C",
            "yj$4I3t*m~",
            # Canonical strong passwords
            "P@ssw0rd!",
            "Tr0ub4dor&3",
        ],
    )
    def test_accepts_real_passwords(self, value: str) -> None:
        check = VALIDATORS["random_password"]
        assert check(value) is True, f"Validator rejected real-looking password {value!r}"

    @pytest.mark.parametrize(
        "value,reason",
        [
            # Too short
            ("ab", "<4 chars"),
            ("abc", "<4 chars"),
            # Single character class
            ("hello", "all lowercase"),
            ("HELLO", "all uppercase"),
            ("12345", "all digits"),
            ("........", "all symbols"),
            # Two classes — insufficient
            ("hello123", "lower+digit only, no symbol"),
            ("HelloWorld", "upper+lower only, no digit/symbol"),
            # Looks like other content types
            ("john@example.com", "plain email — only 2 classes (lower+symbol)"),
            ("192.168.1.1", "IP — digit+symbol only"),
            ("2026-04-12", "date — digit+symbol only"),
            # Too long
            ("x" * 100, ">64 chars"),
        ],
    )
    def test_rejects_non_passwords(self, value: str, reason: str) -> None:
        check = VALIDATORS["random_password"]
        assert check(value) is False, f"Validator accepted {value!r} ({reason}) — should reject"


class TestPasswordColumnClassification:
    """End-to-end: random passwords under a password column name must
    produce a CREDENTIAL finding with non-zero content match_ratio."""

    def test_password_column_produces_credential_finding_with_match_ratio(self, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="password",
            sample_values=[
                "r]iD1#8",
                "q4R\\x",
                "Be~o}.zq8^1",
                "2iGk^a",
                "P@ssw0rd!",
                "Tr0ub4dor&3",
                "yj$4I3t*m~",
                "V9R#w7C",
                "7v.Pn,z",
                "?/Uq.9EP9tR",
            ],
        )
        findings = classify_columns([col], profile)
        # Sprint 8 Item 4: password column → credential category (any of the 4
        # subtypes); in practice OPAQUE_SECRET for shape-matched values.
        credential = next((f for f in findings if f.category == "Credential"), None)
        assert credential is not None, (
            f"Expected a Credential-category finding for password column, got {[f.entity_type for f in findings]}"
        )
        assert credential.entity_type == "OPAQUE_SECRET", (
            f"Expected OPAQUE_SECRET for password column, got {credential.entity_type}"
        )
        # The content match_ratio must reflect regex matches, not just
        # the column_name engine's identification
        if credential.sample_analysis is not None:
            match_ratio = credential.sample_analysis.match_ratio
            assert match_ratio >= 0.5, (
                f"Expected match_ratio >= 0.5 for password column "
                f"with random passwords, got {match_ratio}. "
                f"sample_analysis={credential.sample_analysis}"
            )


class TestColumnGatePreventsFalsePositives:
    """Random-looking content under a non-password column name must NOT
    produce a CREDENTIAL finding via the random_password pattern."""

    def test_password_like_content_under_notes_column_not_credential(self, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="notes",  # generic column, no credential hint
            sample_values=[
                "P@ssw0rd!",
                "r]iD1#8",
                "Tr0ub4dor&3",
            ],
        )
        findings = classify_columns([col], profile)
        # Sprint 8 Item 4: random_password → OPAQUE_SECRET, and the column-gate
        # must still suppress it when the column name has no credential hint.
        credentials_from_random_password = [
            f
            for f in findings
            if f.category == "Credential"
            and f.engine == "regex"
            and f.sample_analysis is not None
            and f.sample_analysis.match_ratio > 0
        ]
        assert not credentials_from_random_password, (
            f"random_password should not fire without a password column hint, got {credentials_from_random_password}"
        )

    def test_uuid_under_id_column_not_credential(self, profile) -> None:
        """UUIDs under 'id' column have 4 classes but must not land in the
        Credential category (Sprint 8 Item 4: credential category = API_KEY,
        PRIVATE_KEY, PASSWORD_HASH, or OPAQUE_SECRET).
        """
        col = ColumnInput(
            column_id="c1",
            column_name="user_id",
            sample_values=[
                "550e8400-e29b-41d4-a716-446655440000",
                "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            ],
        )
        findings = classify_columns([col], profile)
        credential_findings = [f for f in findings if f.category == "Credential"]
        assert not credential_findings, (
            f"UUIDs under 'user_id' should not be Credential category, got {credential_findings}"
        )


class TestAi4PrivacyCredentialCoverage:
    """Full Ai4Privacy CREDENTIAL corpus coverage test.

    Matches the Sprint 7 acceptance criterion: per-value match_ratio >= 0.50.
    """

    def test_coverage_exceeds_50_percent(self, ai4privacy_credentials: list[str]) -> None:
        assert len(ai4privacy_credentials) >= 1000, (
            f"Expected >=1000 CREDENTIAL rows in Ai4Privacy sample, got {len(ai4privacy_credentials)}"
        )
        check = VALIDATORS["random_password"]
        matched = sum(1 for v in ai4privacy_credentials if check(v))
        match_ratio = matched / len(ai4privacy_credentials)
        assert match_ratio >= 0.50, (
            f"Ai4Privacy CREDENTIAL validator coverage {match_ratio:.1%} "
            f"below 50% target ({matched}/{len(ai4privacy_credentials)})"
        )
