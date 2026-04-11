"""Corpus loader — loads external and synthetic corpora for benchmarking.

Supports multiple corpus sources:
- Synthetic (Faker-based, via corpus_generator.py)
- Ai4Privacy pii-masking-300k (HuggingFace sample)
- Nemotron-PII (HuggingFace sample)

Sample data ships in tests/fixtures/corpora/ for offline benchmarking.

Usage:
    from tests.benchmarks.corpus_loader import load_corpus
    corpus = load_corpus("ai4privacy", max_rows=500)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from data_classifier.core.types import ColumnInput

logger = logging.getLogger(__name__)

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "corpora"

# ── Entity type mappings from external corpora to our types ──────────────────

# Verified label names from actual datasets (see scripts/download_corpora.py)
AI4PRIVACY_TYPE_MAP: dict[str, str] = {
    "EMAIL": "EMAIL",
    "TEL": "PHONE",
    "IP": "IP_ADDRESS",
    "SOCIALNUMBER": "SSN",
    "PASS": "CREDENTIAL",
    "BOD": "DATE_OF_BIRTH",
    "DATE": "DATE_OF_BIRTH",
    "GIVENNAME1": "PERSON_NAME",
    "GIVENNAME2": "PERSON_NAME",
    "LASTNAME1": "PERSON_NAME",
    "LASTNAME2": "PERSON_NAME",
    "LASTNAME3": "PERSON_NAME",
    "STREET": "ADDRESS",
    "SECADDRESS": "ADDRESS",
    "ADDRESS": "ADDRESS",
    "PHONE": "PHONE",
    "SSN": "SSN",
    "CREDENTIAL": "CREDENTIAL",
    "IP_ADDRESS": "IP_ADDRESS",
    "PERSON_NAME": "PERSON_NAME",
    "DATE_OF_BIRTH": "DATE_OF_BIRTH",
}

NEMOTRON_TYPE_MAP: dict[str, str] = {
    "first_name": "PERSON_NAME",
    "last_name": "PERSON_NAME",
    "date_of_birth": "DATE_OF_BIRTH",
    "street_address": "ADDRESS",
    "email": "EMAIL",
    "email_address": "EMAIL",
    "phone_number": "PHONE",
    "social_security_number": "SSN",
    "ssn": "SSN",
    "credit_debit_card": "CREDIT_CARD",
    "credit_card_number": "CREDIT_CARD",
    "ip_address": "IP_ADDRESS",
    "ipv4": "IP_ADDRESS",
    "ipv6": "IP_ADDRESS",
    "url": "URL",
    "iban": "IBAN",
    "swift_bic": "SWIFT_BIC",
    "swift_code": "SWIFT_BIC",
    "mac_address": "MAC_ADDRESS",
    "bank_routing_number": "ABA_ROUTING",
    "routing_number": "ABA_ROUTING",
    "password": "CREDENTIAL",
    "api_key": "CREDENTIAL",
    "pin": "CREDENTIAL",
    "PERSON_NAME": "PERSON_NAME",
    "ADDRESS": "ADDRESS",
    "EMAIL": "EMAIL",
    "PHONE": "PHONE",
    "SSN": "SSN",
    "CREDIT_CARD": "CREDIT_CARD",
    "IP_ADDRESS": "IP_ADDRESS",
    "URL": "URL",
    "SWIFT_BIC": "SWIFT_BIC",
    "MAC_ADDRESS": "MAC_ADDRESS",
    "ABA_ROUTING": "ABA_ROUTING",
    "CREDENTIAL": "CREDENTIAL",
    "DATE_OF_BIRTH": "DATE_OF_BIRTH",
}


def _load_json_corpus(path: Path) -> list[dict]:
    """Load a JSON corpus file, returning list of records."""
    if not path.exists():
        logger.warning("Corpus file not found: %s", path)
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _records_to_corpus(
    records: list[dict],
    type_map: dict[str, str],
    source_name: str,
    max_rows: int = 500,
) -> list[tuple[ColumnInput, str | None]]:
    """Convert corpus records to (ColumnInput, expected_entity_type) tuples.

    Groups values by mapped entity type, creates one ColumnInput per type
    with up to max_rows sample values.
    """
    # Group values by our entity type
    by_type: dict[str, list[str]] = {}
    for record in records:
        ext_type = record.get("entity_type", record.get("type", ""))
        value = record.get("value", "")
        if not value or not ext_type:
            continue

        our_type = type_map.get(ext_type)
        if our_type is None:
            continue

        by_type.setdefault(our_type, []).append(str(value))

    corpus: list[tuple[ColumnInput, str | None]] = []
    for entity_type, values in sorted(by_type.items()):
        # Truncate to max_rows
        values = values[:max_rows]
        col = ColumnInput(
            column_name=f"{source_name}_{entity_type.lower()}",
            column_id=f"{source_name}_{entity_type}_0",
            data_type="STRING",
            sample_values=values,
        )
        corpus.append((col, entity_type))

    return corpus


def load_ai4privacy_corpus(
    path: Path | str | None = None,
    max_rows: int = 500,
) -> list[tuple[ColumnInput, str | None]]:
    """Load Ai4Privacy corpus sample and convert to our format.

    Args:
        path: Path to JSON sample file. Defaults to bundled fixture.
        max_rows: Maximum sample values per entity type.

    Returns:
        List of (ColumnInput, expected_entity_type) tuples.
    """
    if path is None:
        path = _FIXTURES_DIR / "ai4privacy_sample.json"
    else:
        path = Path(path)

    records = _load_json_corpus(path)
    if not records:
        logger.warning("No records loaded from Ai4Privacy corpus at %s", path)
        return []

    return _records_to_corpus(records, AI4PRIVACY_TYPE_MAP, "ai4privacy", max_rows)


def load_nemotron_corpus(
    path: Path | str | None = None,
    max_rows: int = 500,
) -> list[tuple[ColumnInput, str | None]]:
    """Load Nemotron-PII corpus sample and convert to our format.

    Args:
        path: Path to JSON sample file. Defaults to bundled fixture.
        max_rows: Maximum sample values per entity type.

    Returns:
        List of (ColumnInput, expected_entity_type) tuples.
    """
    if path is None:
        path = _FIXTURES_DIR / "nemotron_sample.json"
    else:
        path = Path(path)

    records = _load_json_corpus(path)
    if not records:
        logger.warning("No records loaded from Nemotron corpus at %s", path)
        return []

    return _records_to_corpus(records, NEMOTRON_TYPE_MAP, "nemotron", max_rows)


def load_synthetic_corpus(
    samples_per_type: int = 200,
) -> list[tuple[ColumnInput, str | None]]:
    """Wrap the existing Faker-based synthetic generator.

    Args:
        samples_per_type: Number of sample values per entity type.

    Returns:
        List of (ColumnInput, expected_entity_type) tuples.
    """
    from tests.benchmarks.corpus_generator import generate_corpus

    return generate_corpus(samples_per_type=samples_per_type)


def load_corpus(
    source: str,
    *,
    max_rows: int = 500,
    path: Path | str | None = None,
    samples_per_type: int = 200,
) -> list[tuple[ColumnInput, str | None]]:
    """Dispatcher — load corpus by source name.

    Args:
        source: One of "synthetic", "ai4privacy", "nemotron", "all".
        max_rows: Max rows for real-world corpora.
        path: Optional custom path to corpus file.
        samples_per_type: Samples per type for synthetic corpus.

    Returns:
        List of (ColumnInput, expected_entity_type) tuples.
    """
    if source == "synthetic":
        return load_synthetic_corpus(samples_per_type=samples_per_type)
    elif source == "ai4privacy":
        return load_ai4privacy_corpus(path=path, max_rows=max_rows)
    elif source == "nemotron":
        return load_nemotron_corpus(path=path, max_rows=max_rows)
    elif source == "all":
        corpus: list[tuple[ColumnInput, str | None]] = []
        corpus.extend(load_synthetic_corpus(samples_per_type=samples_per_type))
        corpus.extend(load_ai4privacy_corpus(max_rows=max_rows))
        corpus.extend(load_nemotron_corpus(max_rows=max_rows))
        return corpus
    else:
        msg = f"Unknown corpus source: {source!r}. Valid: synthetic, ai4privacy, nemotron, all"
        raise ValueError(msg)
