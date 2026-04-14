"""Tests for the structured secret scanner engine.

Covers parsers, key-name scoring, entropy scoring, tiered composite scoring,
match-type filtering, anti-indicator suppression, integration scenarios,
and edge cases.
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
    _compute_relative_entropy,
    _detect_charset,
    _match_key_pattern,
    _score_key_name,
    _score_relative_entropy,
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


# ── Match-type tests ────────────────────────────────────────────────────────


class TestMatchType:
    """Tests for word_boundary and suffix match-type logic."""

    def test_word_boundary_matches_whole_word(self) -> None:
        assert _match_key_pattern("auth_token", "auth", "word_boundary") is True

    def test_word_boundary_matches_at_start(self) -> None:
        assert _match_key_pattern("auth", "auth", "word_boundary") is True

    def test_word_boundary_matches_after_separator(self) -> None:
        assert _match_key_pattern("my_auth", "auth", "word_boundary") is True

    def test_word_boundary_rejects_substring(self) -> None:
        """'auth' should NOT match 'author' or 'authenticate'."""
        assert _match_key_pattern("author", "auth", "word_boundary") is False
        assert _match_key_pattern("authenticate", "auth", "word_boundary") is False

    def test_word_boundary_rejects_internal_substring(self) -> None:
        """'token' should NOT match 'tokenize'."""
        assert _match_key_pattern("tokenize", "token", "word_boundary") is False

    def test_word_boundary_pass_rejects_bypass(self) -> None:
        """'pass' should NOT match 'bypass'."""
        assert _match_key_pattern("bypass", "pass", "word_boundary") is False

    def test_word_boundary_hash_rejects_hashtag(self) -> None:
        """'hash' should NOT match 'hashtag'."""
        assert _match_key_pattern("hashtag", "hash", "word_boundary") is False

    def test_word_boundary_salt_rejects_basalt(self) -> None:
        """'salt' should NOT match 'basalt'."""
        assert _match_key_pattern("basalt", "salt", "word_boundary") is False

    def test_suffix_matches_after_separator(self) -> None:
        assert _match_key_pattern("api_key", "key", "suffix") is True
        assert _match_key_pattern("secret_key", "key", "suffix") is True
        assert _match_key_pattern("my-key", "key", "suffix") is True

    def test_suffix_rejects_bare_word(self) -> None:
        """'key' alone (without a preceding separator) should NOT match as suffix."""
        assert _match_key_pattern("key", "key", "suffix") is False

    def test_suffix_rejects_substring(self) -> None:
        """'key' should NOT match 'keyboard' or 'monkey'."""
        assert _match_key_pattern("keyboard", "key", "suffix") is False
        assert _match_key_pattern("monkey", "key", "suffix") is False

    def test_substring_matches_anywhere(self) -> None:
        assert _match_key_pattern("my_password_field", "password", "substring") is True
        assert _match_key_pattern("password", "password", "substring") is True


# ── Key-name scoring tests ───────────────────────────────────────────────────


class TestKeyNameScoring:
    """Tests for key-name pattern matching with match_type and tier."""

    @pytest.fixture()
    def key_entries(self) -> list[dict]:
        """Load key entries from the JSON file."""
        from pathlib import Path

        path = Path(__file__).parent.parent / "data_classifier" / "patterns" / "secret_key_names.json"
        with open(path) as f:
            data = json.load(f)
        return data["key_names"]

    def test_api_key_high_score(self, key_entries: list[dict]) -> None:
        score, tier, _subtype = _score_key_name("api_key", key_entries)
        assert score >= 0.90
        assert tier == "definitive"

    def test_password_high_score(self, key_entries: list[dict]) -> None:
        score, tier, _subtype = _score_key_name("password", key_entries)
        assert score >= 0.90
        assert tier == "definitive"

    def test_db_password_high_score(self, key_entries: list[dict]) -> None:
        score, tier, _subtype = _score_key_name("DB_PASSWORD", key_entries)
        assert score >= 0.90

    def test_my_custom_api_key_matches(self, key_entries: list[dict]) -> None:
        """Substring matching: 'api_key' is in 'MY_CUSTOM_API_KEY'."""
        score, _tier, _subtype = _score_key_name("MY_CUSTOM_API_KEY", key_entries)
        assert score >= 0.90

    def test_name_no_match(self, key_entries: list[dict]) -> None:
        score, _tier, _subtype = _score_key_name("name", key_entries)
        assert score == 0.0

    def test_config_path_no_match(self, key_entries: list[dict]) -> None:
        score, _tier, _subtype = _score_key_name("config_path", key_entries)
        assert score == 0.0

    def test_username_no_match(self, key_entries: list[dict]) -> None:
        """'username' should not match 'pass' or 'password'."""
        score, _tier, _subtype = _score_key_name("username", key_entries)
        assert score == 0.0

    def test_token_moderate_score(self, key_entries: list[dict]) -> None:
        score, tier, _subtype = _score_key_name("token", key_entries)
        assert 0.5 < score < 1.0
        assert tier == "strong"

    def test_author_not_matched(self, key_entries: list[dict]) -> None:
        """'author' should NOT match 'auth' (word_boundary)."""
        score, _tier, _subtype = _score_key_name("author", key_entries)
        assert score == 0.0

    def test_keyboard_not_matched(self, key_entries: list[dict]) -> None:
        """'keyboard' should NOT match 'key' (suffix)."""
        score, _tier, _subtype = _score_key_name("keyboard", key_entries)
        assert score == 0.0

    def test_authenticate_not_matched(self, key_entries: list[dict]) -> None:
        """'authenticate' should NOT match 'auth' (word_boundary)."""
        score, _tier, _subtype = _score_key_name("authenticate", key_entries)
        assert score == 0.0

    def test_auth_token_matches_definitive(self, key_entries: list[dict]) -> None:
        """'auth_token' should match the specific 'auth_token' pattern (definitive)."""
        score, tier, _subtype = _score_key_name("auth_token", key_entries)
        assert score >= 0.90
        assert tier == "definitive"

    def test_my_auth_matches(self, key_entries: list[dict]) -> None:
        """'my_auth' should match 'auth' at word boundary."""
        score, _tier, _subtype = _score_key_name("my_auth", key_entries)
        assert score > 0.0


# ── Charset detection tests ─────────────────────────────────────────────────


class TestCharsetDetection:
    """Tests for character set detection."""

    def test_hex_string(self) -> None:
        assert _detect_charset("a1b2c3d4e5f6") == "hex"

    def test_base64_string(self) -> None:
        assert _detect_charset("ABCdef123+/=") == "base64"

    def test_alphanumeric_classified_as_base64(self) -> None:
        """Pure alphanumeric is a subset of base64 charset."""
        assert _detect_charset("ABCdef123xyz") == "base64"

    def test_full_charset(self) -> None:
        assert _detect_charset("kJ#9xMp$2wLq!") == "full"

    def test_pure_digits_as_hex(self) -> None:
        assert _detect_charset("12345678") == "hex"


# ── Relative entropy tests ──────────────────────────────────────────────────


class TestRelativeEntropy:
    """Tests for relative entropy computation and scoring."""

    def test_high_entropy_hex(self) -> None:
        """High-entropy hex should have relative entropy near 1.0."""
        rel = _compute_relative_entropy("a1b2c3d4e5f6a7b8")
        assert rel > 0.7

    def test_low_entropy_repeating(self) -> None:
        """Repeating chars should have very low relative entropy."""
        rel = _compute_relative_entropy("aaaaaaaa")
        assert rel < 0.2

    def test_relative_entropy_bounded(self) -> None:
        """Relative entropy should never exceed 1.0."""
        rel = _compute_relative_entropy("kJ#9xMp$2wLq!aB")
        assert 0.0 <= rel <= 1.0

    def test_score_below_threshold_is_zero(self) -> None:
        assert _score_relative_entropy(0.3) == 0.0
        assert _score_relative_entropy(0.49) == 0.0

    def test_score_at_threshold(self) -> None:
        assert _score_relative_entropy(0.5) == 0.5

    def test_score_high_value(self) -> None:
        assert _score_relative_entropy(0.9) == 0.9

    def test_score_capped_at_one(self) -> None:
        assert _score_relative_entropy(1.5) == 1.0


# ── Tiered composite scoring tests ──────────────────────────────────────────


class TestTieredScoring:
    """Tests for the tiered scoring model."""

    @pytest.fixture()
    def engine(self) -> SecretScannerEngine:
        engine = SecretScannerEngine()
        engine.startup()
        return engine

    def test_definitive_password_with_low_entropy(self, engine: SecretScannerEngine) -> None:
        """password='admin123' SHOULD be detected — definitive tier bypasses entropy."""
        column = ColumnInput(
            column_name="config_data",
            column_id="col_1",
            sample_values=['password = "admin12345"'],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1
        # Sprint 8 Item 4: password key → OPAQUE_SECRET subtype
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].category == "Credential"
        assert findings[0].confidence > 0.5

    def test_definitive_tier_rejects_placeholder(self, engine: SecretScannerEngine) -> None:
        """Definitive key with known placeholder value should NOT be detected."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["password=changeme"],
        )
        findings = engine.classify_column(column, min_confidence=0.1)
        assert len(findings) == 0

    def test_strong_tier_with_high_entropy(self, engine: SecretScannerEngine) -> None:
        """'token' (strong tier) with high-entropy value should be detected."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["my_token=kJ#9xMp$2wLq!aB"],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1

    def test_strong_tier_with_low_entropy_rejected(self, engine: SecretScannerEngine) -> None:
        """'token' (strong tier) with low-entropy value should NOT be detected."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["my_token=aaaaaaaa"],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 0

    def test_contextual_tier_needs_strong_signal(self, engine: SecretScannerEngine) -> None:
        """'hash' (contextual) with high-entropy diverse value should be detected."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["my_hash=xK7#mQ2$pL9!nR4wB6@jF8dZ3&hY5"],
        )
        findings = engine.classify_column(column, min_confidence=0.1)
        assert len(findings) == 1

    def test_contextual_tier_rejects_low_diversity(self, engine: SecretScannerEngine) -> None:
        """'hash' (contextual) with hex-only value (low diversity) should NOT be detected."""
        column = ColumnInput(
            column_name="config",
            column_id="col_1",
            sample_values=["my_hash=a1b2c3d4e5f6a7b8"],
        )
        findings = engine.classify_column(column, min_confidence=0.1)
        assert len(findings) == 0

    def test_password_with_high_entropy_detected(self, engine: SecretScannerEngine) -> None:
        """DB_PASSWORD with random value should be detected."""
        column = ColumnInput(
            column_name="config_data",
            column_id="col_1",
            sample_values=["DB_PASSWORD=kJ#9xMp$2wLq!aB"],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1
        # Sprint 8 Item 4: DB_PASSWORD key → OPAQUE_SECRET subtype
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].category == "Credential"
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
        """Known placeholder 'changeme' should be suppressed."""
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
        # Sprint 8 Item 4: DB_PASSWORD / API_TOKEN both resolve to the new
        # credential subtypes (OPAQUE_SECRET and API_KEY respectively).
        assert findings[0].entity_type in {"OPAQUE_SECRET", "API_KEY"}
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
        # Sprint 8 Item 4: db_password → OPAQUE_SECRET subtype
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].category == "Credential"

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


# ── Sprint 10: net-new dictionary entries (Kingfisher/gitleaks/NP harvest) ──
#
# Item: expand-secret-key-names-dictionary-kingfisher-gitleaks-nosey-parker-
# 80-net-new-entries-sprint-10-m-sibling-of-kingfisher-l
#
# These tests cover:
#   1. TestNewDictionaryEntries — every curated net-new pattern fires with
#      the recorded (score, tier, subtype) tuple.
#   2. TestIngestionScript      — idempotence and required-field schema.
#   3. TestDictionaryHealth     — full-dict invariants on patterns, scores,
#      tiers, and match types.


def _import_ingest_module():
    """Import scripts/ingest_credential_patterns.py as ``ingest_credential_patterns``.

    Python 3.12+ requires the module to be registered in ``sys.modules``
    BEFORE ``exec_module`` so that @dataclass decoration (which looks up
    the defining module via ``sys.modules[cls.__module__].__dict__``)
    succeeds.  Cached on second call.
    """
    import importlib.util
    import sys as _sys
    from pathlib import Path

    if "ingest_credential_patterns" in _sys.modules:
        return _sys.modules["ingest_credential_patterns"]
    script = Path(__file__).parent.parent / "scripts" / "ingest_credential_patterns.py"
    spec = importlib.util.spec_from_file_location("ingest_credential_patterns", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    _sys.modules["ingest_credential_patterns"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_curated_manifest() -> list[dict]:
    """Import the curated manifest from scripts/ingest_credential_patterns.py.

    Returns a list of dicts with keys:
        pattern, score, match_type, tier, subtype, category_tag,
        upstream, upstream_rule_id.
    """
    module = _import_ingest_module()
    return [
        {
            "pattern": e.pattern,
            "score": e.score,
            "match_type": e.match_type,
            "tier": e.tier,
            "subtype": e.subtype,
            "category_tag": e.category_tag,
            "upstream": e.upstream,
            "upstream_rule_id": e.upstream_rule_id,
        }
        for e in module.CURATED_ENTRIES
    ]


def _load_full_dictionary() -> list[dict]:
    """Read all key_names entries from secret_key_names.json."""
    from pathlib import Path

    path = Path(__file__).parent.parent / "data_classifier" / "patterns" / "secret_key_names.json"
    with open(path) as fh:
        return json.load(fh)["key_names"]


_CURATED_MANIFEST = _load_curated_manifest()


class TestNewDictionaryEntries:
    """Parametrized test: each curated net-new entry fires with recorded tier/subtype.

    The test key used is the pattern itself (a real-world key like
    ``datadog_app_key`` is itself a sensible test input).  The expectation
    is that ``_score_key_name`` returns a score >= the entry's recorded
    score, and the same subtype.  A stronger existing pattern may win
    (e.g., ``password`` outranks ``admin_password``) — that's an acceptable
    outcome because it still fires and attributes to a credential subtype
    with equal-or-higher confidence.  The assertion therefore uses
    ``>=`` on score and checks subtype consistency within the credential
    taxonomy, not exact equality to the manifest entry.
    """

    @pytest.fixture(scope="class")
    def key_entries(self) -> list[dict]:
        return _load_full_dictionary()

    @pytest.mark.parametrize(
        "entry",
        _CURATED_MANIFEST,
        ids=[e["pattern"] for e in _CURATED_MANIFEST],
    )
    def test_new_entry_fires_with_expected_tier_and_subtype(self, entry: dict, key_entries: list[dict]) -> None:
        score, tier, subtype = _score_key_name(entry["pattern"], key_entries)
        # The entry must fire with at least the recorded score.
        assert score >= entry["score"], f"{entry['pattern']}: got score {score}, expected >= {entry['score']}"
        # Tier must be at least as strong as recorded
        # (definitive > strong > contextual).
        tier_rank = {"contextual": 0, "strong": 1, "definitive": 2}
        assert tier_rank[tier] >= tier_rank[entry["tier"]], (
            f"{entry['pattern']}: got tier {tier!r}, expected >= {entry['tier']!r}"
        )
        # Subtype must be in the credential taxonomy.
        assert subtype in {"API_KEY", "OPAQUE_SECRET", "PRIVATE_KEY", "PASSWORD_HASH"}

    def test_manifest_has_at_least_80_entries(self) -> None:
        assert len(_CURATED_MANIFEST) >= 80, f"Manifest has {len(_CURATED_MANIFEST)} entries, minimum 80"

    def test_manifest_within_hard_ceiling(self) -> None:
        assert len(_CURATED_MANIFEST) <= 95, f"Manifest has {len(_CURATED_MANIFEST)} entries, hard ceiling 95"

    def test_definitive_fraction_above_60_percent(self) -> None:
        definitive = sum(1 for e in _CURATED_MANIFEST if e["tier"] == "definitive")
        frac = definitive / max(len(_CURATED_MANIFEST), 1)
        assert frac >= 0.60, f"Definitive fraction {frac:.2%}, minimum 60%"

    @pytest.mark.parametrize(
        "category, minimum",
        [
            ("saas", 30),
            ("cloud", 15),
            ("cicd", 12),
            ("database", 8),
            ("oauth", 6),
            ("pwd_crypto", 13),
        ],
    )
    def test_category_minimum_counts_met(self, category: str, minimum: int) -> None:
        got = sum(1 for e in _CURATED_MANIFEST if e["category_tag"] == category)
        assert got >= minimum, f"Category {category}: {got} entries, minimum {minimum}"


class TestIngestionScript:
    """Tests for scripts/ingest_credential_patterns.py."""

    def test_ingest_script_is_idempotent(self) -> None:
        """Running the script twice leaves the dictionary byte-identical.

        First run syncs any missing entries.  Second run must report
        zero changes and touch no files.
        """
        from pathlib import Path

        module = _import_ingest_module()
        dict_path = Path(module.DICT_PATH)
        md_path = Path(module.ATTRIBUTION_MD_PATH)

        # First pass (usually already a no-op on disk, but may normalize).
        rc = module.main([])
        assert rc == 0
        dict_snapshot = dict_path.read_bytes()
        md_snapshot = md_path.read_bytes() if md_path.exists() else b""

        # Second pass must be bit-for-bit identical on disk.
        rc2 = module.main([])
        assert rc2 == 0
        assert dict_path.read_bytes() == dict_snapshot, "Dictionary file changed on second script run — not idempotent"
        assert md_path.read_bytes() == md_snapshot, "Attribution md changed on second script run — not idempotent"

    def test_all_new_entries_have_required_fields(self) -> None:
        """Every curated entry must have pattern, score, match_type, tier, subtype."""
        required = {"pattern", "score", "match_type", "tier", "subtype"}
        for entry in _CURATED_MANIFEST:
            missing = required - entry.keys()
            assert not missing, f"{entry.get('pattern', '?')}: missing fields {missing}"
            # Also sanity-check field types
            assert isinstance(entry["pattern"], str)
            assert isinstance(entry["score"], float)
            assert entry["match_type"] in {"substring", "word_boundary", "suffix"}
            assert entry["tier"] in {"definitive", "strong", "contextual"}
            assert entry["subtype"] in {
                "API_KEY",
                "OPAQUE_SECRET",
                "PRIVATE_KEY",
                "PASSWORD_HASH",
            }

    def test_manifest_validation_passes(self) -> None:
        """validate_manifest() returns zero errors for the current manifest."""
        module = _import_ingest_module()
        errors = module.validate_manifest(module.CURATED_ENTRIES)
        assert errors == [], f"Manifest validation errors: {errors}"


class TestDictionaryHealth:
    """Invariants on the full secret_key_names.json file (existing + net-new)."""

    def test_dictionary_has_no_duplicate_patterns(self) -> None:
        entries = _load_full_dictionary()
        patterns = [e["pattern"].lower() for e in entries]
        duplicates = {p for p in patterns if patterns.count(p) > 1}
        assert not duplicates, f"Duplicate patterns: {duplicates}"

    def test_dictionary_scores_in_valid_range(self) -> None:
        entries = _load_full_dictionary()
        for e in entries:
            assert 0.0 <= e["score"] <= 1.0, f"{e['pattern']}: score {e['score']} out of [0, 1]"

    def test_dictionary_tiers_valid(self) -> None:
        entries = _load_full_dictionary()
        valid = {"definitive", "strong", "contextual"}
        for e in entries:
            assert e["tier"] in valid, f"{e['pattern']}: invalid tier {e['tier']!r}"

    def test_dictionary_match_types_valid(self) -> None:
        entries = _load_full_dictionary()
        valid = {"substring", "word_boundary", "suffix"}
        for e in entries:
            assert e["match_type"] in valid, f"{e['pattern']}: invalid match_type {e['match_type']!r}"

    def test_dictionary_subtypes_valid(self) -> None:
        entries = _load_full_dictionary()
        valid = {"API_KEY", "OPAQUE_SECRET", "PRIVATE_KEY", "PASSWORD_HASH"}
        for e in entries:
            assert e["subtype"] in valid, f"{e['pattern']}: invalid subtype {e['subtype']!r}"

    def test_dictionary_grew_from_88_baseline(self) -> None:
        """Sanity guard: Sprint 9 baseline was 88 entries.  We must have
        grown by at least the hard-minimum 80 net-new."""
        entries = _load_full_dictionary()
        assert len(entries) >= 88 + 80, (
            f"Dictionary has {len(entries)} entries, expected >= 168 (88 baseline + 80 minimum net-new)"
        )


class TestMatchTypeTightening:
    """Sprint 11 item #4 — ``id_token`` and ``token_secret`` must not fire
    on substring-containing compound identifiers.

    The pre-Sprint-11 ``match_type: substring`` rule caused the id_token
    pattern to over-fire on any key whose middle or suffix happened to
    contain the literal string ``id_token`` (e.g. ``rapid_token`` — the
    substring ``id_token`` occurs at positions 3–10). Tightening to
    ``match_type: word_boundary`` requires the pattern to be preceded
    and followed by a word-break character (``^``, ``_``, ``-``, ``.``,
    whitespace, or ``$``).

    These tests pin both the JSON-level invariant and the runtime
    behaviour so neither can silently regress.
    """

    def _find_entry(self, pattern: str) -> dict:
        entries = _load_full_dictionary()
        matches = [e for e in entries if e["pattern"] == pattern]
        assert len(matches) == 1, f"expected exactly one entry for {pattern!r}, got {len(matches)}"
        return matches[0]

    def test_id_token_uses_word_boundary_match_type(self) -> None:
        entry = self._find_entry("id_token")
        assert entry["match_type"] == "word_boundary", (
            f"id_token must use word_boundary match_type (was {entry['match_type']!r})"
        )

    def test_token_secret_uses_word_boundary_match_type(self) -> None:
        entry = self._find_entry("token_secret")
        assert entry["match_type"] == "word_boundary", (
            f"token_secret must use word_boundary match_type (was {entry['match_type']!r})"
        )

    @pytest.mark.parametrize(
        "key",
        [
            "id_token",
            "user_id_token",
            "id_token_v2",
            "oauth.id_token",
            "ID_TOKEN",  # case-insensitive
        ],
    )
    def test_id_token_still_matches_legitimate_keys(self, key: str) -> None:
        """Positive regression: the tightened pattern must still fire on real id_token columns."""
        from data_classifier.engines.secret_scanner import _match_key_pattern

        assert _match_key_pattern(key.lower(), "id_token", "word_boundary"), (
            f"tightened id_token pattern should still match {key!r}"
        )

    @pytest.mark.parametrize(
        "key",
        [
            "rapid_token",  # "id_token" at positions 3–10, preceded by "p"
            "avid_tokens",  # "id_token" at positions 1–8, preceded by "v"
            "mid_token_v2",  # "id_token" at positions 1–8, preceded by "m"
            "squid_token",  # "id_token" at positions 3–10, preceded by "u"
        ],
    )
    def test_id_token_does_not_fire_on_compound_substrings(self, key: str) -> None:
        """Negative regression: the tightened pattern must NOT fire on unrelated compound keys."""
        from data_classifier.engines.secret_scanner import _match_key_pattern

        assert not _match_key_pattern(key.lower(), "id_token", "word_boundary"), (
            f"tightened id_token pattern should NOT match {key!r}"
        )

    @pytest.mark.parametrize(
        "key",
        [
            "token_secret",
            "api_token_secret",
            "token_secret_v2",
            "oauth.token_secret",
            "TOKEN_SECRET",
        ],
    )
    def test_token_secret_still_matches_legitimate_keys(self, key: str) -> None:
        from data_classifier.engines.secret_scanner import _match_key_pattern

        assert _match_key_pattern(key.lower(), "token_secret", "word_boundary"), (
            f"tightened token_secret pattern should still match {key!r}"
        )

    @pytest.mark.parametrize(
        "key",
        [
            "bigtoken_secret",  # "token_secret" at positions 3–14, preceded by "g"
            "atoken_secrets",  # preceded by "a", suffix "s"
            "mytoken_secret_v2",  # preceded by "y"
        ],
    )
    def test_token_secret_does_not_fire_on_compound_substrings(self, key: str) -> None:
        from data_classifier.engines.secret_scanner import _match_key_pattern

        assert not _match_key_pattern(key.lower(), "token_secret", "word_boundary"), (
            f"tightened token_secret pattern should NOT match {key!r}"
        )
