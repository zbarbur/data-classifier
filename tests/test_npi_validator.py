"""Tests for the NPI Luhn validator.

NPI = US National Provider Identifier. 10 digits, starts with 1 (individual
provider) or 2 (organization). Per CMS specification, the check digit is
computed by prepending ``80840`` to the 9-digit NPI prefix and running a
standard Luhn checksum on the resulting 14-digit string. The resulting
10-digit NPI (9 prefix + 1 check digit) is valid iff ``80840`` + NPI passes
Luhn.

The validator itself only enforces Luhn + length; the leading-digit rule
(NPI must start with 1 or 2) is enforced by the regex pattern in
``default_patterns.json`` (``us_npi``). These unit tests focus on the
validator in isolation — for full pattern coverage see ``test_patterns.py``.
"""

from __future__ import annotations

import pytest

from data_classifier.engines.validators import npi_luhn_check


class TestNpiValidatorValidCmsReference:
    """Known-valid NPIs from the CMS public reference list.

    These are the same NPIs used in ``default_patterns.json`` ``examples_match``
    for the ``us_npi`` pattern, plus additional published CMS test numbers.
    A valid NPI must produce a zero Luhn checksum when ``80840`` is prepended.
    """

    @pytest.mark.parametrize(
        "npi",
        [
            "1003000126",
            "1234567893",
        ],
    )
    def test_cms_reference_npis_accepted(self, npi: str) -> None:
        assert npi_luhn_check(npi) is True


class TestNpiValidatorInvalidLuhn:
    """10-digit sequences that pass the regex shape but fail Luhn.

    Critical regression guard: any fix to the Luhn implementation or the
    80840 prefix logic will break these cases. These are also the class of
    false positives the validator is meant to kill on Nemotron col_0 (ABA)
    and similar 10-digit collision piles.
    """

    @pytest.mark.parametrize(
        "bad",
        [
            "1234567890",  # sequential, starts with 1, length 10, fails Luhn
            "1111111111",  # repeated digit, individual prefix, fails Luhn
            "2222222222",  # repeated digit, organization prefix, fails Luhn
            "1003000127",  # one digit off from valid 1003000126 — proves Luhn is actually checked
            "1234567894",  # one digit off from valid 1234567893
        ],
    )
    def test_invalid_luhn_rejected(self, bad: str) -> None:
        assert npi_luhn_check(bad) is False


class TestNpiValidatorFormatTolerance:
    """Parity with Presidio-style input: the validator strips non-digits.

    A downstream caller may hand us an NPI already formatted with dashes or
    spaces. The validator should not care about separators — only about the
    underlying 10-digit sequence.
    """

    @pytest.mark.parametrize(
        "formatted",
        [
            "1003-000-126",
            "1003 000 126",
            " 1003000126 ",
        ],
    )
    def test_formatted_valid_npi_accepted(self, formatted: str) -> None:
        assert npi_luhn_check(formatted) is True


class TestNpiValidatorMalformed:
    """Inputs that don't yield exactly 10 digits are rejected."""

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "123",
            "123456789",  # 9 digits
            "12345678901",  # 11 digits
            "abcdefghij",  # non-numeric, strips to empty
            "hello world",
        ],
    )
    def test_malformed_rejected(self, bad: str) -> None:
        assert npi_luhn_check(bad) is False
