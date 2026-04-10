"""Synthetic corpus generator for accuracy benchmarking.

Generates labeled ColumnInput objects with known entity types as ground truth.
Uses Faker for realistic synthetic data generation, plus custom generators
for entity types that require valid check digits (NPI, DEA, VIN, ABA, etc.).

Usage:
    from tests.benchmarks.corpus_generator import generate_corpus
    corpus = generate_corpus(samples_per_type=50, locale="en_US")
    for column_input, expected_entity_type in corpus:
        ...
"""

from __future__ import annotations

import random
import uuid

from faker import Faker

from data_classifier.core.types import ColumnInput

# ── Custom generators for check-digit-validated patterns ─────────────────────


def _generate_valid_npi(n: int) -> list[str]:
    """Generate Luhn-valid NPI numbers (prefix 80840 + 10 digits)."""
    results = []
    for _ in range(n):
        base = f"{random.randint(1, 2)}{random.randint(0, 99999999):08d}"
        # Compute Luhn check digit with 80840 prefix
        full = "80840" + base
        digits = [int(d) for d in full]
        checksum = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 0:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
        check = (10 - (checksum % 10)) % 10
        results.append(base + str(check))
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
    """Generate Luhn-valid Canadian SIN numbers."""
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
        all_digits = digits + [check]
        d = all_digits
        results.append(f"{d[0]}{d[1]}{d[2]} {d[3]}{d[4]}{d[5]} {d[6]}{d[7]}{d[8]}")
    return results


def _generate_mbi(n: int) -> list[str]:
    """Generate valid MBI format strings (positional alphanumeric)."""
    alpha = "ACDEFGHJKMNPQRTUVWXY"  # no S,L,O,I,B,Z
    alphanum = alpha + "0123456789"
    results = []
    for _ in range(n):
        c1 = str(random.randint(1, 9))
        c2 = random.choice(alpha)
        c3 = random.choice(alphanum)
        c4 = str(random.randint(0, 9))
        c5 = random.choice(alpha)
        c6 = random.choice(alphanum)
        c7 = str(random.randint(0, 9))
        c8 = random.choice(alpha)
        c9 = random.choice(alpha)
        c10 = str(random.randint(0, 9))
        c11 = str(random.randint(0, 9))
        results.append(c1 + c2 + c3 + c4 + c5 + c6 + c7 + c8 + c9 + c10 + c11)
    return results


# Entity type generators: each returns a list of sample values from Faker
_ENTITY_GENERATORS: dict[str, dict] = {
    "SSN": {
        "column_name": "test_ssn_column",
        "generator": lambda fake, n: [fake.ssn() for _ in range(n)],
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
        "generator": lambda fake, n: [fake.credit_card_number() for _ in range(n)],
    },
    "DATE_OF_BIRTH": {
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
        "generator": lambda _fake, n: ["1HGBH41JXMN109186", "5YJSA1DG9DFP14705"] * (n // 2 + 1),
    },
    "BITCOIN_ADDRESS": {
        "column_name": "test_bitcoin_column",
        "generator": lambda _fake, n: (
            [
                "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
                "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
            ]
            * (n // 2 + 1)
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
    "DATE_OF_BIRTH_EU": {
        "column_name": "test_dob_eu_column",
        "generator": lambda fake, n: [fake.date_of_birth().strftime("%d/%m/%Y") for _ in range(n)],
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
}


def generate_corpus(
    samples_per_type: int = 20,
    locale: str = "en_US",
) -> list[tuple[ColumnInput, str | None]]:
    """Generate a labeled corpus of ColumnInput objects for accuracy benchmarking.

    Each tuple contains a ColumnInput with Faker-generated sample values and the
    expected entity type (or None for columns that should not match anything).

    Args:
        samples_per_type: Number of sample values per column.
        locale: Faker locale for data generation.

    Returns:
        List of (ColumnInput, expected_entity_type) tuples.
    """
    fake = Faker(locale)
    corpus: list[tuple[ColumnInput, str | None]] = []

    # Generate positive cases (known entity types)
    for entity_type, config in _ENTITY_GENERATORS.items():
        column = ColumnInput(
            column_name=config["column_name"],
            column_id=f"corpus_{entity_type}_0",
            data_type="STRING",
            sample_values=config["generator"](fake, samples_per_type),
        )
        corpus.append((column, entity_type))

    # Generate negative cases (should not match anything)
    for none_key, config in _NONE_GENERATORS.items():
        column = ColumnInput(
            column_name=config["column_name"],
            column_id=f"corpus_none_{none_key}_0",
            data_type="STRING",
            sample_values=config["generator"](fake, samples_per_type),
        )
        corpus.append((column, None))

    return corpus
