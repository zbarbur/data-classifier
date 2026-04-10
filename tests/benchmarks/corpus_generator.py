"""Synthetic corpus generator for accuracy benchmarking.

Generates labeled ColumnInput objects with known entity types as ground truth.
Uses Faker for realistic synthetic data generation.

Usage:
    from tests.benchmarks.corpus_generator import generate_corpus
    corpus = generate_corpus(samples_per_type=20, locale="en_US")
    for column_input, expected_entity_type in corpus:
        ...
"""

from __future__ import annotations

import uuid

from faker import Faker

from data_classifier.core.types import ColumnInput

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
