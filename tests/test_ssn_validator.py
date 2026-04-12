"""Unit tests for the SSN validator (``ssn_zeros_check``).

Covers the Sprint 6 expansion to canonical post-2011 SSA randomized
issuance rules plus the SSA-published advertising list.
"""

from __future__ import annotations

import pytest

from data_classifier.engines import validators
from data_classifier.engines.validators import ssn_zeros_check


class TestSsnAreaRules:
    """Canonical SSA post-2011 area-number rules."""

    @pytest.mark.parametrize(
        "ssn",
        [
            "000-12-3456",  # area 000
            "666-12-3456",  # area 666 (never issued)
            "900-12-3456",  # area 900 (ITIN)
            "950-12-3456",  # area 950 (ITIN)
            "999-12-3456",  # area 999 (ITIN)
        ],
    )
    def test_invalid_area_rejected(self, ssn: str) -> None:
        assert ssn_zeros_check(ssn) is False

    @pytest.mark.parametrize(
        "ssn",
        [
            "001-12-3456",  # area 001 (lowest valid)
            "123-45-6789",  # generic valid
            "665-12-3456",  # just below 666
            "667-12-3456",  # just above 666
            "899-12-3456",  # area 899 (highest valid)
        ],
    )
    def test_valid_area_accepted(self, ssn: str) -> None:
        assert ssn_zeros_check(ssn) is True


class TestSsnZeroRules:
    """Legacy zero-group rejection must still hold."""

    @pytest.mark.parametrize(
        "ssn",
        [
            "123-00-4567",  # group 00
            "123-45-0000",  # serial 0000
            "000-45-6789",  # area 000 (also caught by area rule)
        ],
    )
    def test_zero_groups_rejected(self, ssn: str) -> None:
        assert ssn_zeros_check(ssn) is False


class TestSsnAdvertisingList:
    """SSA-published advertising / example SSNs must be rejected."""

    @pytest.mark.parametrize(
        "ssn",
        [
            "078-05-1120",  # Hilda Whitcher — Woolworth wallet insert
            "219-09-9999",  # WL Murphy — advertising use
            "987-65-4320",  # SSA advertising range lower bound
            "987-65-4321",
            "987-65-4325",
            "987-65-4329",  # SSA advertising range upper bound
        ],
    )
    def test_advertising_ssns_rejected(self, ssn: str) -> None:
        assert ssn_zeros_check(ssn) is False

    def test_famous_advertising_neighbors_accepted(self) -> None:
        """Sanity-check that near-miss SSNs to the famous advertising
        numbers (078-05-1121, 219-09-9998) are NOT rejected — only
        the exact SSA-published entries are on the list. Both areas
        (078, 219) are within the canonical 001-899 range.
        """
        assert ssn_zeros_check("078-05-1121") is True
        assert ssn_zeros_check("219-09-9998") is True

    def test_987_range_fully_rejected_via_area_rule(self) -> None:
        """987 is above the 001-899 canonical area range, so every
        987-xx-xxxx is rejected regardless of the advertising list.
        This test documents that the area rule subsumes the advertising
        list for the 987-65-43xx block.
        """
        assert ssn_zeros_check("987-65-4319") is False  # area > 899
        assert ssn_zeros_check("987-65-4330") is False  # area > 899


class TestAdvertisingRangeHandledByAreaRule:
    """The SSA-published advertising range 987-65-4320..4329 lives entirely
    inside the ITIN area (900-999), which is rejected by the canonical area
    rule *before* the advertising list check runs. These tests pin down that
    invariant so the advertising list can shed those 10 dead entries without
    weakening rejection.
    """

    @pytest.mark.parametrize(
        "ssn",
        [f"98765{n:04d}" for n in range(4320, 4330)],
    )
    def test_advertising_range_rejected(self, ssn: str) -> None:
        """All 10 987-65-43xx values must be rejected — no matter the mechanism."""
        assert ssn_zeros_check(ssn) is False

    @pytest.mark.parametrize(
        "ssn",
        [f"98765{n:04d}" for n in range(4320, 4330)],
    )
    def test_advertising_range_rejected_even_with_list_stripped(
        self, ssn: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stronger invariant: stripping the 987-65-43xx entries from
        ``_SSN_ADVERTISING_LIST`` must not change the rejection outcome.
        This exercises the post-refactor state against current code and
        catches any future regression that weakens the area rule.
        """
        stripped = frozenset({"078051120", "219099999"})
        monkeypatch.setattr(validators, "_SSN_ADVERTISING_LIST", stripped)
        assert ssn_zeros_check(ssn) is False


class TestSsnMalformed:
    """Malformed inputs must be rejected safely, not raise."""

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "12345",
            "123-45-67890",  # 10 digits
            "abc-de-fghi",
            "12-34-5678",  # wrong shape (8 digits)
            "123-4X-6789",  # non-digit inside
        ],
    )
    def test_malformed_rejected(self, bad: str) -> None:
        assert ssn_zeros_check(bad) is False


class TestSsnNoDashesFormat:
    """Validator must also work for 9-digit strings without dashes."""

    @pytest.mark.parametrize(
        "ssn",
        [
            "123456789",
            "001000001",  # valid area, but group 00
        ],
    )
    def test_bare_digits(self, ssn: str) -> None:
        # 123456789 is valid; 001000001 should be rejected (group 00)
        expected = ssn == "123456789"
        assert ssn_zeros_check(ssn) is expected

    def test_aba_routing_with_zero_group_rejected(self) -> None:
        """Common ABA routing numbers frequently have zero-filled
        group or serial segments once split SSN-style, which the
        zero-group rules already reject.

        Example: 021000021 (Federal Reserve NY ABA). Split SSN-style:
        area=021, group=00, serial=0021 — rejected via group==00.
        This is exactly the class of false positive the Sprint 6
        hardening targets on Nemotron col_0.
        """
        assert ssn_zeros_check("021000021") is False
        # 011000015 (FRB Boston): group=00 → rejected
        assert ssn_zeros_check("011000015") is False
        # 121000248 (Wells Fargo): area=121 valid, group=00 → rejected
        assert ssn_zeros_check("121000248") is False

    def test_itin_style_9_digit_rejected(self) -> None:
        """9-digit numbers in the 900-999 area (ITIN range) must
        be rejected even without dashes."""
        assert ssn_zeros_check("912345678") is False
