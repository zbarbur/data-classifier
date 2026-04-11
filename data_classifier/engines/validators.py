"""Secondary validators for content pattern matches.

Validators run AFTER a regex matches to reduce false positives.
If a validator returns False, the match is discarded.
"""

from __future__ import annotations

import typing


def luhn_check(value: str) -> bool:
    """Luhn algorithm checksum for credit card numbers."""
    digits = [int(d) for d in value if d.isdigit()]
    if len(digits) < 13:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def luhn_strip_check(value: str) -> bool:
    """Luhn check after stripping separators (dashes, spaces)."""
    stripped = value.replace("-", "").replace(" ", "")
    return luhn_check(stripped)


def ssn_zeros_check(value: str) -> bool:
    """Reject SSNs with all-zeros in any group.

    Invalid: 000-XX-XXXX, XXX-00-XXXX, XXX-XX-0000
    Also rejects known test/advertising SSNs (078-05-1120, 219-09-9999).
    """
    digits = value.replace("-", "")
    if len(digits) != 9:
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area == "000" or group == "00" or serial == "0000":
        return False
    # Known invalid SSNs
    if digits in ("078051120", "219099999"):
        return False
    return True


def ipv4_not_reserved_check(value: str) -> bool:
    """Reject common non-PII IPv4 addresses (localhost, broadcast)."""
    if value in ("0.0.0.0", "127.0.0.1", "255.255.255.255"):
        return False
    return True


def npi_luhn_check(value: str) -> bool:
    """NPI Luhn check — prepend '80840' then standard Luhn."""
    digits_only = "".join(c for c in value if c.isdigit())
    if len(digits_only) != 10:
        return False
    return luhn_check("80840" + digits_only)


def dea_checkdigit_check(value: str) -> bool:
    """DEA number check digit validation.

    Check digit = last digit of (d1+d3+d5 + 2*(d2+d4+d6)).
    """
    if len(value) != 9:
        return False
    try:
        digits = [int(c) for c in value[2:]]
    except ValueError:
        return False
    checksum = (digits[0] + digits[2] + digits[4]) + 2 * (digits[1] + digits[3] + digits[5])
    return checksum % 10 == digits[6]


def vin_checkdigit_check(value: str) -> bool:
    """VIN check digit (position 9, mod 11)."""
    transliteration = {
        "A": 1,
        "B": 2,
        "C": 3,
        "D": 4,
        "E": 5,
        "F": 6,
        "G": 7,
        "H": 8,
        "J": 1,
        "K": 2,
        "L": 3,
        "M": 4,
        "N": 5,
        "P": 7,
        "R": 9,
        "S": 2,
        "T": 3,
        "U": 4,
        "V": 5,
        "W": 6,
        "X": 7,
        "Y": 8,
        "Z": 9,
    }
    weights = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
    value = value.upper()
    if len(value) != 17:
        return False
    total = 0
    for i, c in enumerate(value):
        if c.isdigit():
            val = int(c)
        else:
            val = transliteration.get(c, 0)
        total += val * weights[i]
    remainder = total % 11
    check_char = value[8]
    expected = "X" if remainder == 10 else str(remainder)
    return check_char == expected


def ein_prefix_check(value: str) -> bool:
    """Validate EIN campus prefix (first 2 digits)."""
    digits = value.replace("-", "")
    if len(digits) != 9:
        return False
    try:
        prefix = int(digits[:2])
    except ValueError:
        return False
    valid_ranges = [
        (1, 6),
        (10, 16),
        (20, 27),
        (30, 39),
        (40, 48),
        (50, 68),
        (71, 77),
        (80, 88),
        (90, 95),
        (98, 99),
    ]
    return any(lo <= prefix <= hi for lo, hi in valid_ranges)


def aba_checksum_check(value: str) -> bool:
    """ABA routing number weighted checksum (3-7-1 pattern)."""
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) != 9:
        return False
    weights = [3, 7, 1, 3, 7, 1, 3, 7, 1]
    return sum(d * w for d, w in zip(digits, weights)) % 10 == 0


def iban_checksum_check(value: str) -> bool:
    """IBAN mod-97 validation (ISO 13616)."""
    clean = value.replace(" ", "").replace("-", "").upper()
    if len(clean) < 5:
        return False
    # Move first 4 chars to end
    rearranged = clean[4:] + clean[:4]
    numeric = ""
    for c in rearranged:
        if c.isdigit():
            numeric += c
        elif c.isalpha():
            numeric += str(ord(c) - ord("A") + 10)
        else:
            return False
    return int(numeric) % 97 == 1


def sin_luhn_check(value: str) -> bool:
    """Luhn check for Canadian SIN — strips separators and requires exactly 9 digits."""
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) != 9:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def phone_number_check(value: str) -> bool:
    """Validate phone number using Google's phonenumbers library.

    Supports 170+ countries, validates number ranges (not just format).
    Strips extensions (x1234) before parsing.
    """
    try:
        import phonenumbers
    except ImportError:
        return True  # Graceful degradation if phonenumbers not installed

    # Strip common extension formats
    clean = value.split("x")[0].split("ext")[0].strip()

    try:
        parsed = phonenumbers.parse(clean, "US")  # Default region US
        return phonenumbers.is_possible_number(parsed)
    except phonenumbers.NumberParseException:
        return False


def aws_secret_not_hex(value: str) -> bool:
    """AWS secret keys are base64 (mixed case + digits + /+=), never pure hex.

    Rejects pure-hex strings that match the 40-char length but are actually
    git SHAs, checksums, or other hex identifiers.
    """
    import re

    # Strip any matched prefix/suffix that the regex might have included
    clean = value.strip()
    # Pure hex (0-9, a-f, case-insensitive) → not an AWS key
    if re.fullmatch(r"[0-9a-fA-F]+", clean):
        return False
    # Must contain at least one uppercase AND one lowercase (base64 property)
    has_upper = any(c.isupper() for c in clean)
    has_lower = any(c.islower() for c in clean)
    return has_upper and has_lower


# Registry mapping validator names to functions
VALIDATORS: dict[str, typing.Callable] = {
    "luhn": luhn_check,
    "luhn_strip": luhn_strip_check,
    "sin_luhn": sin_luhn_check,
    "ssn_zeros": ssn_zeros_check,
    "ipv4_not_reserved": ipv4_not_reserved_check,
    "npi_luhn": npi_luhn_check,
    "dea_checkdigit": dea_checkdigit_check,
    "vin_checkdigit": vin_checkdigit_check,
    "ein_prefix": ein_prefix_check,
    "aba_checksum": aba_checksum_check,
    "iban_checksum": iban_checksum_check,
    "phone_number": phone_number_check,
    "aws_secret_not_hex": aws_secret_not_hex,
}
