"""Sprint 13 S0-driven precision tests — SWIFT_BIC + IPv4 fixes."""

from __future__ import annotations

import pytest

from data_classifier.engines.validators import (
    austrian_svnr_check,
    dutch_bsn_check,
    french_nir_check,
    german_steuerid_check,
    ipv4_not_reserved_check,
    italian_codice_fiscale_check,
    spanish_dni_check,
    spanish_nie_check,
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


# ── Sprint 16 — EU national ID validators ────────────────────────────────


class TestGermanSteueridCheck:
    """German Steueridentifikationsnummer — 11 digits, iterative mod-10/11."""

    @pytest.mark.parametrize("value", ["12345678903", "65929810345"])
    def test_valid_ids_pass(self, value):
        assert german_steuerid_check(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "12345678900",  # bad check digit
            "12345678901",  # bad check digit
            "01234567890",  # leading zero
            "1234567890",  # too short
            "123456789012",  # too long
            "abcdefghijk",  # non-digits
        ],
    )
    def test_invalid_ids_rejected(self, value):
        assert german_steuerid_check(value) is False


class TestFrenchNirCheck:
    """French NIR/INSEE — 15 digits, control key = 97 - (first_13 % 97)."""

    @pytest.mark.parametrize(
        "value",
        [
            "254031088723464",
            "154021234500048",
            "293067890100059",
        ],
    )
    def test_valid_nir_pass(self, value):
        assert french_nir_check(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "254031088723499",  # bad control key
            "554031088723464",  # invalid gender digit (5)
            "12345678901234",  # too short (14 digits)
            "1234567890123456",  # too long (16 digits)
            "abcdefghijklmno",  # non-digits
        ],
    )
    def test_invalid_nir_rejected(self, value):
        assert french_nir_check(value) is False


class TestSpanishDniCheck:
    """Spanish DNI — 8 digits + check letter."""

    @pytest.mark.parametrize(
        "value",
        [
            "12345678Z",
            "00000001R",
            "98765432M",
        ],
    )
    def test_valid_dni_pass(self, value):
        assert spanish_dni_check(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "12345678A",  # wrong letter
            "1234567Z",  # too short
            "123456789Z",  # too long
            "ABCDEFGHZ",  # non-digits in number part
        ],
    )
    def test_invalid_dni_rejected(self, value):
        assert spanish_dni_check(value) is False


class TestSpanishNieCheck:
    """Spanish NIE — X/Y/Z + 7 digits + check letter."""

    @pytest.mark.parametrize(
        "value",
        [
            "X2482300W",
            "X0000000T",
            "Y1234567X",
        ],
    )
    def test_valid_nie_pass(self, value):
        assert spanish_nie_check(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "X2482300A",  # wrong letter
            "A1234567Z",  # invalid prefix
            "X123456Z",  # too short
            "X12345678Z",  # too long
        ],
    )
    def test_invalid_nie_rejected(self, value):
        assert spanish_nie_check(value) is False


class TestItalianCodiceFiscaleCheck:
    """Italian Codice Fiscale — 16 chars with complex check character."""

    @pytest.mark.parametrize(
        "value",
        [
            "RSSMRA85M01H501Q",
            "BNCLRA92E63H501Y",
        ],
    )
    def test_valid_cf_pass(self, value):
        assert italian_codice_fiscale_check(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "RSSMRA85M01H501Z",  # wrong check character
            "RSSMRA85M01H501A",  # wrong check character
            "ABCDEF12G34H567",  # too short (15 chars)
            "1234567890123456",  # all digits
        ],
    )
    def test_invalid_cf_rejected(self, value):
        assert italian_codice_fiscale_check(value) is False


class TestDutchBsnCheck:
    """Dutch BSN — 9 digits, 11-check with weights [9,8,7,6,5,4,3,2,-1]."""

    @pytest.mark.parametrize(
        "value",
        [
            "111222333",
            "123456782",
            "999999990",
        ],
    )
    def test_valid_bsn_pass(self, value):
        assert dutch_bsn_check(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "123456789",  # bad checksum
            "012345678",  # leading zero
            "12345678",  # too short
            "1234567890",  # too long
            "abcdefghi",  # non-digits
        ],
    )
    def test_invalid_bsn_rejected(self, value):
        assert dutch_bsn_check(value) is False


class TestAustrianSvnrCheck:
    """Austrian SVNR — 10 digits, check digit at position 4."""

    @pytest.mark.parametrize("value", ["1237010180"])
    def test_valid_svnr_pass(self, value):
        assert austrian_svnr_check(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "1234010180",  # wrong check digit
            "0123456789",  # leading zero
            "123456789",  # too short
            "12345678901",  # too long
            "abcdefghij",  # non-digits
        ],
    )
    def test_invalid_svnr_rejected(self, value):
        assert austrian_svnr_check(value) is False
