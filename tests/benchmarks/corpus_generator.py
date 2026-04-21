"""Synthetic corpus generator for accuracy and performance benchmarking.

Generates labeled data at two levels:
1. Column-level: ColumnInput objects for testing classify_columns()
2. Sample-level: raw (value, entity_type) pairs for testing pattern matching directly

Includes format variations (formatted/unformatted, embedded in text, partial),
adversarial near-misses, and negative data.

Usage:
    from tests.benchmarks.corpus_generator import generate_corpus, generate_raw_samples
    corpus = generate_corpus(samples_per_type=200, locale="en_US")
    raw = generate_raw_samples(count_per_type=500)
"""

from __future__ import annotations

import random
import string
import uuid

from faker import Faker

from data_classifier.core.types import ColumnInput

# ── Custom generators for check-digit-validated patterns ─────────────────────


def _luhn_check_digit(partial: str) -> str:
    """Compute Luhn check digit for a partial number string."""
    digits = [int(d) for d in partial]
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return str((10 - (checksum % 10)) % 10)


def _generate_valid_npi(n: int) -> list[str]:
    """Generate Luhn-valid NPI numbers (prefix 80840 + 10 digits)."""
    results = []
    for _ in range(n):
        base = f"{random.randint(1, 2)}{random.randint(0, 99999999):08d}"
        check = _luhn_check_digit("80840" + base)
        results.append(base + check)
    return results


def _generate_valid_dea(n: int) -> list[str]:
    """Generate valid DEA numbers with correct check digits."""
    results = []
    first_letters = list("ABFGMPR")
    for _ in range(n):
        prefix = random.choice(first_letters) + chr(random.randint(65, 90))
        digits = [random.randint(0, 9) for _ in range(6)]
        checksum = (digits[0] + digits[2] + digits[4]) + 2 * (digits[1] + digits[3] + digits[5])
        check = checksum % 10
        results.append(prefix + "".join(str(d) for d in digits) + str(check))
    return results


def _generate_valid_aba(n: int) -> list[str]:
    """Generate ABA routing numbers with valid checksums (3-7-1 weighted)."""
    results = []
    for _ in range(n):
        digits = [random.randint(0, 9) for _ in range(8)]
        weights = [3, 7, 1, 3, 7, 1, 3, 7]
        partial = sum(d * w for d, w in zip(digits, weights))
        check = (10 - (partial % 10)) % 10
        results.append("".join(str(d) for d in digits) + str(check))
    return results


def _generate_valid_sin(n: int) -> list[str]:
    """Generate Luhn-valid Canadian SIN numbers in various formats."""
    results = []
    for _ in range(n):
        digits = [random.randint(0, 9) for _ in range(8)]
        checksum = 0
        for i, d in enumerate(digits):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
        check = (10 - (checksum % 10)) % 10
        d = digits + [check]
        # Vary format: spaces, dashes, or no separator
        fmt = random.choice(["space", "dash", "none"])
        if fmt == "space":
            results.append(f"{d[0]}{d[1]}{d[2]} {d[3]}{d[4]}{d[5]} {d[6]}{d[7]}{d[8]}")
        elif fmt == "dash":
            results.append(f"{d[0]}{d[1]}{d[2]}-{d[3]}{d[4]}{d[5]}-{d[6]}{d[7]}{d[8]}")
        else:
            results.append("".join(str(x) for x in d))
    return results


def _generate_mbi(n: int) -> list[str]:
    """Generate valid MBI format strings (positional alphanumeric)."""
    alpha = "ACDEFGHJKMNPQRTUVWXY"  # no S,L,O,I,B,Z
    alphanum = alpha + "0123456789"
    results = []
    for _ in range(n):
        chars = [
            str(random.randint(1, 9)),
            random.choice(alpha),
            random.choice(alphanum),
            str(random.randint(0, 9)),
            random.choice(alpha),
            random.choice(alphanum),
            str(random.randint(0, 9)),
            random.choice(alpha),
            random.choice(alpha),
            str(random.randint(0, 9)),
            str(random.randint(0, 9)),
        ]
        results.append("".join(chars))
    return results


def _generate_valid_cc(fake: Faker, n: int) -> list[str]:
    """Generate credit card numbers in various formats (with/without separators)."""
    results = []
    for _ in range(n):
        cc = fake.credit_card_number()
        fmt = random.choice(["plain", "spaced", "dashed"])
        if fmt == "spaced" and len(cc) == 16:
            cc = f"{cc[:4]} {cc[4:8]} {cc[8:12]} {cc[12:]}"
        elif fmt == "dashed" and len(cc) == 16:
            cc = f"{cc[:4]}-{cc[4:8]}-{cc[8:12]}-{cc[12:]}"
        results.append(cc)
    return results


def _generate_ssn_variants(fake: Faker, n: int) -> list[str]:
    """Generate SSNs in both formatted (XXX-XX-XXXX) and unformatted (XXXXXXXXX) styles."""
    results = []
    for _ in range(n):
        ssn = fake.ssn()  # Returns XXX-XX-XXXX
        if random.random() < 0.3:
            ssn = ssn.replace("-", "")  # 30% unformatted
        results.append(ssn)
    return results


def _generate_embedded_values(values: list[str], entity_type: str) -> list[str]:
    """Wrap some values in surrounding text to simulate free-text columns."""
    templates = {
        "SSN": ["SSN: {v}", "Social Security Number is {v}", "my ssn {v}"],
        "EMAIL": ["contact: {v}", "send to {v} please", "{v}"],
        "PHONE": ["call {v}", "phone: {v}", "reach me at {v}"],
        "CREDIT_CARD": ["card ending {v}", "payment via {v}", "{v}"],
        "NPI": ["provider NPI: {v}", "NPI {v}", "{v}"],
        "DEFAULT": ["value: {v}", "{v}", "data {v} here"],
    }
    tmpl_list = templates.get(entity_type, templates["DEFAULT"])
    results = []
    for v in values:
        if random.random() < 0.2:  # 20% embedded in text
            tmpl = random.choice(tmpl_list)
            results.append(tmpl.format(v=v))
        else:
            results.append(v)
    return results


# ── Entity type generators ───────────────────────────────────────────────────

_ENTITY_GENERATORS: dict[str, dict] = {
    "SSN": {
        "column_name": "test_ssn_column",
        "generator": lambda fake, n: _generate_ssn_variants(fake, n),
    },
    "EMAIL": {
        "column_name": "test_email_column",
        "generator": lambda fake, n: [fake.email() for _ in range(n)],
    },
    "PHONE": {
        "column_name": "test_phone_column",
        "generator": lambda fake, n: [fake.phone_number() for _ in range(n)],
    },
    "CREDIT_CARD": {
        "column_name": "test_credit_card_column",
        "generator": lambda fake, n: _generate_valid_cc(fake, n),
    },
    "DATE": {
        "column_name": "test_dob_column",
        "generator": lambda fake, n: [fake.date_of_birth().strftime("%m/%d/%Y") for _ in range(n)],
    },
    "IP_ADDRESS": {
        "column_name": "test_ip_column",
        "generator": lambda fake, n: [fake.ipv4() for _ in range(n)],
    },
    "URL": {
        "column_name": "test_url_column",
        "generator": lambda fake, n: [fake.url() for _ in range(n)],
    },
    "PERSON_NAME": {
        "column_name": "test_person_name_column",
        "generator": lambda fake, n: [fake.name() for _ in range(n)],
    },
    "ADDRESS": {
        "column_name": "test_address_column",
        "generator": lambda fake, n: [fake.address() for _ in range(n)],
    },
    "IBAN": {
        "column_name": "test_iban_column",
        "generator": lambda fake, n: [fake.iban() for _ in range(n)],
    },
    "SWIFT_BIC": {
        "column_name": "test_swift_column",
        "generator": lambda fake, n: [fake.swift() for _ in range(n)],
    },
    "EIN": {
        "column_name": "test_ein_column",
        "generator": lambda _fake, n: [
            f"{random.choice([12, 20, 35, 50, 80, 95]):02d}-{random.randint(1000000, 9999999)}" for _ in range(n)
        ],
    },
    "VIN": {
        "column_name": "test_vin_column",
        "generator": lambda _fake, n: random.choices(
            [
                "1HGBH41JXMN109186",  # Honda
                "5YJSA1DG9DFP14705",  # Tesla
                "2T1BURHE5JC034461",  # Toyota
                "3VWFE21C04M000001",  # Volkswagen
                "1N4AL3AP8JC231503",  # Nissan
            ],
            k=n,
        ),
    },
    "BITCOIN_ADDRESS": {
        "column_name": "test_bitcoin_column",
        "generator": lambda _fake, n: random.choices(
            [
                "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
                "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
                "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
            ],
            k=n,
        ),
    },
    "ETHEREUM_ADDRESS": {
        "column_name": "test_ethereum_column",
        "generator": lambda fake, n: [f"0x{fake.hexify('^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^')}" for _ in range(n)],
    },
    "NPI": {
        "column_name": "test_npi_column",
        "generator": lambda _fake, n: _generate_valid_npi(n),
    },
    "DEA_NUMBER": {
        "column_name": "test_dea_column",
        "generator": lambda _fake, n: _generate_valid_dea(n),
    },
    "MBI": {
        "column_name": "test_mbi_column",
        "generator": lambda _fake, n: _generate_mbi(n),
    },
    "ABA_ROUTING": {
        "column_name": "test_aba_column",
        "generator": lambda _fake, n: _generate_valid_aba(n),
    },
    "CANADIAN_SIN": {
        "column_name": "test_sin_column",
        "generator": lambda _fake, n: _generate_valid_sin(n),
    },
    "MAC_ADDRESS": {
        "column_name": "test_mac_column",
        "generator": lambda fake, n: [fake.mac_address() for _ in range(n)],
    },
}

# "None" generators — columns that should NOT match any entity type
_NONE_GENERATORS: dict[str, dict] = {
    "random_integers": {
        "column_name": "test_random_int_column",
        "generator": lambda fake, n: [str(fake.random_int(min=1, max=999999)) for _ in range(n)],
    },
    "uuids": {
        "column_name": "test_uuid_column",
        "generator": lambda _fake, n: [str(uuid.uuid4()) for _ in range(n)],
    },
    "color_names": {
        "column_name": "test_color_column",
        "generator": lambda fake, n: [fake.color_name() for _ in range(n)],
    },
    "company_names": {
        "column_name": "test_company_column",
        "generator": lambda fake, n: [fake.company() for _ in range(n)],
    },
    "random_words": {
        "column_name": "test_random_word_column",
        "generator": lambda fake, n: [fake.word() for _ in range(n)],
    },
    "sentences": {
        "column_name": "test_sentence_column",
        "generator": lambda fake, n: [fake.sentence() for _ in range(n)],
    },
    "paragraphs": {
        "column_name": "test_paragraph_column",
        "generator": lambda fake, n: [fake.paragraph() for _ in range(n)],
    },
    "file_paths": {
        "column_name": "test_filepath_column",
        "generator": lambda fake, n: [fake.file_path() for _ in range(n)],
    },
    "hex_strings": {
        "column_name": "test_hex_column",
        "generator": lambda _fake, n: [
            "".join(random.choices("0123456789abcdef", k=random.randint(16, 64))) for _ in range(n)
        ],
    },
    "numeric_ids": {
        "column_name": "test_numeric_id_column",
        "generator": lambda _fake, n: [str(random.randint(100000, 999999999)) for _ in range(n)],
    },
}


def generate_corpus(
    samples_per_type: int = 200,
    locale: str = "en_US",
    *,
    include_embedded: bool = True,
) -> list[tuple[ColumnInput, str | None]]:
    """Generate a labeled corpus of ColumnInput objects for accuracy benchmarking.

    Args:
        samples_per_type: Number of sample values per column.
        locale: Faker locale for data generation.
        include_embedded: If True, add extra columns with values embedded in text.

    Returns:
        List of (ColumnInput, expected_entity_type) tuples.
    """
    fake = Faker(locale)
    corpus: list[tuple[ColumnInput, str | None]] = []

    # Generate positive cases (known entity types)
    for entity_type, config in _ENTITY_GENERATORS.items():
        samples = config["generator"](fake, samples_per_type)[:samples_per_type]
        column = ColumnInput(
            column_name=config["column_name"],
            column_id=f"corpus_{entity_type}_0",
            data_type="STRING",
            sample_values=samples,
        )
        corpus.append((column, entity_type))

        # Also generate a column with embedded-in-text values
        if include_embedded and entity_type in ("SSN", "EMAIL", "PHONE", "CREDIT_CARD", "NPI"):
            embedded = _generate_embedded_values(samples, entity_type)
            emb_col = ColumnInput(
                column_name=f"test_{entity_type.lower()}_notes",
                column_id=f"corpus_{entity_type}_embedded",
                data_type="STRING",
                sample_values=embedded,
            )
            corpus.append((emb_col, entity_type))

    # Generate negative cases (should not match anything)
    for none_key, config in _NONE_GENERATORS.items():
        column = ColumnInput(
            column_name=config["column_name"],
            column_id=f"corpus_none_{none_key}_0",
            data_type="STRING",
            sample_values=config["generator"](fake, samples_per_type)[:samples_per_type],
        )
        corpus.append((column, None))

    return corpus


# ── Raw sample generator for direct pattern testing ──────────────────────────


def generate_raw_samples(
    count_per_type: int = 500,
    locale: str = "en_US",
) -> list[tuple[str, str | None]]:
    """Generate raw (value, entity_type) pairs for direct pattern matching tests.

    Unlike generate_corpus() which wraps values in ColumnInputs, this returns
    individual values for testing regex patterns directly. Useful for:
    - Pattern-level precision/recall
    - String-length performance scaling
    - Cross-pattern collision detection

    Returns:
        List of (value_string, expected_entity_type_or_None) tuples.
    """
    fake = Faker(locale)
    samples: list[tuple[str, str | None]] = []

    for entity_type, config in _ENTITY_GENERATORS.items():
        values = config["generator"](fake, count_per_type)[:count_per_type]
        for v in values:
            samples.append((v, entity_type))

    # Add negative samples
    for _ in range(count_per_type):
        samples.append((fake.word(), None))
        samples.append((str(random.randint(1, 99999)), None))
        samples.append(("".join(random.choices(string.ascii_letters, k=random.randint(5, 30))), None))

    return samples


def generate_length_scaling_data() -> list[tuple[str, int]]:
    """Generate strings of varying lengths for RE2 performance scaling tests.

    Returns:
        List of (text, length_bytes) sorted by length. Each text contains
        a known pattern (SSN) buried at a random position, surrounded by
        padding text. Tests how RE2 scales with input length.
    """
    ssn = "123-45-6789"
    results: list[tuple[str, int]] = []
    for target_len in [50, 100, 500, 1000, 5000, 10000, 50000]:
        padding_len = max(0, target_len - len(ssn) - 1)
        padding = "".join(random.choices(string.ascii_lowercase + " ", k=padding_len))
        insert_pos = random.randint(0, len(padding))
        text = padding[:insert_pos] + " " + ssn + " " + padding[insert_pos:]
        results.append((text, len(text)))
    return results
