"""Regression tests for gitleaks placeholder false-positive suppression.

Sprint 4 analysis of the gitleaks FP corpus surfaced ~37 cases where the
secret scanner fired on values that are obviously placeholders / templates
("YOUR_API_KEY_HERE", "xxxxxxxxxxxxxx", "<your-token>", ...).  This file
holds one parameterized test per case, plus positive control tests so we
know the suppression does not hide real secrets.

Item: gitleaks-fp-analysis.
"""

from __future__ import annotations

import base64

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.engines.secret_scanner import (
    SecretScannerEngine,
    _is_placeholder_value,
)

# ── Test fixture decoding ────────────────────────────────────────────────────
#
# A small number of the real gitleaks FP fixtures have static byte sequences
# that GitHub push protection mis-identifies as real secrets (e.g. Hashicorp
# Terraform Cloud tokens match the ``.atlasv1.`` signature even when all
# surrounding characters are placeholder ``x``s).  We store those fixtures
# XOR+base64 encoded at rest so the static bytes on disk cannot trigger any
# signature scanner.  At test-collection time ``_decode_xor`` restores the
# original literal byte for byte, so the secret_scanner is exercised against
# the authentic gitleaks FP shape.  This mirrors the ``xor:`` convention
# already used in ``data_classifier/patterns/__init__.py`` for credential
# pattern examples.

_XOR_KEY = 0x5A


def _decode_xor(encoded: str) -> str:
    """Decode an ``xor:``-prefixed placeholder into its literal UTF-8 form."""
    if not encoded.startswith("xor:"):
        return encoded
    raw = base64.b64decode(encoded[4:])
    return bytes(b ^ _XOR_KEY for b in raw).decode("utf-8")


# ── The 37 placeholder FP cases ──────────────────────────────────────────────
#
# Each case is a (label, sample_value) pair.  When the secret scanner runs on
# a single-sample column containing this value, it MUST produce zero findings.
#
# Cases 1-14 are real gitleaks FPs (see tests/fixtures/corpora/gitleaks_fixtures.json
# source_type below).  Cases 15+ are hand-crafted placeholder templates that
# exercise the suppression patterns on common shapes.
GITLEAKS_PLACEHOLDER_FPS: list[tuple[str, str]] = [
    # ── Real gitleaks corpus FPs ──────────────────────────────────────────
    ("gitleaks_cohere_xxx", "CO_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"),
    (
        "gitleaks_hashicorp_xxx",
        # Real Hashicorp Terraform Cloud FP shape; XOR-encoded at rest so
        # the static bytes on disk can't trip the ``.atlasv1.`` signature
        # GitHub push protection scans for.  Decoded value is byte-identical
        # to the original gitleaks fixture.
        _decode_xor(
            "xor:LjUxPzR6enp6enp6emd6eCIiIiIiIiIiIiIiIiIidDsuNjspLGt0IiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIiIng="
        ),
    ),
    ("gitleaks_grafana_ones", 'API_KEY="glc_111111111111111111111111111111111111111111="'),
    ("gitleaks_prefect_big_x", 'PREFECT_API_KEY = "pnu_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"'),
    (
        "gitleaks_readme_big_x",
        "const API_KEY = 'rdme_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX';",
    ),
    (
        "gitleaks_openshift_put_your",
        '--set kraken.kubeconfig.token.token="sha256~XXXXXXXXXX_PUT_YOUR_TOKEN_HERE_XXXXXXXXXXXX"',
    ),
    ("gitleaks_aws_example", "aws_access_key: AKIAIOSFODNN7EXAMPLE"),
    ("gitleaks_1password_a3_x", "api_key = A3-XXXXXX-XXXXXXXXXXX-XXXXX-XXXXX-XXXXX"),
    ("gitleaks_infracost_ico_x", "infracost_api_key = ico-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
    ("gitleaks_sumologic_xxx", "SUMO_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"),
    ("gitleaks_aws_key_xxx", "key = AKIAXXXXXXXXXXXXXXXX"),
    (
        "gitleaks_slack_xoxp_x",
        '"token2": "xoxp-XXXXXXXXXX-XXXXXXXXXX-XXXXXXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"',
    ),
    ("gitleaks_clickhouse_4b1d_x", "key = 4b1dXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"),
    ("gitleaks_grafana_glc_xxx", "api_key = glc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"),
    # ── Hand-crafted "YOUR_API_KEY_HERE" templates ─────────────────────────
    ("your_api_key", "api_key=YOUR_API_KEY"),
    ("your_api_key_here", "api_key=YOUR_API_KEY_HERE"),
    ("your_secret_here", "secret=YOUR_SECRET_HERE"),
    ("your_access_token", "access_token=YOUR_ACCESS_TOKEN"),
    ("your_token_mixed_case", "token=your_auth_token_here"),
    ("password_your", "password=your_password"),
    # ── Angle-bracket placeholders ─────────────────────────────────────────
    ("angle_bracket_your_key", "api_key=<your-api-key>"),
    ("angle_bracket_token", "auth_token=<TOKEN>"),
    ("angle_bracket_password", "password=<your-password>"),
    ("angle_bracket_secret", "secret=<YOUR_SECRET>"),
    # ── Template markers ───────────────────────────────────────────────────
    ("jinja_template", 'password="{{DB_PASSWORD}}"'),
    ("shell_variable_ref", 'api_key="${API_KEY}"'),
    ("mustache_template", 'secret="{{SECRET_VALUE}}"'),
    # ── Sentinel words ─────────────────────────────────────────────────────
    ("placeholder_word", "api_key=PLACEHOLDER_VALUE_123"),
    ("redacted_marker", "token=abc123REDACTEDxyz"),
    ("redacted_lower", "password=[redacted]something"),
    # ── Repetition patterns ────────────────────────────────────────────────
    ("zeros_repeat", "api_key=00000000000000000000"),
    ("ones_repeat", "token=11111111111111111111"),
    ("all_x_uppercase", "secret=XXXXXXXXXXXXXXXX"),
    ("all_x_lowercase", "secret=xxxxxxxxxxxxxxxxxxxx"),
    # ── Lazy / example placeholders ────────────────────────────────────────
    ("put_your_key_here", "api_key=PUT_YOUR_KEY_HERE"),
    ("insert_your_token", "token=INSERT_YOUR_TOKEN_HERE"),
    ("replace_me", "password=REPLACE_ME_BEFORE_DEPLOY"),
    ("changeme_template", "password=changeme_in_prod"),
]


@pytest.fixture(scope="module")
def engine() -> SecretScannerEngine:
    eng = SecretScannerEngine()
    eng.startup()
    return eng


class TestPlaceholderCount:
    """Sanity check — we ship at least 37 regression cases."""

    def test_at_least_37_cases(self) -> None:
        assert len(GITLEAKS_PLACEHOLDER_FPS) >= 37, (
            f"Expected >= 37 placeholder FP cases, got {len(GITLEAKS_PLACEHOLDER_FPS)}"
        )


@pytest.mark.parametrize(
    ("label", "value"),
    GITLEAKS_PLACEHOLDER_FPS,
    ids=[case[0] for case in GITLEAKS_PLACEHOLDER_FPS],
)
class TestPlaceholderSuppression:
    """Each placeholder must produce zero findings from the secret scanner."""

    def test_no_finding(self, engine: SecretScannerEngine, label: str, value: str) -> None:
        column = ColumnInput(
            column_name="config",
            column_id=f"fp_{label}",
            data_type="STRING",
            sample_values=[value],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert findings == [], f"placeholder '{label}' was not suppressed: {findings!r}"


# ── Positive control tests: real secrets must still be detected ─────────────


class TestPlaceholderSuppressionDoesNotHideRealSecrets:
    """Negative test for the suppression — real secrets must still fire."""

    def test_real_high_entropy_password_still_detected(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="config",
            column_id="real_pw",
            data_type="STRING",
            sample_values=['password = "kJ#9xMp$2wLq!aB7nE"'],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1
        # Sprint 8 Item 4: password → OPAQUE_SECRET subtype
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].category == "Credential"

    def test_real_api_token_still_detected(self, engine: SecretScannerEngine) -> None:
        column = ColumnInput(
            column_name="config",
            column_id="real_tok",
            data_type="STRING",
            sample_values=["api_token=8fJk3Nz2PqL9vR4cX7bD1hT6yM0wA5eS"],
        )
        findings = engine.classify_column(column, min_confidence=0.3)
        assert len(findings) == 1
        # Sprint 8 Item 4: api_token → API_KEY subtype
        assert findings[0].entity_type == "API_KEY"
        assert findings[0].category == "Credential"


# ── Unit tests for _is_placeholder_value helper ─────────────────────────────


class TestIsPlaceholderValue:
    """Direct tests for the helper predicate."""

    def test_plain_xxx_is_placeholder(self) -> None:
        assert _is_placeholder_value("xxxxxxxxxxxxxxxx") is True

    def test_upper_xxx_is_placeholder(self) -> None:
        assert _is_placeholder_value("XXXXXXXXXXXXXXXX") is True

    def test_repeated_chars_is_placeholder(self) -> None:
        assert _is_placeholder_value("11111111111111111") is True
        assert _is_placeholder_value("00000000000000000") is True

    def test_angle_bracket_is_placeholder(self) -> None:
        assert _is_placeholder_value("<your-api-key>") is True

    def test_your_api_key_is_placeholder(self) -> None:
        assert _is_placeholder_value("YOUR_API_KEY") is True

    def test_real_token_is_not_placeholder(self) -> None:
        # A high-entropy random string should not match any placeholder pattern.
        assert _is_placeholder_value("kJ9xMp2wLq7bT4eR6nY8vC") is False

    def test_empty_string_is_not_placeholder(self) -> None:
        assert _is_placeholder_value("") is False
