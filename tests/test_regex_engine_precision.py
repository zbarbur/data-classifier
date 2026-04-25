"""Sprint 13 S0-driven precision tests — SWIFT_BIC + IPv4 fixes."""

from __future__ import annotations

import pytest

from data_classifier.engines.validators import (
    ipv4_not_reserved_check,
    swift_bic_country_code_check,
)


class TestSwiftBicCountryCodeValidator:
    """SWIFT_BIC positions 5-6 must be a valid ISO 3166-1 alpha-2 code."""

    @pytest.mark.parametrize(
        "code",
        [
            "BARCGB22",  # Barclays, UK (GB) — has digit
            "CHASUS33",  # Chase, US — has digit
            "GLQDUS9XM2A",  # 11-char with digits
        ],
    )
    def test_real_bic_codes_with_digits_pass(self, code):
        assert swift_bic_country_code_check(code) is True

    @pytest.mark.parametrize(
        "code",
        [
            "DEUTDEFF",  # Deutsche Bank — all-alpha, needs column context
            "BNPAFRPPXXX",  # BNP Paribas — all-alpha 11-char
            "COBADEFFXXX",  # Commerzbank — all-alpha 11-char
        ],
    )
    def test_all_alpha_bic_rejected(self, code):
        """All-alpha BIC codes are rejected — indistinguishable from
        surnames (HOUTHTALING, CHRISTOPHER) without column context."""
        assert swift_bic_country_code_check(code) is False

    @pytest.mark.parametrize(
        "word",
        [
            "CONSTRAINTS",  # positions 5-6 = "RA" → valid? RA is not a country
            "RESPONSE",  # RE → Réunion — actually valid! but 8-char "RESPONSE" is only 8 chars
            "COMMANDS",  # AN → Netherlands Antilles (historical) — borderline
            "SERVQUAL",  # QU → not a code
            "PERFORMS",  # RM → not a code
            "OVERLAPS",  # LA → Laos — valid! This validator won't catch all English words
        ],
    )
    def test_english_word_fps_rejected(self, word):
        """All-alpha English words are always rejected regardless of country code."""
        assert swift_bic_country_code_check(word) is False

    def test_wrong_length_rejected(self):
        assert swift_bic_country_code_check("DEUT") is False
        assert swift_bic_country_code_check("DEUTDEFFXXXXXX") is False


class TestIpv4NotReservedCheck:
    """IPv4 validator using stdlib ipaddress module."""

    @pytest.mark.parametrize(
        "ip",
        [
            "192.168.1.1",  # RFC1918 private — KEEP (DLP-relevant)
            "10.0.0.1",  # RFC1918 private — KEEP
            "172.16.254.1",  # RFC1918 private — KEEP
            "8.8.8.8",  # Google DNS — public
            "1.2.3.4",  # Public
        ],
    )
    def test_valid_ips_pass(self, ip):
        assert ipv4_not_reserved_check(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "0.0.0.0",  # unspecified
            "0.0.18.105",  # 0.0.0.0/8 block — S0 FP repro
            "127.0.0.1",  # loopback
            "127.0.0.5",  # loopback range
            "127.255.255.254",  # loopback range
            "169.254.1.1",  # link-local
            "224.0.0.1",  # multicast
            "255.255.255.255",  # broadcast (reserved)
            "240.0.0.1",  # reserved (future use)
        ],
    )
    def test_reserved_ips_rejected(self, ip):
        assert ipv4_not_reserved_check(ip) is False

    def test_invalid_format_rejected(self):
        assert ipv4_not_reserved_check("not_an_ip") is False
        assert ipv4_not_reserved_check("999.999.999.999") is False


class TestIpv4RegexBoundary:
    """IPv4 regex should NOT match partial octets from longer strings."""

    def test_no_partial_match_from_five_octet_string(self):
        """256.0.0.18.105 should NOT produce a match on 0.0.18.105."""
        from data_classifier import classify_columns, load_profile
        from data_classifier.core.types import ColumnInput

        column = ColumnInput(
            column_id="test_boundary",
            column_name="data",
            sample_values=["256.0.0.18.105"] * 10,
        )
        findings = classify_columns([column], load_profile("standard"))
        ip_findings = [f for f in findings if f.entity_type == "IP_ADDRESS"]
        assert ip_findings == [], f"Should not match partial IP from 256.0.0.18.105, got {ip_findings}"

    def test_normal_ip_still_matches(self):
        from data_classifier import classify_columns, load_profile
        from data_classifier.core.types import ColumnInput

        column = ColumnInput(
            column_id="test_normal",
            column_name="ip",
            sample_values=["192.168.1.100"] * 10,
        )
        findings = classify_columns([column], load_profile("standard"))
        ip_findings = [f for f in findings if f.entity_type == "IP_ADDRESS"]
        assert len(ip_findings) >= 1
