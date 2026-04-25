"""Tests for EU government ID validators (Sprint 15)."""

from __future__ import annotations

import pytest

from data_classifier.engines.validators import (
    bulgarian_egn_check,
    czech_rodne_cislo_check,
    danish_cpr_check,
    swiss_ahv_check,
)


class TestBulgarianEGN:
    def test_valid_egn(self):
        base = "750101001"
        weights = [2, 4, 8, 5, 10, 9, 7, 3, 6]
        total = sum(int(base[i]) * weights[i] for i in range(9))
        remainder = total % 11
        check = 0 if remainder >= 10 else remainder
        valid_egn = base + str(check)
        assert bulgarian_egn_check(valid_egn) is True

    def test_invalid_check_digit(self):
        base = "750101001"
        weights = [2, 4, 8, 5, 10, 9, 7, 3, 6]
        total = sum(int(base[i]) * weights[i] for i in range(9))
        remainder = total % 11
        check = 0 if remainder >= 10 else remainder
        wrong_check = (check + 1) % 10
        invalid_egn = base + str(wrong_check)
        assert bulgarian_egn_check(invalid_egn) is False

    def test_wrong_length(self):
        assert bulgarian_egn_check("12345") is False

    def test_non_numeric(self):
        assert bulgarian_egn_check("abcdefghij") is False


class TestCzechRodneCislo:
    def test_valid_rodne_cislo(self):
        # Find a 10-digit number with valid month/day divisible by 11
        # Start with 8001010000 and find nearest multiple of 11
        base_num = 8001010000
        remainder = base_num % 11
        valid_num = base_num + (11 - remainder) if remainder != 0 else base_num
        valid_str = str(valid_num)
        # Verify month/day are still valid after adjustment
        assert czech_rodne_cislo_check(valid_str) is True

    def test_valid_with_slash(self):
        # Same number but with slash separator
        base_num = 8001010000
        remainder = base_num % 11
        valid_num = base_num + (11 - remainder) if remainder != 0 else base_num
        valid_str = str(valid_num)
        with_slash = valid_str[:6] + "/" + valid_str[6:]
        assert czech_rodne_cislo_check(with_slash) is True

    def test_invalid_mod11(self):
        # A number that is NOT divisible by 11
        base_num = 8001010000
        remainder = base_num % 11
        valid_num = base_num + (11 - remainder) if remainder != 0 else base_num
        invalid_num = valid_num + 1  # off by one, not divisible by 11
        assert czech_rodne_cislo_check(str(invalid_num)) is False

    def test_female_month(self):
        # Month +50 for females (e.g., month 51 = January female)
        base_num = 8051010000
        remainder = base_num % 11
        valid_num = base_num + (11 - remainder) if remainder != 0 else base_num
        valid_str = str(valid_num)
        assert czech_rodne_cislo_check(valid_str) is True

    def test_invalid_month(self):
        assert czech_rodne_cislo_check("8013011234") is False

    def test_invalid_day(self):
        assert czech_rodne_cislo_check("8001321234") is False

    def test_wrong_length(self):
        assert czech_rodne_cislo_check("123456") is False


class TestSwissAHV:
    def test_valid_ahv(self):
        # Compute a valid AHV: 756 prefix, 12 digits + check
        base = "756123456780"
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(base))
        check = (10 - (total % 10)) % 10
        valid_ahv = base + str(check)
        assert swiss_ahv_check(valid_ahv) is True

    def test_invalid_check_digit(self):
        base = "756123456780"
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(base))
        check = (10 - (total % 10)) % 10
        wrong_check = (check + 1) % 10
        invalid_ahv = base + str(wrong_check)
        assert swiss_ahv_check(invalid_ahv) is False

    def test_valid_with_dots(self):
        base = "756123456780"
        total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(base))
        check = (10 - (total % 10)) % 10
        valid_ahv = base + str(check)
        # Format with dots: 756.1234.5678.0X
        dotted = f"{valid_ahv[:3]}.{valid_ahv[3:7]}.{valid_ahv[7:11]}.{valid_ahv[11:]}"
        assert swiss_ahv_check(dotted) is True

    def test_wrong_prefix(self):
        assert swiss_ahv_check("123.4567.8901.23") is False

    def test_wrong_length(self):
        assert swiss_ahv_check("756.1234") is False


class TestDanishCPR:
    def test_valid_cpr(self):
        # Compute a valid CPR: DDMMYY + NNNN, weighted sum mod 11 == 0
        # Start with 0101800000 (01 Jan 1980) and find sequence digits
        base = "010180"
        weights = [4, 3, 2, 7, 6, 5, 4, 3, 2, 1]
        # Try sequence numbers until we find one that passes mod 11
        for seq in range(10000):
            candidate = base + f"{seq:04d}"
            total = sum(int(candidate[i]) * weights[i] for i in range(10))
            if total % 11 == 0:
                assert danish_cpr_check(candidate) is True
                break
        else:
            pytest.fail("Could not find a valid CPR number")

    def test_invalid_check(self):
        # Find a valid one, then corrupt the last digit
        base = "010180"
        weights = [4, 3, 2, 7, 6, 5, 4, 3, 2, 1]
        for seq in range(10000):
            candidate = base + f"{seq:04d}"
            total = sum(int(candidate[i]) * weights[i] for i in range(10))
            if total % 11 == 0:
                # Corrupt last digit
                last = int(candidate[9])
                corrupted = candidate[:9] + str((last + 1) % 10)
                assert danish_cpr_check(corrupted) is False
                break

    def test_valid_with_dash(self):
        base = "010180"
        weights = [4, 3, 2, 7, 6, 5, 4, 3, 2, 1]
        for seq in range(10000):
            candidate = base + f"{seq:04d}"
            total = sum(int(candidate[i]) * weights[i] for i in range(10))
            if total % 11 == 0:
                with_dash = candidate[:6] + "-" + candidate[6:]
                assert danish_cpr_check(with_dash) is True
                break

    def test_invalid_day(self):
        assert danish_cpr_check("320187-1234") is False

    def test_invalid_month(self):
        assert danish_cpr_check("011387-1234") is False

    def test_wrong_length(self):
        assert danish_cpr_check("12345") is False
