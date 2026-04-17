"""Tests for Sprint 14: disable cascade short-circuit on free_text_heterogeneous shape.

On heterogeneous columns (mixed entity types), the orchestrator must preserve
findings from ALL engines — authority-based suppression must not discard
lower-authority entity types. On structured_single columns, authority
suppression must continue to work as before.
"""

from __future__ import annotations

import pytest

from data_classifier import ColumnInput, load_profile
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.orchestrator.orchestrator import Orchestrator
from data_classifier.orchestrator.shape_detector import detect_column_shape


def _classify_no_ml(column: ColumnInput, profile, **kwargs) -> list:
    """Classify a single column WITHOUT GLiNER — tests cascade/router behavior only."""
    engines = [ColumnNameEngine(), RegexEngine(), HeuristicEngine(), SecretScannerEngine()]
    orch = Orchestrator(engines=engines, mode="structured", meta_classifier_directive=False)
    return orch.classify_column(column, profile, **kwargs)


@pytest.fixture
def profile():
    return load_profile("standard")


# ── Core test: heterogeneous column preserves multi-entity findings ──────


class TestHeterogeneousNoShortCircuit:
    """Heterogeneous columns must run all engines and keep all entity types."""

    def test_credential_column_with_urls_produces_both_entity_types(self, profile):
        """Column named 'api_key' with values containing BOTH credentials AND URLs.

        The column_name engine fires first (authority=10) and finds CREDENTIAL.
        The regex engine (authority=5) finds URL in the URL-shaped values.
        On a heterogeneous column, BOTH must survive — authority suppression
        must NOT discard the URL finding.
        """
        column = ColumnInput(
            column_name="api_key",
            column_id="test_hetero_cred_url",
            sample_values=[
                "_STRIPE_TEST_KEY",
                "https://api.example.com/v2/users",
                "pk_test_xxxxxxxxxxxxxxxxxxxxxxxx",
                "https://cdn.example.org/assets/logo.png",
                "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
                "https://hooks.slack.com/services/T00/B00/xxxx",
                "The quick brown fox jumps over the lazy dog near the river",
                "Please check the documentation at https://docs.example.com/api",
            ],
        )
        findings = _classify_no_ml(column, profile, min_confidence=0.0)
        entity_types = {f.entity_type for f in findings}

        # Must find credential-family entity (from column_name or regex/secret_scanner)
        credential_types = {"CREDENTIAL", "API_KEY", "SECRET_KEY", "ENCRYPTION_KEY"}
        assert entity_types & credential_types, f"Expected at least one credential type in findings, got {entity_types}"

        # Must find URL (from regex engine — NOT suppressed by authority)
        assert "URL" in entity_types, (
            f"Expected URL in findings (regex engine should not be suppressed "
            f"on heterogeneous column), got {entity_types}"
        )

    def test_heterogeneous_shape_detected(self, profile):
        """Verify the column is actually routed to free_text_heterogeneous."""
        column = ColumnInput(
            column_name="api_key",
            column_id="test_hetero_shape_check",
            sample_values=[
                "_STRIPE_TEST_KEY",
                "https://api.example.com/v2/users",
                "pk_test_xxxxxxxxxxxxxxxxxxxxxxxx",
                "https://cdn.example.org/assets/logo.png",
                "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef",
                "https://hooks.slack.com/services/T00/B00/xxxx",
                "The quick brown fox jumps over the lazy dog near the river",
                "Please check the documentation at https://docs.example.com/api",
            ],
        )
        findings = _classify_no_ml(column, profile, min_confidence=0.0)
        shape = detect_column_shape(column, findings)
        assert shape.shape == "free_text_heterogeneous", (
            f"Expected free_text_heterogeneous, got {shape.shape} (dict_ratio={shape.dict_word_ratio:.3f})"
        )


# ── Regression: structured_single columns keep authority suppression ─────


class TestStructuredSingleRegressions:
    """Structured-single columns must keep current behavior: authority suppression active."""

    def test_email_column_single_entity(self, profile):
        """A pure email column should produce only EMAIL, not spurious secondary types."""
        column = ColumnInput(
            column_name="email",
            column_id="test_structured_email",
            sample_values=[
                "alice@example.com",
                "bob@company.org",
                "charlie@university.edu",
                "diana@startup.io",
                "eve@government.gov",
            ],
        )
        findings = _classify_no_ml(column, profile, min_confidence=0.0)
        entity_types = {f.entity_type for f in findings}

        assert "EMAIL" in entity_types, f"Expected EMAIL in findings, got {entity_types}"

        # Verify shape is structured_single
        shape = detect_column_shape(column, findings)
        assert shape.shape == "structured_single", f"Expected structured_single, got {shape.shape}"

    def test_ssn_column_authority_suppression_preserved(self, profile):
        """SSN column: column_name engine (authority=10) should suppress lower-authority conflicts."""
        column = ColumnInput(
            column_name="ssn",
            column_id="test_structured_ssn",
            sample_values=[
                "123-45-6789",
                "987-65-4321",
                "111-22-3333",
                "444-55-6666",
                "777-88-9999",
            ],
        )
        findings = _classify_no_ml(column, profile, min_confidence=0.0)
        entity_types = {f.entity_type for f in findings}

        assert "SSN" in entity_types, f"Expected SSN in findings, got {entity_types}"

        # The top finding should be SSN (from column_name authority)
        top = max(findings, key=lambda f: f.confidence)
        assert top.entity_type == "SSN", f"Expected SSN as top finding, got {top.entity_type}"

        # Verify shape is structured_single
        shape = detect_column_shape(column, findings)
        assert shape.shape == "structured_single", f"Expected structured_single, got {shape.shape}"

    def test_phone_column_stays_single_entity(self, profile):
        """Phone column should not pick up spurious secondary types."""
        column = ColumnInput(
            column_name="phone_number",
            column_id="test_structured_phone",
            sample_values=[
                "+1-555-123-4567",
                "+1-555-987-6543",
                "+44-20-7946-0958",
                "+1-555-246-8135",
                "+1-555-369-2580",
            ],
        )
        findings = _classify_no_ml(column, profile, min_confidence=0.0)
        entity_types = {f.entity_type for f in findings}

        assert "PHONE" in entity_types, f"Expected PHONE in findings, got {entity_types}"

        # Should be structured_single
        shape = detect_column_shape(column, findings)
        assert shape.shape == "structured_single", f"Expected structured_single, got {shape.shape}"


# ── Unit test for the pre-check function ─────────────────────────────────


class TestLikelyHeterogeneousPreCheck:
    """Test the lightweight _is_likely_heterogeneous pre-check."""

    def test_heterogeneous_values_detected(self):
        from data_classifier.orchestrator.orchestrator import _is_likely_heterogeneous

        values = [
            "The quick brown fox jumps over the lazy dog",
            "https://api.example.com/v2/users",
            "_STRIPE_TEST_KEY",
            "Please check the documentation at https://docs.example.com",
        ]
        assert _is_likely_heterogeneous(values) is True

    def test_structured_values_not_detected(self):
        from data_classifier.orchestrator.orchestrator import _is_likely_heterogeneous

        values = [
            "123-45-6789",
            "987-65-4321",
            "111-22-3333",
        ]
        assert _is_likely_heterogeneous(values) is False

    def test_empty_values(self):
        from data_classifier.orchestrator.orchestrator import _is_likely_heterogeneous

        assert _is_likely_heterogeneous([]) is False
