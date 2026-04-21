"""Tests for opaque token detection in the SecretScannerEngine.

The secret scanner detects credential-like values via three paths:
  1. Column name — column name scores as key, cell value as candidate
  2. KV parsing — parse key=value structure, score key name
  3. Population — statistical entropy/diversity analysis

Prefix-based detection (ghp_, AKIA, etc.) is handled by the regex engine's
specific patterns, which are more precise than generic prefix matching.

These tests cover paths 1 and 3 (path 2 is tested in the existing
secret scanner test suite). The heuristic engine's opaque_secret_detection
has been consolidated here — the secret scanner owns the richer key-name
dictionary (280 entries) and tiered scoring.
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.engines.secret_scanner import SecretScannerEngine

# ── Path 1: Column name as key ────────────────────────────────────────────

# High-entropy, mixed-case, length 24-40
POSITIVE_VALUES: list[list[str]] = [
    [
        "aK7!pQ9#mL4wB2$nR6@jF8dZ3&hY5",
        "xK1#mQ2$pL9!nR4wB6@jF8dZ3&hY5T",
        "zW3^eT5*uI7_pL9!nR4wB6@jF8dZ3",
        "bY9$kF2&mN6#qR4*tV8_wX0+zC5",
        "gH4%jK6^lP8&mN2*qR4#tV6$wX8",
        "nJ5@eR7#iU9$oP1^bV3&xC5*zQ7",
        "rG8(kL2)pM4+nB6_cV8=hY0|jW3",
        "qS4/dF7.gH9:jK2;mN5?pR8<tV0",
        "xL6>yB9[aC3]dE5{gH7}iJ0!nR4",
        "wT2-zU5=vX8_aB1@dE4#gH7$jK0",
        "YWxpY2VAZXhhbXBsZS5jb21ZWxpY",
        "base64safe_abcdefghijklmnop",
    ],
    [
        "xK7!mQ2$pL9nR4wB6jF8dZ3hY5TeU7oI9aS1dFgHjKlM",
        "zW3eT5uI7pL9nR4wB6jF8dZ3hY5aK7pQ9mL4wB2nR6jF",
        "nJ5eR7iU9oP1bV3xC5zQ7wY2tG4hJ6kL8mP0nQ2rS4uV",
        "qS4dF7gH9jK2mN5pR8tV0xB2dE4gH7jK0lP2nR4pT6vX",
        "rG8kL2pM4nB6cV8hY0jW3zA5cE7gI9kM1oQ3qS5uW7yX",
        "bY9kF2mN6qR4tV8wX0zC5aE7cG9eI1gK3iM5kO7mQ9oS",
        "wT2zU5vX8aB1dE4gH7jK0lN2nP4pR6qS8rT0uV2wX4yZ",
        "gH4jK6lP8mN2qR4tV6wX8yZ0aB1cD3eF5gH7iJ9kL1mN",
        "xL6yB9aC3dE5gH7iJ0nR4pT6rV8tX0vZ2wB4yD6aF8cH",
        "eU7oI9aS1dFgHjKlMnOpQrStUvWxYz0123456789abc",
    ],
]

# Negative cases: should NOT trigger
NEGATIVE_CASES: list[tuple[str, list[str]]] = [
    # UUID v4 under non-credential column
    (
        "user_id",
        [
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            "6ba7b812-9dad-11d1-80b4-00c04fd430c8",
        ],
    ),
    # IP addresses — too short
    (
        "client_secret",
        ["192.168.1.1", "10.0.0.5", "172.16.0.1", "203.0.113.42"],
    ),
    # Prose text under non-credential column
    (
        "description",
        [
            "the quick brown fox jumps over lazy dogs daily for sport",
            "lorem ipsum dolor sit amet consectetur adipiscing elit today",
            "my name is alice and I live in wonderland forever more",
            "this is a random sentence containing many common words used",
        ],
    ),
    # Short values under credential column — too short for detection
    (
        "api_key",
        ["abc123", "def456", "ghi789", "jkl012"],
    ),
]


class TestColumnNameDetection:
    """Column name as key — the secret scanner should use the column name
    to identify credential-like columns and apply tiered scoring to values."""

    @pytest.fixture(autouse=True)
    def _engine(self) -> None:
        self.engine = SecretScannerEngine()
        self.engine.startup()

    @pytest.mark.parametrize("values", POSITIVE_VALUES)
    def test_high_entropy_credential_column_detected(self, values: list[str]) -> None:
        col = ColumnInput(column_name="password", column_id="col_pw", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.3)
        cred = [f for f in findings if f.category == "Credential"]
        assert len(cred) >= 1, f"expected credential finding, got {findings}"

    def test_fires_for_api_key_column(self) -> None:
        values = [
            "xK7!mQ2$pL9nR4wB6jF8dZ3hY5TeU7oI9aS1dFgHjKlM",
            "zW3eT5uI7pL9nR4wB6jF8dZ3hY5aK7pQ9mL4wB2nR6jF",
            "nJ5eR7iU9oP1bV3xC5zQ7wY2tG4hJ6kL8mP0nQ2rS4uV",
            "qS4dF7gH9jK2mN5pR8tV0xB2dE4gH7jK0lP2nR4pT6vX",
        ]
        col = ColumnInput(column_name="internal_api_key", column_id="col_ak", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.3)
        cred = [f for f in findings if f.category == "Credential"]
        assert len(cred) >= 1

    def test_fires_for_client_secret_column(self) -> None:
        values = [
            "rG8kL2pM4nB6cV8hY0jW3zA5cE7gI9kM1oQ3qS5uW7yX",
            "bY9kF2mN6qR4tV8wX0zC5aE7cG9eI1gK3iM5kO7mQ9oS",
            "wT2zU5vX8aB1dE4gH7jK0lN2nP4pR6qS8rT0uV2wX4yZ",
            "gH4jK6lP8mN2qR4tV6wX8yZ0aB1cD3eF5gH7iJ9kL1mN",
        ]
        col = ColumnInput(column_name="client_secret", column_id="col_cs", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.3)
        cred = [f for f in findings if f.category == "Credential"]
        assert len(cred) >= 1

    def test_non_credential_column_no_fire(self) -> None:
        """High-entropy values under a non-credential column name should not fire
        via column-name path (may still fire via population path if enough samples)."""
        values = [
            "xK7!mQ2$pL9nR4wB6jF8dZ3hY5TeU7oI9aS1dFgHjKlM",
            "zW3eT5uI7pL9nR4wB6jF8dZ3hY5aK7pQ9mL4wB2nR6jF",
            "nJ5eR7iU9oP1bV3xC5zQ7wY2tG4hJ6kL8mP0nQ2rS4uV",
        ]
        col = ColumnInput(column_name="notes", column_id="col_notes", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.3)
        # Column name "notes" doesn't score — should not fire via path 2.
        # With only 3 samples, path 4 won't fire either (needs >= 5).
        assert len(findings) == 0

    @pytest.mark.parametrize(("column_name", "values"), NEGATIVE_CASES)
    def test_negative_cases(self, column_name: str, values: list[str]) -> None:
        col = ColumnInput(column_name=column_name, column_id="col_neg", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.5)
        cred = [f for f in findings if f.category == "Credential"]
        assert len(cred) == 0, f"Expected no credential finding for column={column_name!r}, got {cred}"


# ── Path 4: Population-level analysis ─────────────────────────────────────


class TestPopulationAnalysis:
    """Blind columns (no name hint, no prefix) with secret-like population
    characteristics should fire at reduced confidence."""

    @pytest.fixture(autouse=True)
    def _engine(self) -> None:
        self.engine = SecretScannerEngine()
        self.engine.startup()

    def test_high_entropy_blind_column(self) -> None:
        """50 high-entropy, consistent-length, high-diversity values
        under a blind column name."""
        import random
        import string

        rng = random.Random(42)
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        values = ["".join(rng.choices(chars, k=32)) for _ in range(50)]
        col = ColumnInput(column_name="col_0", column_id="col_0", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.5)
        cred = [f for f in findings if f.category == "Credential"]
        assert len(cred) >= 1
        assert cred[0].entity_type == "OPAQUE_SECRET"
        assert cred[0].confidence <= 0.80  # capped confidence

    def test_uuid_column_excluded(self) -> None:
        """UUIDs have high entropy but are not secrets — population path
        should exclude them."""
        values = [
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            "6ba7b812-9dad-11d1-80b4-00c04fd430c8",
            "f47ac10b-58cc-4372-a567-0e02b2c3d479",
            "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        ]
        col = ColumnInput(column_name="record_id", column_id="col_uid", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.3)
        assert len(findings) == 0

    def test_too_few_samples_no_fire(self) -> None:
        """Population analysis requires >= 5 samples."""
        import random
        import string

        rng = random.Random(42)
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        values = ["".join(rng.choices(chars, k=32)) for _ in range(3)]
        col = ColumnInput(column_name="col_0", column_id="col_0", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.3)
        # Only 3 samples, below _MIN_STATISTICAL_SAMPLES=5
        assert len(findings) == 0

    def test_low_entropy_no_fire(self) -> None:
        """Repeated/low-entropy values should not trigger."""
        values = ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"] * 10
        col = ColumnInput(column_name="col_0", column_id="col_0", sample_values=values)
        findings = self.engine.classify_column(col, min_confidence=0.3)
        assert len(findings) == 0


# ── End-to-end through the engine cascade ─────────────────────────────────


class TestOpaqueSecretInEngine:
    """SecretScannerEngine emits OPAQUE_SECRET findings for qualifying columns."""

    @pytest.fixture(autouse=True)
    def _engine(self) -> None:
        self.engine = SecretScannerEngine()
        self.engine.startup()

    def test_engine_emits_for_password_column(self) -> None:
        col = ColumnInput(
            column_name="password",
            column_id="col_pw",
            sample_values=[
                "xK7!mQ2$pL9nR4wB6jF8dZ3hY5TeU7oI9aS1dFgHjKlM",
                "zW3eT5uI7pL9nR4wB6jF8dZ3hY5aK7pQ9mL4wB2nR6jF",
                "nJ5eR7iU9oP1bV3xC5zQ7wY2tG4hJ6kL8mP0nQ2rS4uV",
                "qS4dF7gH9jK2mN5pR8tV0xB2dE4gH7jK0lP2nR4pT6vX",
                "rG8kL2pM4nB6cV8hY0jW3zA5cE7gI9kM1oQ3qS5uW7yX",
                "bY9kF2mN6qR4tV8wX0zC5aE7cG9eI1gK3iM5kO7mQ9oS",
                "wT2zU5vX8aB1dE4gH7jK0lN2nP4pR6qS8rT0uV2wX4yZ",
                "gH4jK6lP8mN2qR4tV6wX8yZ0aB1cD3eF5gH7iJ9kL1mN",
                "xL6yB9aC3dE5gH7iJ0nR4pT6rV8tX0vZ2wB4yD6aF8cH",
                "eU7oI9aS1dFgHjKlMnOpQrStUvWxYz0123456789abc",
            ],
        )
        findings = self.engine.classify_column(col, min_confidence=0.3)
        cred = [f for f in findings if f.category == "Credential"]
        assert len(cred) == 1
        assert cred[0].engine == "secret_scanner"

    def test_engine_does_not_emit_on_non_credential_column(self) -> None:
        col = ColumnInput(
            column_name="notes",
            column_id="col_notes",
            sample_values=[
                "xK7!mQ2$pL9nR4wB6jF8dZ3hY5TeU7oI9aS1dFgHjKlM",
                "zW3eT5uI7pL9nR4wB6jF8dZ3hY5aK7pQ9mL4wB2nR6jF",
                "nJ5eR7iU9oP1bV3xC5zQ7wY2tG4hJ6kL8mP0nQ2rS4uV",
            ],
        )
        findings = self.engine.classify_column(col, min_confidence=0.5)
        cred = [f for f in findings if f.category == "Credential"]
        assert not cred, f"notes column must not produce credential, got {findings}"
