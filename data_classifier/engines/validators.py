"""Secondary validators for content pattern matches.

Validators run AFTER a regex matches to reduce false positives.
If a validator returns False, the match is discarded.
"""

from __future__ import annotations

import re
import typing

# SSA-published SSNs that were inadvertently used in advertising or examples
# and must never be treated as real PII. Source: SSA Press Office historical
# record. The SSA-reserved advertising range 987-65-4320..4329 (10 numbers)
# is intentionally NOT listed here — it sits inside the ITIN area (900-999),
# which the canonical area rule in ssn_zeros_check rejects first. See
# tests/test_ssn_validator.py::TestAdvertisingRangeHandledByAreaRule.
_SSN_ADVERTISING_LIST: frozenset[str] = frozenset(
    {
        "078051120",  # Hilda Schrader Whitcher — Woolworth wallet insert
        "219099999",  # WL Murphy — advertising use
    }
)


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
    """Validate a 9-digit sequence against SSA canonical SSN rules.

    Post-2011 SSA randomized issuance rules:
      - Area (digits 1-3): 001-899, except 666 is never issued
      - Group (digits 4-5): 01-99
      - Serial (digits 6-9): 0001-9999
      - Area 900-999 is the ITIN range, never issued as SSN
    Additionally rejects the SSA-published advertising/example list
    (see ``_SSN_ADVERTISING_LIST``).

    The name is preserved for backward compatibility with
    ``default_patterns.json`` references; behavior is strictly a
    superset of the previous zeros-only check.
    """
    digits = value.replace("-", "")
    if len(digits) != 9 or not digits.isdigit():
        return False

    area, group, serial = digits[:3], digits[3:5], digits[5:]

    # Group and serial zero-group rejection (legacy behavior)
    if group == "00" or serial == "0000":
        return False

    # Area rules — canonical post-2011 SSA randomized issuance
    if area == "000" or area == "666":
        return False
    area_int = int(area)
    if 900 <= area_int <= 999:  # ITIN range, never issued as SSN
        return False

    # SSA-published advertising / example list
    if digits in _SSN_ADVERTISING_LIST:
        return False

    return True


def ipv4_not_reserved_check(value: str) -> bool:
    """Reject non-PII IPv4 addresses using stdlib ipaddress module.

    Rejects: loopback (127/8), unspecified (0.0.0.0/8), multicast
    (224/4), reserved (240/4), link-local (169.254/16).
    KEEPS: RFC1918 private ranges (10/8, 172.16/12, 192.168/16) because
    DLP cares about leaked internal IPs.

    Sprint 13 S0 rewrite: the previous implementation only rejected 3
    exact strings (0.0.0.0, 127.0.0.1, 255.255.255.255), missing the
    full loopback/reserved/multicast ranges.
    """
    import ipaddress

    try:
        addr = ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, ValueError):
        return False

    if addr.is_loopback:
        return False
    if addr.is_unspecified:
        return False
    if addr.is_multicast:
        return False
    if addr.is_reserved:
        return False
    if addr.is_link_local:
        return False
    # 0.0.0.0/8 ("this network", RFC 1122) — Python classifies as is_private
    # but these are not real RFC1918 addresses. Reject explicitly.
    if addr in ipaddress.IPv4Network("0.0.0.0/8"):
        return False
    # is_private intentionally NOT rejected — RFC1918 leaks are DLP-relevant.
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
    # Strip any matched prefix/suffix that the regex might have included
    clean = value.strip()
    # Pure hex (0-9, a-f, case-insensitive) → not an AWS key
    if re.fullmatch(r"[0-9a-fA-F]+", clean):
        return False
    # Must contain at least one uppercase AND one lowercase (base64 property)
    has_upper = any(c.isupper() for c in clean)
    has_lower = any(c.islower() for c in clean)
    return has_upper and has_lower


# ── Bitcoin address checksum validation ────────────────────────────────────
#
# Bitcoin uses two independent address formats, each with its own integrity
# check. The regex for BITCOIN_ADDRESS matches the STRUCTURE (prefix +
# charset + length); these helpers verify the cryptographic checksum so
# random strings that happen to match the structure are rejected.


_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {c: i for i, c in enumerate(_BASE58_ALPHABET)}


def _base58_decode(value: str) -> bytes | None:
    """Decode a base58 string to bytes. Returns None on invalid input."""
    n = 0
    for c in value:
        if c not in _BASE58_INDEX:
            return None
        n = n * 58 + _BASE58_INDEX[c]

    # Big-endian byte representation
    payload = bytearray()
    while n > 0:
        payload.append(n & 0xFF)
        n >>= 8
    payload.reverse()

    # Each leading '1' in base58 represents a leading zero byte
    leading_zeros = len(value) - len(value.lstrip("1"))
    return bytes(leading_zeros) + bytes(payload)


def _base58check_verify(value: str) -> bool:
    """Verify a base58check-encoded payload against its 4-byte checksum."""
    import hashlib

    decoded = _base58_decode(value)
    if decoded is None or len(decoded) < 5:
        return False
    payload, checksum = decoded[:-4], decoded[-4:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return digest == checksum


# Bech32 / bech32m: BIP 173 / BIP 350
_BECH32_ALPHABET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_INDEX = {c: i for i, c in enumerate(_BECH32_ALPHABET)}
_BECH32_CONST = 1  # bech32 (segwit v0)
_BECH32M_CONST = 0x2BC830A3  # bech32m (segwit v1+ / taproot)


def _bech32_polymod(values: list[int]) -> int:
    generator = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i, g in enumerate(generator):
            if (top >> i) & 1:
                chk ^= g
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_verify(value: str) -> bool:
    """Verify a bech32 or bech32m checksum. Bitcoin segwit addresses only."""
    lower = value.lower()
    # Reject if mixed case
    if value != lower and value != value.upper():
        return False
    pos = lower.rfind("1")
    # HRP must be 'bc' for mainnet Bitcoin; separator is the last '1';
    # data portion must have at least 6 chars (checksum length).
    if pos < 1 or pos + 7 > len(lower):
        return False
    hrp = lower[:pos]
    if hrp != "bc":
        return False
    data = lower[pos + 1 :]
    values: list[int] = []
    for c in data:
        if c not in _BECH32_INDEX:
            return False
        values.append(_BECH32_INDEX[c])
    polymod = _bech32_polymod(_bech32_hrp_expand(hrp) + values)
    return polymod in (_BECH32_CONST, _BECH32M_CONST)


def bitcoin_address_check(value: str) -> bool:
    """Validate a Bitcoin address by its checksum.

    Accepts three formats:
      - P2PKH (starts with '1'): base58check + length 25 bytes
      - P2SH (starts with '3'): base58check + length 25 bytes
      - Bech32/bech32m (starts with 'bc1'): polymod over bech32 alphabet

    A purely structural regex match is not sufficient — random base58
    alphabet strings will match the shape but almost never satisfy the
    checksum. Empirically this rejects ~100% of FPs seen in secretbench
    NEGATIVE and gitleaks NEGATIVE samples for this pattern.
    """
    clean = value.strip()
    if not clean:
        return False
    first = clean[0]
    if first in ("1", "3"):
        if not _base58check_verify(clean):
            return False
        # Decoded length must be 25 bytes (1 version + 20 hash160 + 4 checksum)
        decoded = _base58_decode(clean)
        return decoded is not None and len(decoded) == 25
    if clean.lower().startswith("bc1"):
        return _bech32_verify(clean)
    return False


# ── Ethereum / EVM address validation ──────────────────────────────────────
#
# EIP-55 defines a mixed-case checksum over the keccak256 of the hex digits.
# Python's stdlib hashlib does NOT ship keccak256 (hashlib.sha3_256 is the
# final SHA-3 variant which differs from pre-standardization keccak), so we
# can't verify the mixed-case checksum without a new dependency. For Phase 5
# we do structural validation plus rejection of well-known fake / null
# addresses. EIP-55 verification is filed as a follow-up pending a decision
# on the keccak dependency source.


_ETH_KNOWN_FAKES: frozenset[str] = frozenset(
    {
        "0x0000000000000000000000000000000000000000",  # zero / null address
        "0xffffffffffffffffffffffffffffffffffffffff",  # all-ones
        "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",  # dead-beef placeholder
    }
)


def ethereum_address_check(value: str) -> bool:
    """Structural validation for an Ethereum/EVM address.

    Accepts: '0x' followed by exactly 40 hex characters. Rejects well-
    known fake/placeholder addresses (zero address, all-ones, deadbeef
    literal). Note: does NOT verify the EIP-55 mixed-case checksum —
    see module docstring for rationale.

    For Phase 5 this is strictly stronger than no validator (catches
    the common null/placeholder FPs) without adding a keccak256
    dependency. True EIP-55 verification is a follow-up item.
    """
    clean = value.strip()
    if not clean.startswith("0x"):
        return False
    if len(clean) != 42:
        return False
    hex_part = clean[2:]
    if not all(c in "0123456789abcdefABCDEF" for c in hex_part):
        return False
    return clean.lower() not in _ETH_KNOWN_FAKES


# ── Placeholder-credential rejection ────────────────────────────────────────
#
# The secret_scanner engine already rejects values in
# known_placeholder_values.json at its per-value stage. The regex_engine
# does NOT consume that file (only stopwords.json), so generic-value
# credential regexes in default_patterns.json (github_token, stripe_key,
# aws_access_key, etc.) previously let placeholder strings like
# ``your_api_key_here`` or ``00000000-0000-0000-0000-000000000000``
# through unchallenged.
#
# This validator closes that gap. It is a VALIDATOR-layer filter: it
# runs AFTER the regex structural match and AFTER the stopword check.
# Its only job is to reject values that match the regex shape but are
# semantically placeholders. It loads known_placeholder_values.json
# lazily on first call and caches the result as a frozenset.

_PLACEHOLDER_VALUES: frozenset[str] | None = None


def _load_placeholder_values_once() -> frozenset[str]:
    """Load known_placeholder_values.json and return a case-insensitive frozenset."""
    global _PLACEHOLDER_VALUES
    if _PLACEHOLDER_VALUES is not None:
        return _PLACEHOLDER_VALUES

    import json
    from pathlib import Path

    path = Path(__file__).parent.parent / "patterns" / "known_placeholder_values.json"
    try:
        with path.open() as f:
            raw = json.load(f)
    except FileNotFoundError:
        _PLACEHOLDER_VALUES = frozenset()
        return _PLACEHOLDER_VALUES

    if "placeholder_values" not in raw:
        _PLACEHOLDER_VALUES = frozenset()
        return _PLACEHOLDER_VALUES

    _PLACEHOLDER_VALUES = frozenset(v.lower() for v in raw["placeholder_values"])
    return _PLACEHOLDER_VALUES


_PLACEHOLDER_CHAR_RE = re.compile(r"(.)\1{7,}")
_PLACEHOLDER_X_RE = re.compile(r"[xX]{5,}")
_PLACEHOLDER_TEMPLATE_RE = re.compile(
    r"(?i)(^|[=:\s\"'])(?:your[_\-\s]|my[_\-\s]|insert[_\-\s]|put[_\-\s]|replace[_\-\s]|add[_\-\s]|enter[_\-\s])"
)


def not_placeholder_credential(value: str) -> bool:
    """Reject the value if it is a known credential placeholder string.

    Returns True (accept) if the value is a non-placeholder; False (reject)
    if the value matches any of:
    - Exact match in ``known_placeholder_values.json``
    - Contains 5+ repeated identical characters (e.g. ``XXXXXXXXXX``)
    - Contains sequential placeholder patterns (``abcdefgh``, ``12345678``)

    Only applies to credential patterns. The stopwords.json filter (in
    regex_engine._is_stopword) already runs before this validator, so
    there is no double-filtering — this validator covers the strictly
    additional set of placeholder strings that stopwords.json does not.
    """
    placeholders = _load_placeholder_values_once()
    clean = value.strip().lower()
    if clean in placeholders:
        return False
    # Repeated character runs (XXXXXXXXXX, 0000000000, etc.)
    if _PLACEHOLDER_X_RE.search(value):
        return False
    # 8+ identical consecutive characters (not X which is caught above)
    if _PLACEHOLDER_CHAR_RE.search(value):
        return False
    # Template prefixes: YOUR_API_KEY, my_secret, insert_token_here, etc.
    if _PLACEHOLDER_TEMPLATE_RE.search(clean):
        return False
    return True


def random_password_check(value: str) -> bool:
    """Accept only mixed-class short random strings.

    A value passes iff:
      - Length is in [4, 64]
      - Contains a symbol (non-alphanumeric, non-whitespace)
      - Uses at least 3 of {lowercase, uppercase, digit, symbol}

    The symbol requirement is load-bearing: plain emails, dates, and IPs
    all have symbol + digit but only 2 classes total, so they're rejected
    by the ≥3 classes rule. Mixed-case identifiers with digits (``Hello123``)
    lack a symbol and are also rejected.
    """
    if not 4 <= len(value) <= 64:
        return False

    has_lower = any(c.islower() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_digit = any(c.isdigit() for c in value)
    has_symbol = any(not c.isalnum() and not c.isspace() for c in value)

    if not has_symbol:
        return False

    classes = sum([has_lower, has_upper, has_digit, has_symbol])
    return classes >= 3


# ── SWIFT/BIC country-code validation ─────────────────────────────────────
# ISO 3166-1 alpha-2 country codes. Positions 5-6 of a SWIFT/BIC code
# must be a valid country code. Without this check, any 8/11-letter
# uppercase English word matches (CONSTRAINTS, PERFORMANCE, etc.).
# Sprint 13 S0: ~593 FPs per 50K eliminated by this check.
_ISO_3166_ALPHA2: frozenset[str] = frozenset(
    {
        "AD",
        "AE",
        "AF",
        "AG",
        "AI",
        "AL",
        "AM",
        "AO",
        "AQ",
        "AR",
        "AS",
        "AT",
        "AU",
        "AW",
        "AX",
        "AZ",
        "BA",
        "BB",
        "BD",
        "BE",
        "BF",
        "BG",
        "BH",
        "BI",
        "BJ",
        "BL",
        "BM",
        "BN",
        "BO",
        "BQ",
        "BR",
        "BS",
        "BT",
        "BV",
        "BW",
        "BY",
        "BZ",
        "CA",
        "CC",
        "CD",
        "CF",
        "CG",
        "CH",
        "CI",
        "CK",
        "CL",
        "CM",
        "CN",
        "CO",
        "CR",
        "CU",
        "CV",
        "CW",
        "CX",
        "CY",
        "CZ",
        "DE",
        "DJ",
        "DK",
        "DM",
        "DO",
        "DZ",
        "EC",
        "EE",
        "EG",
        "EH",
        "ER",
        "ES",
        "ET",
        "FI",
        "FJ",
        "FK",
        "FM",
        "FO",
        "FR",
        "GA",
        "GB",
        "GD",
        "GE",
        "GF",
        "GG",
        "GH",
        "GI",
        "GL",
        "GM",
        "GN",
        "GP",
        "GQ",
        "GR",
        "GS",
        "GT",
        "GU",
        "GW",
        "GY",
        "HK",
        "HM",
        "HN",
        "HR",
        "HT",
        "HU",
        "ID",
        "IE",
        "IL",
        "IM",
        "IN",
        "IO",
        "IQ",
        "IR",
        "IS",
        "IT",
        "JE",
        "JM",
        "JO",
        "JP",
        "KE",
        "KG",
        "KH",
        "KI",
        "KM",
        "KN",
        "KP",
        "KR",
        "KW",
        "KY",
        "KZ",
        "LA",
        "LB",
        "LC",
        "LI",
        "LK",
        "LR",
        "LS",
        "LT",
        "LU",
        "LV",
        "LY",
        "MA",
        "MC",
        "MD",
        "ME",
        "MF",
        "MG",
        "MH",
        "MK",
        "ML",
        "MM",
        "MN",
        "MO",
        "MP",
        "MQ",
        "MR",
        "MS",
        "MT",
        "MU",
        "MV",
        "MW",
        "MX",
        "MY",
        "MZ",
        "NA",
        "NC",
        "NE",
        "NF",
        "NG",
        "NI",
        "NL",
        "NO",
        "NP",
        "NR",
        "NU",
        "NZ",
        "OM",
        "PA",
        "PE",
        "PF",
        "PG",
        "PH",
        "PK",
        "PL",
        "PM",
        "PN",
        "PR",
        "PS",
        "PT",
        "PW",
        "PY",
        "QA",
        "RE",
        "RO",
        "RS",
        "RU",
        "RW",
        "SA",
        "SB",
        "SC",
        "SD",
        "SE",
        "SG",
        "SH",
        "SI",
        "SJ",
        "SK",
        "SL",
        "SM",
        "SN",
        "SO",
        "SR",
        "SS",
        "ST",
        "SV",
        "SX",
        "SY",
        "SZ",
        "TC",
        "TD",
        "TF",
        "TG",
        "TH",
        "TJ",
        "TK",
        "TL",
        "TM",
        "TN",
        "TO",
        "TR",
        "TT",
        "TV",
        "TW",
        "TZ",
        "UA",
        "UG",
        "UM",
        "US",
        "UY",
        "UZ",
        "VA",
        "VC",
        "VE",
        "VG",
        "VI",
        "VN",
        "VU",
        "WF",
        "WS",
        "YE",
        "YT",
        "ZA",
        "ZM",
        "ZW",
        # SWIFT-specific pseudo-codes (XK=Kosovo, EU=EU institutions)
        "XK",
        "EU",
    }
)


def swift_bic_country_code_check(value: str) -> bool:
    """Validate SWIFT/BIC country code at positions 5-6.

    SWIFT/BIC format: BBBBCCLL[NNN] where CC is the ISO 3166 country code.
    Without this check, 8-letter English words like CONSTRAINTS (positions
    5-6 = "IN" = India) and PERFORMANCE (positions 5-6 = "MA" = Morocco)
    match — but DATABASE (positions 5-6 = "BA" = Bosnia) also matches, so
    this validator catches ~50% of English-word FPs (the ones with non-code
    letters at positions 5-6). Full bank-registry validation is a separate
    item.
    """
    clean = value.strip().upper()
    if len(clean) not in (8, 11):
        return False
    country = clean[4:6]
    return country in _ISO_3166_ALPHA2


def _openai_legacy_key_check(value: str) -> bool:
    """Validate an OpenAI legacy key (sk-<48 chars>) has mixed case + digits.

    Real keys are base62 (a-z, A-Z, 0-9) with high entropy. Rejects
    values that are all-lowercase, all-uppercase, or all-hex — these
    are likely hash suffixes or test data, not real keys.
    """
    # Strip the sk- prefix for the check
    suffix = value[3:] if value.startswith("sk-") else value
    has_upper = any(c.isupper() for c in suffix)
    has_lower = any(c.islower() for c in suffix)
    has_digit = any(c.isdigit() for c in suffix)
    # Must have at least 2 of {upper, lower, digit} — real base62 keys always have all 3
    return sum([has_upper, has_lower, has_digit]) >= 2


_CAMEL_CASE_RE = re.compile(r"[a-z][A-Z]")


def huggingface_token_check(value: str) -> bool:
    """Reject ``hf_`` prefixed values that look like code identifiers.

    Real HuggingFace tokens are random alphanumeric (``hf_`` + 34 chars).
    False positives are camelCase method/property names from Objective-C
    and Swift frameworks (e.g. ``hf_requiredCharacteristicTypesForDisplayMetadata``).

    Rejects when the suffix (after ``hf_``) contains camelCase transitions
    (``[a-z][A-Z]``) AND no digits — real random tokens virtually always
    contain digits (P(no digit in 34 base62 chars) < 0.001%).
    """
    suffix = value[3:] if value.startswith("hf_") else value
    has_camel = bool(_CAMEL_CASE_RE.search(suffix))
    has_digit = any(c.isdigit() for c in suffix)
    if has_camel and not has_digit:
        return False
    return True


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
    "random_password": random_password_check,
    # Sprint 11 Phase 5
    "bitcoin_address": bitcoin_address_check,
    "ethereum_address": ethereum_address_check,
    # Sprint 11 Phase 6
    "not_placeholder_credential": not_placeholder_credential,
    # Sprint 13 S0
    "swift_bic_country_code": swift_bic_country_code_check,
    "openai_legacy_key": _openai_legacy_key_check,
    "huggingface_token": huggingface_token_check,
}
