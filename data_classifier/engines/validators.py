"""Secondary validators for content pattern matches.

Validators run AFTER a regex matches to reduce false positives.
If a validator returns False, the match is discarded.
"""

from __future__ import annotations


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


# Registry mapping validator names to functions
VALIDATORS: dict[str, callable] = {
    "luhn": luhn_check,
    "luhn_strip": luhn_strip_check,
    "ssn_zeros": ssn_zeros_check,
    "ipv4_not_reserved": ipv4_not_reserved_check,
    "iban_checksum": lambda _v: True,  # TODO: implement IBAN mod-97 check
}
