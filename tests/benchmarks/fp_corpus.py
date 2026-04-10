"""False positive corpus — static and synthetic near-miss test data.

Loads FP test cases from YAML and generates synthetic near-misses
that should NOT trigger classification.
"""

from __future__ import annotations

import string
from pathlib import Path

import yaml

from data_classifier.core.types import ColumnInput

_FP_CORPUS_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "fp_corpus.yaml"


def load_fp_corpus() -> list[dict]:
    """Load static FP test cases from YAML.

    Returns:
        List of dicts with keys: name, sample_values, should_not_match, context (optional).
    """
    with open(_FP_CORPUS_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("cases", [])


def generate_near_misses(count: int = 50) -> list[tuple[ColumnInput, None]]:
    """Generate synthetic near-miss values that should NOT be classified.

    Produces columns with values that superficially resemble sensitive data
    but are not valid instances of any entity type.

    Args:
        count: Number of sample values per near-miss column.

    Returns:
        List of (ColumnInput, None) tuples — None indicates no expected match.
    """
    import random

    rng = random.Random(42)  # Deterministic for reproducibility
    near_misses: list[tuple[ColumnInput, None]] = []

    # Near-miss SSNs: wrong format (too few/many digits, invalid area codes)
    ssn_values = (
        [f"000-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}" for _ in range(count // 5)]
        + [f"666-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}" for _ in range(count // 5)]
        + [f"{rng.randint(1, 899)}-00-{rng.randint(1000, 9999)}" for _ in range(count // 5)]
        + [f"{rng.randint(1, 899)}-{rng.randint(1, 99)}-0000" for _ in range(count // 5)]
        + [f"{rng.randint(100, 999)}{rng.randint(10, 99)}{rng.randint(1000, 9999)}" for _ in range(count // 5)]
    )
    near_misses.append(
        (
            ColumnInput(
                column_name="near_miss_ssn",
                column_id="fp_near_miss_ssn",
                data_type="STRING",
                sample_values=ssn_values,
            ),
            None,
        )
    )

    # Near-miss emails: malformed addresses
    email_values = (
        [f"{''.join(rng.choices(string.ascii_lowercase, k=5))}@" for _ in range(count // 4)]
        + [f"@{''.join(rng.choices(string.ascii_lowercase, k=8))}.com" for _ in range(count // 4)]
        + [
            f"{''.join(rng.choices(string.ascii_lowercase, k=5))}@{''.join(rng.choices(string.ascii_lowercase, k=5))}"
            for _ in range(count // 4)
        ]
        + ["".join(rng.choices(string.ascii_lowercase + string.digits, k=15)) for _ in range(count // 4)]
    )
    near_misses.append(
        (
            ColumnInput(
                column_name="near_miss_email",
                column_id="fp_near_miss_email",
                data_type="STRING",
                sample_values=email_values,
            ),
            None,
        )
    )

    # Near-miss credit cards: Luhn-invalid 16-digit numbers
    cc_values = []
    for _ in range(count):
        digits = "".join(str(rng.randint(0, 9)) for _ in range(16))
        # Ensure Luhn-invalid by flipping last digit
        last = int(digits[-1])
        digits = digits[:-1] + str((last + 1) % 10)
        cc_values.append(digits)
    near_misses.append(
        (
            ColumnInput(
                column_name="near_miss_credit_card",
                column_id="fp_near_miss_cc",
                data_type="STRING",
                sample_values=cc_values,
            ),
            None,
        )
    )

    # Near-miss phone numbers: too short or too long
    phone_values = [f"{rng.randint(100, 999)}-{rng.randint(1000, 9999)}" for _ in range(count // 2)] + [
        f"{rng.randint(100, 999)}-{rng.randint(100, 999)}-{rng.randint(10000, 99999)}" for _ in range(count // 2)
    ]
    near_misses.append(
        (
            ColumnInput(
                column_name="near_miss_phone",
                column_id="fp_near_miss_phone",
                data_type="STRING",
                sample_values=phone_values,
            ),
            None,
        )
    )

    # Generic numeric IDs (should not be classified as anything)
    id_values = [str(rng.randint(10000, 99999)) for _ in range(count)]
    near_misses.append(
        (
            ColumnInput(
                column_name="generic_id",
                column_id="fp_generic_id",
                data_type="STRING",
                sample_values=id_values,
            ),
            None,
        )
    )

    return near_misses
