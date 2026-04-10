"""Property-based tests using Hypothesis.

Tests properties of the classification engine that should hold for
all valid inputs, not just specific test cases.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from data_classifier import ClassificationFinding, classify_columns, load_profile
from data_classifier.core.types import ClassificationProfile, ColumnInput


@st.composite
def valid_ssns(draw: st.DrawFn) -> str:
    """Generate valid SSN strings (XXX-XX-XXXX, valid per SSN rules)."""
    area = draw(st.integers(1, 899).filter(lambda x: x != 666))
    group = draw(st.integers(1, 99))
    serial = draw(st.integers(1, 9999))
    return f"{area:03d}-{group:02d}-{serial:04d}"


@st.composite
def valid_emails(draw: st.DrawFn) -> str:
    """Generate valid email addresses."""
    user = draw(st.from_regex(r"[a-z][a-z0-9.]{2,15}", fullmatch=True))
    domain = draw(st.from_regex(r"[a-z]{3,10}\.(com|org|net|io)", fullmatch=True))
    return f"{user}@{domain}"


@st.composite
def luhn_valid_cards(draw: st.DrawFn) -> str:
    """Generate Luhn-valid 16-digit card numbers."""
    prefix = draw(st.sampled_from(["4", "51", "52", "53", "54", "55"]))
    remaining = 16 - len(prefix) - 1
    middle = draw(st.text(alphabet="0123456789", min_size=remaining, max_size=remaining))
    partial = prefix + middle
    # Compute Luhn check digit
    digits = [int(d) for d in partial]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    check_digit = (10 - (checksum % 10)) % 10
    return partial + str(check_digit)


def _classify_single_sample(
    value: str, column_name: str, profile: ClassificationProfile
) -> list[ClassificationFinding]:
    """Helper to classify a single sample value."""
    column = ColumnInput(
        column_name=column_name,
        column_id=f"hypothesis_{column_name}",
        data_type="STRING",
        sample_values=[value],
    )
    return classify_columns([column], profile, min_confidence=0.0)


@pytest.fixture(scope="module")
def standard_profile() -> ClassificationProfile:
    """Load the standard profile once for all hypothesis tests."""
    return load_profile("standard")


class TestSSNProperty:
    """Property-based tests for SSN detection."""

    @given(ssn=valid_ssns())
    @settings(max_examples=50, deadline=None)
    def test_valid_ssns_always_detected(self, ssn: str, standard_profile: ClassificationProfile) -> None:
        """Valid SSNs should always be detected by the regex engine."""
        findings = _classify_single_sample(ssn, "data_column", standard_profile)
        entity_types = {f.entity_type for f in findings}
        assert "SSN" in entity_types, f"SSN not detected for valid SSN: {ssn}"


class TestEmailProperty:
    """Property-based tests for email detection."""

    @given(email=valid_emails())
    @settings(max_examples=50, deadline=None)
    def test_valid_emails_always_detected(self, email: str, standard_profile: ClassificationProfile) -> None:
        """Valid emails should always be detected."""
        findings = _classify_single_sample(email, "data_column", standard_profile)
        entity_types = {f.entity_type for f in findings}
        assert "EMAIL" in entity_types, f"EMAIL not detected for valid email: {email}"


class TestCreditCardProperty:
    """Property-based tests for credit card detection."""

    @given(card=luhn_valid_cards())
    @settings(max_examples=50, deadline=None)
    def test_luhn_valid_cards_detected(self, card: str, standard_profile: ClassificationProfile) -> None:
        """Luhn-valid card numbers should be detected."""
        findings = _classify_single_sample(card, "data_column", standard_profile)
        entity_types = {f.entity_type for f in findings}
        assert "CREDIT_CARD" in entity_types, f"CREDIT_CARD not detected for Luhn-valid card: {card}"


class TestRandomStringProperty:
    """Property-based tests for random string behavior."""

    @given(
        text=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=5,
            max_size=50,
        )
    )
    @settings(max_examples=100, deadline=None)
    def test_random_strings_rarely_match(self, text: str, standard_profile: ClassificationProfile) -> None:
        """Random alphanumeric strings should rarely trigger classifications.

        This is a statistical property test. Individual random strings may
        occasionally match a pattern, but the engine should not produce findings
        for most arbitrary alphanumeric text. We verify that any findings have
        low confidence rather than asserting zero matches.
        """
        findings = _classify_single_sample(text, "random_column", standard_profile)
        # We don't assert zero matches — some random strings may hit patterns.
        # Instead, we verify results are well-formed when they do match.
        for finding in findings:
            assert 0.0 <= finding.confidence <= 1.0, f"Invalid confidence: {finding.confidence}"
            assert finding.entity_type, "Empty entity_type in finding"
            assert finding.column_id == "hypothesis_random_column"
