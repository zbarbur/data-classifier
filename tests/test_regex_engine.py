"""Tests for the RE2 regex classification engine.

Tests both classification paths:
1. Column name matching (profile rules)
2. Sample value matching (content pattern library)

Also tests: confidence computation, deduplication, masking, category filtering.
"""

from __future__ import annotations

import pytest

from data_classifier import ColumnInput, classify_columns, load_profile
from data_classifier.engines.regex_engine import RegexEngine, _compute_sample_confidence


class TestColumnNameMatching:
    """Column name regex matching against profile rules."""

    @pytest.fixture
    def engine(self):
        e = RegexEngine()
        e.startup()
        return e

    @pytest.fixture
    def profile(self):
        return load_profile("standard")

    def test_first_match_wins(self, engine, profile):
        """When column name matches multiple rules, first rule wins."""
        col = ColumnInput(column_name="ssn_number", column_id="test:ssn_number")
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_engine_name_is_regex(self, engine, profile):
        col = ColumnInput(column_name="email", column_id="test:email")
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        assert findings[0].engine == "regex"

    def test_column_id_echoed(self, engine, profile):
        col = ColumnInput(column_name="email", column_id="custom:id:123")
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        assert findings[0].column_id == "custom:id:123"

    def test_no_match_returns_empty(self, engine, profile):
        col = ColumnInput(column_name="generic_data", column_id="test:data")
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        assert findings == []


class TestSampleValueMatching:
    """Sample value regex matching against content pattern library."""

    @pytest.fixture
    def profile(self):
        return load_profile("standard")

    def test_ssn_in_samples(self, profile):
        col = ColumnInput(
            column_name="data_field",
            column_id="test:data",
            sample_values=["123-45-6789", "987-65-4321", "hello world"],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        ssn_findings = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn_findings) == 1
        assert ssn_findings[0].sample_analysis is not None
        assert ssn_findings[0].sample_analysis.samples_matched == 2
        assert ssn_findings[0].sample_analysis.samples_scanned == 3

    def test_email_in_samples(self, profile):
        col = ColumnInput(
            column_name="notes",
            column_id="test:notes",
            sample_values=["Contact john@acme.com", "No email here", "jane@example.org"],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        email_findings = [f for f in findings if f.entity_type == "EMAIL"]
        assert len(email_findings) == 1
        assert email_findings[0].sample_analysis.samples_matched == 2

    def test_multiple_types_in_same_column(self, profile):
        """A single column can have findings for multiple entity types."""
        col = ColumnInput(
            column_name="mixed_data",
            column_id="test:mixed",
            sample_values=[
                "123-45-6789",
                "john@acme.com",
                "jane@example.org",
                "just text",
            ],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        types = {f.entity_type for f in findings}
        assert "SSN" in types
        assert "EMAIL" in types

    def test_no_samples_means_name_only(self, profile):
        """Without sample_values, only column name matching runs."""
        col = ColumnInput(column_name="email", column_id="test:email")
        findings = classify_columns([col], profile, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].sample_analysis is None  # no sample analysis

    def test_name_and_samples_deduplication(self, profile):
        """When name and samples both find SSN, highest confidence wins."""
        col = ColumnInput(
            column_name="ssn",
            column_id="test:ssn",
            sample_values=["123-45-6789"] * 10,
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        ssn_findings = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn_findings) == 1  # deduplicated


class TestMasking:
    def test_mask_samples(self):
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:mask",
            sample_values=["123-45-6789", "john@acme.com"],
        )
        findings = classify_columns([col], profile, min_confidence=0.0, mask_samples=True)
        for f in findings:
            if f.sample_analysis and f.sample_analysis.sample_matches:
                for match in f.sample_analysis.sample_matches:
                    assert "*" in match, f"Expected masked value, got: {match}"


class TestConfidenceComputation:
    def test_zero_matches_returns_zero(self):
        assert _compute_sample_confidence(0.95, 0, 0) == 0.0

    def test_single_match_penalty(self):
        conf = _compute_sample_confidence(0.95, 1, 1)
        assert 0.55 < conf < 0.70  # 0.95 * 0.65

    def test_few_matches_moderate_penalty(self):
        conf = _compute_sample_confidence(0.95, 3, 3)
        assert 0.75 < conf < 0.85  # 0.95 * 0.85

    def test_many_matches_full_confidence(self):
        conf = _compute_sample_confidence(0.95, 10, 10)
        assert conf == 0.95

    def test_abundant_matches_slight_boost(self):
        conf = _compute_sample_confidence(0.95, 25, 25)
        assert conf > 0.95

    def test_validation_failures_reduce_confidence(self):
        conf_all_valid = _compute_sample_confidence(0.95, 10, 10)
        conf_half_valid = _compute_sample_confidence(0.95, 10, 5)
        assert conf_half_valid < conf_all_valid

    def test_no_validations_zeroes_confidence(self):
        conf = _compute_sample_confidence(0.95, 10, 0)
        assert conf == 0.0


class TestCategoryFiltering:
    def test_filter_to_single_category(self):
        profile = load_profile("standard")
        columns = [
            ColumnInput(column_name="ssn", column_id="test:ssn"),
            ColumnInput(column_name="credit_card", column_id="test:cc"),
            ColumnInput(column_name="password", column_id="test:pw"),
        ]
        findings = classify_columns(columns, profile, min_confidence=0.0, categories=["PII"])
        assert all(f.category == "PII" for f in findings)
        assert len(findings) == 1  # only SSN is PII

    def test_filter_to_multiple_categories(self):
        profile = load_profile("standard")
        columns = [
            ColumnInput(column_name="ssn", column_id="test:ssn"),
            ColumnInput(column_name="credit_card", column_id="test:cc"),
            ColumnInput(column_name="password", column_id="test:pw"),
        ]
        findings = classify_columns(columns, profile, min_confidence=0.0, categories=["PII", "Credential"])
        categories = {f.category for f in findings}
        assert "Financial" not in categories

    def test_no_filter_returns_all(self):
        profile = load_profile("standard")
        columns = [
            ColumnInput(column_name="ssn", column_id="test:ssn"),
            ColumnInput(column_name="credit_card", column_id="test:cc"),
            ColumnInput(column_name="password", column_id="test:pw"),
        ]
        findings = classify_columns(columns, profile, min_confidence=0.0)
        assert len(findings) == 3


class TestMinConfidenceThreshold:
    def test_default_threshold_filters_low_confidence(self):
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=["123-45-6789"],  # single match → ~0.62 confidence
        )
        # Default min_confidence=0.5 should keep this
        findings = classify_columns([col], profile)
        ssn = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn) == 1

    def test_high_threshold_filters_more(self):
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=["123-45-6789"],  # single match → ~0.62
        )
        findings = classify_columns([col], profile, min_confidence=0.9)
        ssn = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn) == 0  # filtered out


class TestValidators:
    def test_ssn_zeros_rejected(self):
        """SSN values with all-zeros groups should reduce validated count."""
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=["000-45-6789", "123-00-6789", "123-45-0000", "123-45-6789"],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        ssn = [f for f in findings if f.entity_type == "SSN"]
        if ssn:
            sa = ssn[0].sample_analysis
            assert sa is not None
            assert sa.samples_matched == 4  # all match regex
            assert sa.samples_validated == 1  # only 123-45-6789 passes validator

    def test_luhn_validates_credit_cards(self):
        """Luhn-valid CC numbers pass, invalid ones reduce validation count."""
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=["4111111111111111", "4111111111111112"],  # valid, invalid Luhn
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        cc = [f for f in findings if f.entity_type == "CREDIT_CARD"]
        if cc:
            sa = cc[0].sample_analysis
            assert sa is not None
            assert sa.samples_matched == 2
            assert sa.samples_validated == 1  # only 4111...1111 passes Luhn

    def test_sin_luhn_validator_unit(self):
        """sin_luhn_check handles formatted, unformatted, and invalid SINs."""
        from data_classifier.engines.validators import sin_luhn_check

        # Valid formatted SIN — spaces
        assert sin_luhn_check("046 454 286") is True
        # Valid formatted SIN — dashes
        assert sin_luhn_check("046-454-286") is True
        # Valid unformatted SIN — the bug case
        assert sin_luhn_check("046454286") is True
        # Wrong length — 8 digits
        assert sin_luhn_check("04645428") is False
        # Wrong length — 10 digits
        assert sin_luhn_check("0464542860") is False
        # Correct length but fails Luhn checksum
        assert sin_luhn_check("046454287") is False

    def test_sin_luhn_validates_formatted_and_unformatted(self):
        """Canadian SIN classification accepts both formatted and unformatted values.

        Uses a neutral column name so the content engine (not column-name engine) fires.
        """
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=[
                "046 454 286",  # formatted spaces — valid Luhn
                "046-454-286",  # formatted dashes — valid Luhn
                "046454286",  # unformatted — the bug case, valid Luhn
                "046454287",  # unformatted — fails Luhn
            ],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        sin = [f for f in findings if f.entity_type == "CANADIAN_SIN"]
        assert sin, "Expected CANADIAN_SIN finding"
        sa = sin[0].sample_analysis
        assert sa is not None
        assert sa.samples_matched == 4  # all 4 match the regex
        assert sa.samples_validated == 3  # 3 pass Luhn; 046454287 fails


class TestIntrospection:
    def test_get_supported_categories(self):
        from data_classifier import get_supported_categories

        cats = get_supported_categories()
        assert "PII" in cats
        assert "Financial" in cats
        assert "Credential" in cats
        assert "Health" in cats

    def test_get_supported_entity_types(self):
        from data_classifier import get_supported_entity_types

        types = get_supported_entity_types()
        assert len(types) >= 15
        type_names = {t["entity_type"] for t in types}
        assert "SSN" in type_names
        assert "EMAIL" in type_names

    def test_get_supported_sensitivity_levels(self):
        from data_classifier import get_supported_sensitivity_levels

        levels = get_supported_sensitivity_levels()
        assert levels == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    def test_get_pattern_library(self):
        from data_classifier import get_pattern_library

        patterns = get_pattern_library()
        assert len(patterns) >= 40
        assert all("name" in p for p in patterns)
        assert all("regex" in p for p in patterns)
