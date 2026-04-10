"""Tests for the structured secret scanner engine.

Covers parsers, key-name scoring, entropy scoring, composite scoring,
anti-indicator suppression, integration scenarios, and edge cases.
"""

from __future__ import annotations

import json

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.engines.parsers import (
    _parse_code_literals,
    _parse_env,
    _parse_json,
    _parse_yaml,
    parse_key_values,
)
from data_classifier.engines.secret_scanner import (
    SecretScannerEngine,
    _detect_charset,
    _score_key_name,
    _score_value_entropy,
)

# ── Parser tests ─────────────────────────────────────────────────────────────


class TestJsonParser:
    """Tests for JSON key-value extraction."""

    def test_simple_json(self) -> None:
        text = '{"password": "secret123!", "username": "admin"}'
        result = _parse_json(text)
        assert ("password", "secret123!") in result
        assert ("username", "admin") in result

    def test_nested_json(self) -> None:
        text = '{"db": {"password": "abc123!!", "host": "localhost"}}'
        result = _parse_json(text)
        assert ("db.password", "abc123!!") in result
        assert ("db.host", "localhost") in result

    def test_deeply_nested_json(self) -> None:
        text = '{"level1": {"level2": {"api_key": "deep_value"}}}'
        result = _parse_json(text)
        assert ("level1.level2.api_key", "deep_value") in result

    def test_json_with_array(self) -> None:
        text = '{"keys": ["val1", "val2"]}'
        result = _parse_json(text)
        assert ("keys", "val1") in result
        assert ("keys", "val2") in result

    def test_json_with_numeric_values(self) -> None:
        text = '{"port": 5432, "name": "db"}'
        result = _parse_json(text)
        assert ("port", "5432") in result

    def test_invalid_json(self) -> None:
        assert _parse_json("{invalid json") == []

    def test_json_array_root(self) -> None:
        """Root-level arrays are not supported — returns empty."""
        assert _parse_json('[{"key": "val"}]') == []

    def test_empty_json(self) -> None:
        assert _parse_json("{}") == []

    def test_json_null_values(self) -> None:
        text = '{"key": null, "other": "val"}'
        result = _parse_json(text)
        assert len(result) == 1
        assert ("other", "val") in result


class TestYamlParser:
    """Tests for YAML key-value extraction."""

    def test_simple_yaml(self) -> None:
        text = "password: secret123!\nusername: admin"
        result = _parse_yaml(text)
        assert ("password", "secret123!") in result
        assert ("username", "admin") in result

    def test_nested_yaml(self) -> None:
        text = "db:\n  password: abc123!!\n  host: localhost"
        result = _parse_yaml(text)
        assert ("db.password", "abc123!!") in result
        assert ("db.host", "localhost") in result

    def test_invalid_yaml(self) -> None:
        # Tabs are invalid in YAML — but yaml.safe_load might handle them
        # Use something truly broken
        assert _parse_yaml("") == []

    def test_yaml_scalar_root(self) -> None:
        """A plain scalar is not a dict."""
        assert _parse_yaml("just a string") == []


class TestEnvParser:
    """Tests for env-file format parsing."""

    def test_simple_env(self) -> None:
        text = "DB_PASSWORD=kJ#9xMp$2wLq!"
        result = _parse_env(text)
        assert len(result) == 1
        assert result[0][0] == "DB_PASSWORD"

    def test_export_env(self) -> None:
        text = "export API_TOKEN=a8f3b2c1d4e5"
        result = _parse_env(text)
        assert result[0] == ("API_TOKEN", "a8f3b2c1d4e5")

    def test_double_quoted_env(self) -> None:
        text = 'DB_PASS="my secret pass"'
        result = _parse_env(text)
        assert result[0] == ("DB_PASS", "my secret pass")

    def test_single_quoted_env(self) -> None:
        text = "SECRET_KEY='abc123def456'"
        result = _parse_env(text)
        assert result[0] == ("SECRET_KEY", "abc123def456")

    def test_multiline_env(self) -> None:
        text = "KEY1=val1\nKEY2=val2\nexport KEY3=val3"
        result = _parse_env(text)
        assert len(result) == 3

    def test_no_env_match(self) -> None:
        assert _parse_env("just some text") == []

    def test_empty_value_skipped(self) -> None:
        # An empty unquoted value won't match the regex
        assert _parse_env("KEY=") == []


class TestCodeLiteralParser:
    """Tests for code-style literal assignment parsing."""

    def test_double_quoted_assignment(self) -> None:
        text = 'password = "SuperSecret123!"'
        result = _parse_code_literals(text)
        assert result[0] == ("password", "SuperSecret123!")

    def test_single_quoted_assignment(self) -> None:
        text = "api_key = 'abc-def-ghi-jkl'"
        result = _parse_code_literals(text)
        assert result[0] == ("api_key", "abc-def-ghi-jkl")

    def test_walrus_operator(self) -> None:
        text = 'db_pass := "mypass123!"'
        result = _parse_code_literals(text)
        assert result[0] == ("db_pass", "mypass123!")

    def test_no_match(self) -> None:
        assert _parse_code_literals("no assignments here") == []

    def test_multiple_assignments(self) -> None:
        text = 'user = "admin"\npassword = "secret!"'
        result = _parse_code_literals(text)
        assert len(result) == 2


class TestParseKeyValues:
    """Tests for the unified parse_key_values dispatcher."""

    def test_dispatches_to_json(self) -> None:
        text = '{"api_key": "abc123def456"}'
        result = parse_key_values(text)
        assert ("api_key", "abc123def456") in result

    def test_dispatches_to_env(self) -> None:
        text = "API_KEY=abc123def456"
        result = parse_key_values(text)
        assert ("API_KEY", "abc123def456") in result

    def test_empty_input(self) -> None:
        assert parse_key_values("") == []
        assert parse_key_values("   ") == []

    def test_no_key_values(self) -> None:
        assert parse_key_values("just plain text with no structure") == []


# ── Key-name scoring tests ───────────────────────────────────────────────────


class TestKeyNameScoring:
    """Tests for key-name pattern matching."""

    @pytest.fixture()
    def key_entries(self) -> list[dict]:
        """Load key entries from the JSON file."""
        from pathlib import Path

        path = Path(__file__).parent.parent / "data_classifier" / "patterns" / "secret_key_names.json"
        with open(path) as f:
            data = json.load(f)
        return data["key_names"]

    def test_api_key_high_score(self, key_entries: list[dict]) -> None:
        score = _score_key_name("api_key", key_entries)
        assert score >= 0.90

    def test_password_high_score(self, key_entries: list[dict]) -> None:
        score = _score_key_name("password", key_entries)
        assert score >= 0.90

    def test_db_password_high_score(self, key_entries: list[dict]) -> None:
        score = _score_key_name("DB_PASSWORD", key_entries)
        assert score >= 0.90

    def test_my_custom_api_key_matches(self, key_entries: list[dict]) -> None:
        """Substring matching: 'api_key' is in 'MY_CUSTOM_API_KEY'."""
        score = _score_key_name("MY_CUSTOM_API_KEY", key_entries)
        assert score >= 0.90

    def test_name_no_match(self, key_entries: list[dict]) -> None:
        score = _score_key_name("name", key_entries)
        assert score == 0.0

    def test_config_path_no_match(self, key_entries: list[dict]) -> None:
        score = _score_key_name("config_path", key_entries)
        assert score == 0.0

    def test_username_no_match(self, key_entries: list[dict]) -> None:
        """'username' should not match 'pass' or 'password'."""
        score = _score_key_name("username", key_entries)
        assert score == 0.0

    def test_token_moderate_score(self, key_entries: list[dict]) -> None:
        score = _score_key_name("token", key_entries)
        assert 0.5 < score < 1.0


# ── Entropy scoring tests ────────────────────────────────────────────────────


class TestCharsetDetection:
    """Tests for character set detection."""

    def test_hex_string(self) -> None:
        assert _detect_charset("a1b2c3d4e5f6") == "hex"

    def test_base64_string(self) -> None:
        assert _detect_charset("ABCdef123+/=") == "base64"

    def test_alphanumeric_with_special(self) -> None:
        assert _detect_charset("kJ#9xMp$2wLq!") == "alphanumeric"

    def test_pure_digits_as_hex(self) -> None:
        assert _detect_charset("12345678") == "hex"


class TestEntropyScoring:
    """Tests for value entropy scoring."""

    @pytest.fixture()
    def thresholds(self) -> dict:
        return {"hex": 3.5, "base64": 4.0, "alphanumeric": 3.5}

    def test_high_entropy_detected(self, thresholds: dict) -> None:
        # Random-looking string with high entropy
        score = _score_value_entropy("kJ#9xMp$2wLq!", thresholds)
        assert score > 0.0

    def test_low_entropy_rejected(self, thresholds: dict) -> None:
        # Repeating characters — low entropy
        score = _score_value_entropy("aaaaaaaa", thresholds)
        assert score == 0.0

    def test_high_entropy_hex(self, thresholds: dict) -> None:
        score = _score_value_entropy("a1b2c3d4e5f6a7b8", thresholds)
        assert score > 0.0

    def test_empty_value(self, thresholds: dict) -> None:
        score = _score_value_entropy("", thresholds)
        assert score == 0.0


# ── Composite scoring tests ──────────────────────────────────────────────────


class TestCompositeScoring:
    """Tests for combined key-name + entropy scoring."""

    @pytest.fixture()
    def engine(self) -> SecretScannerEngine:
        engine = SecretScannerEngine()
        engine.startup()
        return engine

    def test_password_with_high_entropy_detected(self, engine: SecretScannerEngine) -> None:
        """DB_PASSWORD with random value should be detected."""
        column = ColumnInput(
            column_name="config_data",
            column_id="col_1",
            sample_values=["DB_PASSWORD=kJ#9xMp$2wLq!aB"],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1
        assert findings[0].entity_type == "CREDENTIAL"
        assert findings[0].confidence > 0.3

    def test_name_with_value_not_detected(self, engine: SecretScannerEngine) -> None:
        """Regular key-value pair should not be detected."""
        column = ColumnInput(
            column_name="user_data",
            column_id="col_2",
            sample_values=["name=John Smith"],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 0


# ── Anti-indicator suppression tests ─────────────────────────────────────────


class TestAntiIndicatorSuppression:
    """Tests for anti-indicator and known example suppression."""

    @pytest.fixture()
    def engine(self) -> SecretScannerEngine:
        engine = SecretScannerEngine()
        engine.startup()
        return engine

    def test_example_value_suppressed(self, engine: SecretScannerEngine) -> None:
        """Values containing 'example' should be suppressed."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["API_KEY=this_is_an_example_key_value"],
        )
        findings = engine.classify_column(column, min_confidence=0.1)
        assert len(findings) == 0

    def test_test_value_suppressed(self, engine: SecretScannerEngine) -> None:
        """Values containing 'test' should be suppressed."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["API_KEY=test_token_for_testing"],
        )
        findings = engine.classify_column(column, min_confidence=0.1)
        assert len(findings) == 0

    def test_changeme_suppressed(self, engine: SecretScannerEngine) -> None:
        """Known example 'changeme' should be suppressed."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["password=changeme"],
        )
        findings = engine.classify_column(column, min_confidence=0.1)
        assert len(findings) == 0

    def test_placeholder_in_key_suppressed(self, engine: SecretScannerEngine) -> None:
        """Keys containing 'placeholder' should be suppressed."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["placeholder_password=kJ#9xMp$2wLq!aB"],
        )
        findings = engine.classify_column(column, min_confidence=0.1)
        assert len(findings) == 0


# ── Integration tests ────────────────────────────────────────────────────────


class TestIntegration:
    """End-to-end integration tests for the secret scanner."""

    @pytest.fixture()
    def engine(self) -> SecretScannerEngine:
        engine = SecretScannerEngine()
        engine.startup()
        return engine

    def test_env_credential_detected(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="env_vars",
            column_id="col_env",
            sample_values=[
                "DB_PASSWORD=kJ#9xMp$2wLq!aB",
                "export API_TOKEN=a8f3b2c1d4e5f6a7",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) >= 1
        assert findings[0].entity_type == "CREDENTIAL"
        assert findings[0].category == "Credential"
        assert findings[0].sensitivity == "CRITICAL"
        assert findings[0].engine == "secret_scanner"

    def test_json_credential_detected(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="config_json",
            column_id="col_json",
            sample_values=[
                '{"db_password": "kJ#9xMp$2wLq!aB"}',
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) >= 1
        assert findings[0].entity_type == "CREDENTIAL"

    def test_code_literal_detected(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="source_code",
            column_id="col_code",
            sample_values=[
                'password = "kJ#9xMp$2wLq!aB"',
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) >= 1

    def test_non_secret_not_detected(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="notes",
            column_id="col_notes",
            sample_values=[
                "This is a regular note.",
                "Another note with nothing special.",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 0

    def test_sample_analysis_populated(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="config",
            column_id="col_sa",
            sample_values=["DB_PASSWORD=kJ#9xMp$2wLq!aB"],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1
        sa = findings[0].sample_analysis
        assert sa is not None
        assert sa.samples_scanned == 1
        assert sa.samples_matched >= 1

    def test_mask_samples(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="config",
            column_id="col_mask",
            sample_values=["DB_PASSWORD=kJ#9xMp$2wLq!aB"],
        )
        findings = engine.classify_column(column, min_confidence=0.3, mask_samples=True)
        assert len(findings) == 1
        sa = findings[0].sample_analysis
        assert sa is not None
        for match in sa.sample_matches:
            # Masked values should contain ***
            assert "***" in match

    def test_yaml_credential_detected(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="yaml_config",
            column_id="col_yaml",
            sample_values=[
                "db_password: kJ#9xMp$2wLq!aB",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) >= 1

    def test_nested_json_detected(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="nested_config",
            column_id="col_nested",
            sample_values=[
                '{"database": {"password": "kJ#9xMp$2wLq!aB"}}',
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) >= 1


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge case tests for the secret scanner."""

    @pytest.fixture()
    def engine(self) -> SecretScannerEngine:
        engine = SecretScannerEngine()
        engine.startup()
        return engine

    def test_empty_samples(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="empty",
            column_id="col_empty",
            sample_values=[],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 0

    def test_empty_string_samples(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="blanks",
            column_id="col_blanks",
            sample_values=["", "", ""],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 0

    def test_malformed_json_handled(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="bad_json",
            column_id="col_bad",
            sample_values=['{{"broken json}}}'],
        )
        # Should not raise — malformed input silently returns no findings
        findings = engine.classify_column(column, min_confidence=0.3)
        assert isinstance(findings, list)

    def test_short_value_rejected(self, engine: SecretScannerEngine) -> None:
        """Values shorter than min_value_length should be rejected."""
        column = ColumnInput(
            column_name="config",
            column_id="col_short",
            sample_values=["password=abc"],
        )
        findings = engine.classify_column(column, min_confidence=0.1)
        assert len(findings) == 0

    def test_no_key_value_content(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="prose",
            column_id="col_prose",
            sample_values=[
                "The quick brown fox jumps over the lazy dog.",
                "Lorem ipsum dolor sit amet.",
            ],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 0


# ── Engine registration test ─────────────────────────────────────────────────


class TestEngineRegistration:
    """Verify the secret scanner is registered in the engine cascade."""

    def test_secret_scanner_in_default_engines(self) -> None:
        from data_classifier import _DEFAULT_ENGINES

        engine_names = [e.name for e in _DEFAULT_ENGINES]
        assert "secret_scanner" in engine_names

    def test_secret_scanner_order(self) -> None:
        from data_classifier import _DEFAULT_ENGINES

        scanner = next(e for e in _DEFAULT_ENGINES if e.name == "secret_scanner")
        assert scanner.order == 4

    def test_secret_scanner_modes(self) -> None:
        from data_classifier import _DEFAULT_ENGINES

        scanner = next(e for e in _DEFAULT_ENGINES if e.name == "secret_scanner")
        assert "structured" in scanner.supported_modes
        assert "unstructured" in scanner.supported_modes

    def test_orchestrator_includes_secret_scanner(self) -> None:
        from data_classifier import _DEFAULT_ENGINES
        from data_classifier.orchestrator.orchestrator import Orchestrator

        orch = Orchestrator(engines=_DEFAULT_ENGINES, mode="structured")
        engine_names = [e.name for e in orch.engines]
        assert "secret_scanner" in engine_names
