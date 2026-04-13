"""Tests for secret_scanner fast-path rejection.

Covers ``_has_secret_indicators`` helper and its integration into the
per-sample loop of ``SecretScannerEngine.classify_column``.

Item: secret-scanner-fast-path-rejection.
"""

from __future__ import annotations

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.engines.secret_scanner import (
    SecretScannerEngine,
    _has_secret_indicators,
)

# ── Unit tests: _has_secret_indicators ───────────────────────────────────────


class TestHasSecretIndicators:
    """Structural screen for values that may carry a secret."""

    def test_empty_string_returns_false(self) -> None:
        assert _has_secret_indicators("") is False

    def test_pure_random_alphanumeric_returns_false(self) -> None:
        # No KV char, no known prefix — nothing for the parser to extract.
        assert _has_secret_indicators("R4nd0mSt1ng") is False
        assert _has_secret_indicators("abcdefghij") is False
        assert _has_secret_indicators("1234567890") is False

    def test_hex_string_returns_false(self) -> None:
        assert _has_secret_indicators("deadbeefcafebabe0123456789abcdef") is False

    def test_kv_equals_returns_true(self) -> None:
        assert _has_secret_indicators("password=xyz") is True
        assert _has_secret_indicators("api_key=abc123") is True

    def test_kv_colon_returns_true(self) -> None:
        assert _has_secret_indicators("token: abc123") is True
        assert _has_secret_indicators('{"password": "secret"}') is True

    def test_double_quote_returns_true(self) -> None:
        assert _has_secret_indicators('"secret"') is True

    def test_single_quote_returns_true(self) -> None:
        assert _has_secret_indicators("password = 'secret'") is True

    def test_github_personal_token_prefix_returns_true(self) -> None:
        # ghp_ tokens are raw secrets with no surrounding KV structure.
        assert _has_secret_indicators("ghp_abc123def456ghi789jklmnop") is True

    def test_aws_access_key_prefix_returns_true(self) -> None:
        assert _has_secret_indicators("AKIAIOSFODNN7EXAMPLE") is True
        assert _has_secret_indicators("ASIAIOSFODNN7EXAMPLE") is True

    def test_slack_token_prefix_returns_true(self) -> None:
        assert _has_secret_indicators("xoxb-1234-5678-abcdef") is True
        assert _has_secret_indicators("xoxp-1234-5678-abcdef") is True

    def test_ssh_key_prefix_returns_true(self) -> None:
        assert _has_secret_indicators("ssh-rsa AAAAB3NzaC1yc2E") is True
        assert _has_secret_indicators("ssh-ed25519 AAAAC3NzaC1l") is True

    def test_pem_header_returns_true(self) -> None:
        assert _has_secret_indicators("-----BEGIN RSA PRIVATE KEY-----") is True

    def test_jwt_prefix_returns_true(self) -> None:
        # A JWT header is base64 of {"alg":...} which always starts with eyJ
        assert _has_secret_indicators("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def") is True

    def test_bearer_token_returns_true(self) -> None:
        assert _has_secret_indicators("Bearer abc123def456") is True

    def test_authorization_header_returns_true(self) -> None:
        # Even without the colon, the header name is a signal.
        assert _has_secret_indicators("Authorization abc") is True


# ── Integration tests: classify_column gate behaviour ────────────────────────


@pytest.fixture()
def engine() -> SecretScannerEngine:
    eng = SecretScannerEngine()
    eng.startup()
    return eng


class TestFastPathIntegration:
    """Fast-path integrated into the scanner's per-sample loop."""

    def test_pure_random_column_produces_no_findings(self, engine: SecretScannerEngine) -> None:
        """A column of pure random strings should short-circuit to empty findings."""
        column = ColumnInput(
            column_name="noise",
            column_id="col_1",
            sample_values=[
                "R4nd0mSt1ng",
                "abcdefghijklmnop",
                "zyxwvutsrq",
                "0123456789abcdef",
                "deadbeefcafebabe",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert findings == []

    def test_mixed_random_and_real_tokens_still_detects_real(self, engine: SecretScannerEngine) -> None:
        """Fast-path must not prevent detection of real secrets mixed with noise."""
        column = ColumnInput(
            column_name="mixed",
            column_id="col_1",
            sample_values=[
                "R4nd0mSt1ng",  # skipped by fast-path
                "abcdefghijklmnop",  # skipped by fast-path
                'password = "kJ#9xMp$2wLq!aB"',  # real secret, KV structure
                "zyxwvutsrq",  # skipped by fast-path
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1
        # Sprint 8 Item 4: password → OPAQUE_SECRET subtype
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].category == "Credential"

    def test_empty_strings_do_not_break_fast_path(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="mixed_empty",
            column_id="col_1",
            sample_values=["", "R4nd0mSt1ng", ""],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert findings == []

    def test_kv_structured_sample_still_classified(self, engine: SecretScannerEngine) -> None:
        """Sample with `=` KV char passes fast-path and reaches the parser."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["my_token=kJ#9xMp$2wLq!aB"],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1
