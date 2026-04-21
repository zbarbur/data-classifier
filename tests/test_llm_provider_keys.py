"""Tests for OpenAI legacy + Anthropic API key patterns (Sprint 13 S0-2)."""

from __future__ import annotations

import secrets
import string

from data_classifier import classify_columns, load_profile
from data_classifier.core.types import ColumnInput


def _random_base62(n: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


PROFILE = load_profile("standard")


class TestOpenAILegacyKey:
    """openai_legacy_key: sk-<48 chars base62>"""

    def test_real_shape_matches(self):
        key = f"sk-{_random_base62(48)}"
        column = ColumnInput(column_id="t", column_name="api_key", sample_values=[key] * 10)
        findings = classify_columns([column], PROFILE)
        api_key_findings = [f for f in findings if f.entity_type == "API_KEY"]
        assert len(api_key_findings) >= 1, f"Expected API_KEY finding for {key[:15]}..."

    def test_too_short_no_match(self):
        """sk- followed by only 20 chars should not match the 48-char pattern."""
        key = f"sk-{_random_base62(20)}"
        column = ColumnInput(column_id="t", column_name="data", sample_values=[key] * 10)
        findings = classify_columns([column], PROFILE)
        api_key_findings = [f for f in findings if f.entity_type == "API_KEY"]
        # May or may not match other patterns, but openai_legacy specifically requires 48
        assert all("legacy" not in (f.evidence or "") for f in api_key_findings)

    def test_bare_prefix_no_match(self):
        """sk- alone should not match."""
        column = ColumnInput(column_id="t", column_name="data", sample_values=["sk-"] * 10)
        findings = classify_columns([column], PROFILE)
        assert not any(f.entity_type == "API_KEY" for f in findings)

    def test_embedded_in_json(self):
        key = f"sk-{_random_base62(48)}"
        value = f'{{"openai_key": "{key}"}}'
        column = ColumnInput(column_id="t", column_name="config", sample_values=[value] * 10)
        findings = classify_columns([column], PROFILE)
        api_key_findings = [f for f in findings if f.entity_type == "API_KEY"]
        assert len(api_key_findings) >= 1


class TestAnthropicKey:
    """anthropic_api_key: sk-ant-(api|admin)NN-<93+ chars>"""

    def test_real_shape_matches(self):
        key = f"sk-ant-api03-{_random_base62(95)}"
        column = ColumnInput(column_id="t", column_name="api_key", sample_values=[key] * 10)
        findings = classify_columns([column], PROFILE)
        api_key_findings = [f for f in findings if f.entity_type == "API_KEY"]
        assert len(api_key_findings) >= 1, f"Expected API_KEY finding for {key[:25]}..."

    def test_admin_variant_matches(self):
        key = f"sk-ant-admin01-{_random_base62(95)}"
        column = ColumnInput(column_id="t", column_name="api_key", sample_values=[key] * 10)
        findings = classify_columns([column], PROFILE)
        api_key_findings = [f for f in findings if f.entity_type == "API_KEY"]
        assert len(api_key_findings) >= 1

    def test_too_short_suffix_no_match(self):
        """sk-ant-api03- with only 20 chars should not match (requires 93+)."""
        key = f"sk-ant-api03-{_random_base62(20)}"
        column = ColumnInput(column_id="t", column_name="data", sample_values=[key] * 10)
        findings = classify_columns([column], PROFILE)
        # Should not fire as anthropic pattern
        api_key_findings = [f for f in findings if f.entity_type == "API_KEY"]
        assert all("anthropic" not in (f.evidence or "").lower() for f in api_key_findings)

    def test_bare_prefix_no_match(self):
        column = ColumnInput(column_id="t", column_name="data", sample_values=["sk-ant-api03-"] * 10)
        findings = classify_columns([column], PROFILE)
        assert not any(f.entity_type == "API_KEY" for f in findings)

    def test_with_checksum_suffix(self):
        """Anthropic keys optionally end with -XX (2-char checksum)."""
        key = f"sk-ant-api03-{_random_base62(93)}-Ab"
        column = ColumnInput(column_id="t", column_name="api_key", sample_values=[key] * 10)
        findings = classify_columns([column], PROFILE)
        api_key_findings = [f for f in findings if f.entity_type == "API_KEY"]
        assert len(api_key_findings) >= 1
