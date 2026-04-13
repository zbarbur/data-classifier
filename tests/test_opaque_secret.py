"""Tests for the OPAQUE_SECRET heuristic (Sprint 8 Item 4).

Covers the ``opaque_secret_detection`` function added to
``data_classifier.engines.heuristic_engine`` as part of the Sprint 8
credential taxonomy split. The heuristic fires only when ALL of the
following hold:
  1. column name contains a credential hint keyword
  2. average entropy >= 4.5 bits/char
  3. length distribution mostly in [20, 200]
  4. avg char-class diversity >= 3
  5. distinct-value ratio >= 0.9

Per the memory feedback ``feedback_entropy_secondary.md`` entropy alone
is never sufficient — the five signals must all agree. These tests lock
in that behavior with positive and negative fixtures.
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.engines.heuristic_engine import (
    HeuristicEngine,
    opaque_secret_detection,
)

# ── Positive fixtures ───────────────────────────────────────────────────────
# High-entropy, mixed-case, length 20-200, under a credential column name.
POSITIVE_VALUES: list[list[str]] = [
    # Mixed-class random strings, length 24-40
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
        # length-28 URL-safe tokens (no spaces/structure markers)
        "YWxpY2VAZXhhbXBsZS5jb21ZWxpY",
        "base64safe_abcdefghijklmnop",
    ],
    # Length-60-ish high-entropy strings
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

# ── Negative fixtures ───────────────────────────────────────────────────────
# These should NOT trigger OPAQUE_SECRET. Each test case pairs the values
# with a column name — the column is chosen deliberately (some credential-
# named to prove the non-shape signals reject, others non-credential to
# prove the column gate works).
NEGATIVE_CASES: list[tuple[str, list[str]]] = [
    # Bitcoin addresses under a credential column — below length window mostly,
    # and lower diversity; should not trigger.
    (
        "secret",
        [
            "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
            "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
        ],
    ),
    # UUID v4 under 'user_id' — credential gate absent
    (
        "user_id",
        [
            "550e8400-e29b-41d4-a716-446655440000",
            "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
            "6ba7b811-9dad-11d1-80b4-00c04fd430c8",
            "6ba7b812-9dad-11d1-80b4-00c04fd430c8",
        ],
    ),
    # Plain hex (SHA-256 file hashes) under 'secret' — low diversity (hex only)
    (
        "file_secret",
        [
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
            "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8",
        ],
    ),
    # IP addresses — length far below 20
    (
        "client_secret",
        ["192.168.1.1", "10.0.0.5", "172.16.0.1", "203.0.113.42"],
    ),
    # Long integer IDs — single char class (digits), no diversity
    (
        "secret_id",
        [
            "123456789012345678901",
            "234567890123456789012",
            "345678901234567890123",
            "456789012345678901234",
        ],
    ),
    # Base64-encoded short strings — fail length window (below 20)
    (
        "api_secret",
        ["YWJjZA==", "ZGVmZw==", "aGlqaw==", "bG1ub3A="],
    ),
    # Prose text with spaces under 'description' — no credential hint + low diversity
    (
        "description",
        [
            "the quick brown fox jumps over lazy dogs daily for sport",
            "lorem ipsum dolor sit amet consectetur adipiscing elit today",
            "my name is alice and I live in wonderland forever more",
            "this is a random sentence containing many common words used",
        ],
    ),
    # Repeated value under credential column — fails distinct ratio
    (
        "password",
        [
            "SameP@ssw0rd123456789ABC",
            "SameP@ssw0rd123456789ABC",
            "SameP@ssw0rd123456789ABC",
            "SameP@ssw0rd123456789ABC",
        ],
    ),
    # Ethereum addresses — low diversity (hex), under non-credential column
    (
        "eth_wallet",
        [
            "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe",
            "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        ],
    ),
    # Git SHA-1 hashes — hex only, low diversity, under 'commit' col
    (
        "commit_secret",
        [
            "2f6c535b1234567890abcdef1234567890abcdef",
            "a1b2c3d4e5f67890abcdef1234567890abcdef12",
            "ff00aa11bb22cc33dd44ee55ff6677889900aabb",
        ],
    ),
    # Credential-hinted column but too-short values (<20) — length gate rejects
    (
        "api_key",
        ["abc123", "def456", "ghi789", "jkl012"],
    ),
]


class TestOpaqueSecretDetectionPositive:
    """``opaque_secret_detection`` must fire on high-entropy credential-shaped columns."""

    @pytest.mark.parametrize("values", POSITIVE_VALUES)
    def test_high_entropy_credential_column_detected(self, values: list[str]) -> None:
        is_opaque, evidence = opaque_secret_detection(values, column_name="password")
        assert is_opaque, f"expected detection, got negative with evidence: {evidence}"
        assert "opaque_secret_detection" in evidence

    def test_fires_for_api_key_column(self) -> None:
        values = [
            "xK7!mQ2$pL9nR4wB6jF8dZ3hY5TeU7oI9aS1dFgHjKlM",
            "zW3eT5uI7pL9nR4wB6jF8dZ3hY5aK7pQ9mL4wB2nR6jF",
            "nJ5eR7iU9oP1bV3xC5zQ7wY2tG4hJ6kL8mP0nQ2rS4uV",
            "qS4dF7gH9jK2mN5pR8tV0xB2dE4gH7jK0lP2nR4pT6vX",
        ]
        is_opaque, _ = opaque_secret_detection(values, column_name="internal_api_key")
        assert is_opaque

    def test_fires_for_client_secret_column(self) -> None:
        values = [
            "rG8kL2pM4nB6cV8hY0jW3zA5cE7gI9kM1oQ3qS5uW7yX",
            "bY9kF2mN6qR4tV8wX0zC5aE7cG9eI1gK3iM5kO7mQ9oS",
            "wT2zU5vX8aB1dE4gH7jK0lN2nP4pR6qS8rT0uV2wX4yZ",
            "gH4jK6lP8mN2qR4tV6wX8yZ0aB1cD3eF5gH7iJ9kL1mN",
        ]
        is_opaque, _ = opaque_secret_detection(values, column_name="client_secret")
        assert is_opaque


class TestOpaqueSecretDetectionNegative:
    """``opaque_secret_detection`` must NOT fire on any of the negative cases."""

    @pytest.mark.parametrize(("column_name", "values"), [(col, vals) for col, vals in NEGATIVE_CASES])
    def test_does_not_fire(self, column_name: str, values: list[str]) -> None:
        is_opaque, evidence = opaque_secret_detection(values, column_name=column_name)
        assert not is_opaque, (
            f"Expected no detection for column={column_name!r} values={values[:2]}..., but got: {evidence}"
        )


class TestOpaqueSecretColumnGate:
    """The column-name gate is the critical FP guard — no hint means no fire."""

    def test_no_column_name_is_rejected(self) -> None:
        values = [
            "xK7!mQ2$pL9nR4wB6jF8dZ3hY5TeU7oI9aS1dFgHjKlM",
            "zW3eT5uI7pL9nR4wB6jF8dZ3hY5aK7pQ9mL4wB2nR6jF",
        ]
        is_opaque, evidence = opaque_secret_detection(values, column_name=None)
        assert not is_opaque
        assert "credential hint" in evidence

    def test_generic_column_name_is_rejected(self) -> None:
        values = [
            "xK7!mQ2$pL9nR4wB6jF8dZ3hY5TeU7oI9aS1dFgHjKlM",
            "zW3eT5uI7pL9nR4wB6jF8dZ3hY5aK7pQ9mL4wB2nR6jF",
            "nJ5eR7iU9oP1bV3xC5zQ7wY2tG4hJ6kL8mP0nQ2rS4uV",
        ]
        is_opaque, _ = opaque_secret_detection(values, column_name="notes")
        assert not is_opaque


class TestOpaqueSecretInEngine:
    """End-to-end: HeuristicEngine emits OPAQUE_SECRET findings for qualifying columns."""

    @pytest.fixture(autouse=True)
    def _disable_ml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove GLiNER2 from the default cascade — this test exercises a
        heuristic-engine feature and does not need ML."""
        import data_classifier

        non_ml_engines = [e for e in data_classifier._DEFAULT_ENGINES if getattr(e, "name", "") != "gliner2"]
        monkeypatch.setattr(data_classifier, "_DEFAULT_ENGINES", non_ml_engines)

    @pytest.fixture()
    def engine(self) -> HeuristicEngine:
        e = HeuristicEngine()
        e.startup()
        return e

    def test_engine_emits_opaque_secret_for_password_column(self, engine: HeuristicEngine) -> None:
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
        findings = engine.classify_column(col)
        opaque = [f for f in findings if f.entity_type == "OPAQUE_SECRET"]
        assert len(opaque) == 1, f"expected one OPAQUE_SECRET finding, got {findings}"
        assert opaque[0].category == "Credential"
        assert opaque[0].sensitivity == "CRITICAL"
        assert opaque[0].engine == "heuristic_stats"

    def test_engine_does_not_emit_on_non_credential_column(self, engine: HeuristicEngine) -> None:
        """A high-entropy notes column should NOT produce OPAQUE_SECRET even
        though the shape signals all align — the column-name gate rejects it.
        """
        col = ColumnInput(
            column_name="notes",
            column_id="col_notes",
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
        findings = engine.classify_column(col)
        opaque = [f for f in findings if f.entity_type == "OPAQUE_SECRET"]
        assert not opaque, f"notes column must not produce OPAQUE_SECRET, got {findings}"
