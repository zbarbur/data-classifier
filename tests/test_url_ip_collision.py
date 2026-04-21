"""Tests for URL/IP_ADDRESS collision suppression.

When an IP address appears inside a URL, only the URL finding is kept.
Standalone IPs are unaffected. Targets Sprint 5 Nemotron col_12 FP where
values like ``http://198.51.100.17/api`` were classified as both URL
(correct) and IP_ADDRESS (false positive).
"""

from __future__ import annotations

import pytest

from data_classifier import ColumnInput, load_profile
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.orchestrator.orchestrator import Orchestrator


def _classify_no_ml(columns, profile, **kwargs):
    """Classify without GLiNER — tests cascade collision behavior only."""
    engines = [ColumnNameEngine(), RegexEngine(), HeuristicEngine(), SecretScannerEngine()]
    orch = Orchestrator(engines=engines, mode="structured")
    results = []
    for col in columns:
        results.extend(orch.classify_column(col, profile, **kwargs))
    return results


@pytest.fixture
def profile():
    return load_profile("standard")


class TestUrlIpCollisionSuppression:
    def test_ip_inside_http_url_suppressed(self, profile) -> None:
        """All matched samples are URL-embedded IPs — IP_ADDRESS must be
        suppressed. The bundled URL regex requires a letter-only TLD and
        therefore does NOT fire on IP-based URLs, so the orchestrator
        suppression relies on inspecting the IP finding's sample_matches
        rather than on a URL co-finding."""
        col = ColumnInput(
            column_id="c1",
            column_name="endpoint",
            sample_values=[
                "http://192.168.1.1/api",
                "https://10.0.0.5:8080/health",
                "http://203.0.113.42/status",
            ],
        )
        findings = _classify_no_ml([col], profile)
        types = {f.entity_type for f in findings}
        assert "IP_ADDRESS" not in types

    def test_standalone_ip_still_detected(self, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="server_ip",
            sample_values=["192.168.1.1", "10.0.0.5", "203.0.113.42"],
        )
        findings = _classify_no_ml([col], profile)
        types = {f.entity_type for f in findings}
        assert "IP_ADDRESS" in types
        assert "URL" not in types

    def test_mixed_ip_and_url_column_keeps_both(self, profile) -> None:
        """A column where some samples are standalone IPs and others are URLs
        keeps both entity types — they are genuine concurrent observations."""
        col = ColumnInput(
            column_id="c1",
            column_name="addresses",
            sample_values=[
                "192.168.1.1",  # standalone
                "http://example.com",  # URL with no IP
                "10.0.0.5",  # standalone
            ],
        )
        findings = _classify_no_ml([col], profile)
        types = {f.entity_type for f in findings}
        assert "IP_ADDRESS" in types
        assert "URL" in types

    def test_url_with_ip_port_suppresses_ip(self, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="endpoint",
            sample_values=["http://192.168.1.1:8080/status"],
        )
        findings = _classify_no_ml([col], profile)
        types = {f.entity_type for f in findings}
        assert "IP_ADDRESS" not in types

    def test_https_url_with_bare_ip_suppresses_ip(self, profile) -> None:
        """``https://198.51.100.17`` — every matched sample starts with an
        ``https://`` scheme, so the IP_ADDRESS finding is suppressed even
        though the URL regex does not fire on IP-based hosts."""
        col = ColumnInput(
            column_id="c1",
            column_name="ref",
            sample_values=["https://198.51.100.17"],
        )
        findings = _classify_no_ml([col], profile)
        types = {f.entity_type for f in findings}
        assert "IP_ADDRESS" not in types
