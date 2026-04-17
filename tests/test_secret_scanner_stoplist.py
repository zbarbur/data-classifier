"""Tests for the compound-name stoplist (Sprint 13 S0-3)."""

from __future__ import annotations

import pytest

from data_classifier import load_profile
from data_classifier.core.types import ColumnInput
from data_classifier.engines.secret_scanner import _is_compound_non_secret

PROFILE = load_profile("standard")


class TestIsCompoundNonSecret:
    """Unit tests for the suffix-based stoplist helper."""

    @pytest.mark.parametrize(
        "key",
        [
            "token_address",
            "wallet_address",
            "password_field",
            "secret_name",
            "api_url",
            "auth_endpoint",
            "key_label",
            "token_placeholder",
            "secret_input",
            "api_id",
        ],
    )
    def test_non_secret_compound_rejected(self, key):
        assert _is_compound_non_secret(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "session_id",  # allowlisted — sensitive
            "auth_id",  # allowlisted — sensitive
            "client_id",  # allowlisted — sensitive
        ],
    )
    def test_allowlisted_compounds_kept(self, key):
        assert _is_compound_non_secret(key) is False

    @pytest.mark.parametrize(
        "key",
        [
            "api_key",  # _key suffix NOT in stoplist
            "api_token",  # _token suffix NOT in stoplist
            "db_password",  # _password suffix NOT in stoplist
            "auth_secret",  # _secret suffix NOT in stoplist
        ],
    )
    def test_real_secret_keys_not_stopped(self, key):
        assert _is_compound_non_secret(key) is False


class TestStoplistSecretScannerLevel:
    """Secret_scanner engine level: compound names must not produce findings."""

    def _run_secret_scanner(self, sample_values: list[str], column_name: str = "code") -> list:
        from data_classifier.engines.secret_scanner import SecretScannerEngine

        engine = SecretScannerEngine()
        engine.startup()
        column = ColumnInput(
            column_id="t",
            column_name=column_name,
            sample_values=sample_values,
        )
        return engine.classify_column(column, profile=PROFILE)

    def test_token_address_solana_not_flagged(self):
        """S0 FP: token_address = Solana public wallet address."""
        findings = self._run_secret_scanner(['token_address = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"'] * 10)
        assert findings == [], f"token_address should not fire in secret_scanner: {findings}"

    def test_password_field_selenium_not_flagged(self):
        """S0 FP: password_field = Selenium element handle."""
        findings = self._run_secret_scanner(
            ["password_field = wait.until(expected_conditions.visibility_of_element_located(locator))"] * 10
        )
        assert findings == [], f"password_field should not fire in secret_scanner: {findings}"

    def test_api_url_not_flagged(self):
        """Compound ending with _url should not fire."""
        findings = self._run_secret_scanner(['api_url = "https://api.example.com/v1/tokens"'] * 10)
        assert findings == [], f"api_url should not fire: {findings}"

    def test_real_password_still_fires(self):
        """Sanity: db_password = real secret must still be detected."""
        findings = self._run_secret_scanner(
            ['db_password = "kJ#9xMp$2wLq!"'] * 10,
            column_name="config",
        )
        assert len(findings) >= 1, "Real db_password should still be detected by secret_scanner"
