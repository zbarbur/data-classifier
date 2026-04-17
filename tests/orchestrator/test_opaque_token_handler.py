"""Tests for the opaque-token handler (Sprint 13 Item C)."""

from __future__ import annotations

import base64
import hashlib
import secrets

import pytest

from data_classifier.orchestrator.opaque_token_handler import (
    _shannon_entropy,
    classify_opaque_tokens,
)


class TestShannonEntropy:
    def test_empty_string(self):
        assert _shannon_entropy("") == 0.0

    def test_single_char_repeated(self):
        assert _shannon_entropy("aaaaaaa") == 0.0

    def test_two_chars_equal_frequency(self):
        # "abababab" → 2 chars, equal freq → 1.0 bit/char
        assert _shannon_entropy("abababab") == pytest.approx(1.0)

    def test_high_entropy_base64(self):
        val = base64.b64encode(secrets.token_bytes(32)).decode()
        assert _shannon_entropy(val) > 4.0

    def test_hex_hash(self):
        val = hashlib.sha256(b"test").hexdigest()
        # hex has 16 chars → max ~4.0 bits/char
        assert _shannon_entropy(val) >= 3.5


class TestClassifyOpaqueTokens:
    def test_jwt_tokens_emit_opaque_secret(self):
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        findings = classify_opaque_tokens("col_jwt", [jwt] * 20)
        assert len(findings) == 1
        assert findings[0].entity_type == "OPAQUE_SECRET"
        assert findings[0].engine == "entropy"
        assert findings[0].confidence >= 0.6

    def test_base64_payloads_emit_opaque_secret(self):
        values = [
            base64.b64encode(f'{{"user":"u{i}","role":"admin","ts":{1700000000 + i}}}'.encode()).decode()
            for i in range(20)
        ]
        findings = classify_opaque_tokens("col_b64", values)
        assert len(findings) == 1
        assert findings[0].entity_type == "OPAQUE_SECRET"

    def test_hex_hashes_emit_opaque_secret(self):
        values = [hashlib.sha256(f"val_{i}".encode()).hexdigest() for i in range(20)]
        findings = classify_opaque_tokens("col_hash", values)
        assert len(findings) == 1
        assert findings[0].entity_type == "OPAQUE_SECRET"

    def test_session_ids_emit_opaque_secret(self):
        values = [secrets.token_urlsafe(32) for _ in range(20)]
        findings = classify_opaque_tokens("col_sess", values)
        assert len(findings) == 1
        assert findings[0].entity_type == "OPAQUE_SECRET"

    def test_short_values_do_not_fire(self):
        """Short strings (< 20 chars mean) should not trigger."""
        values = [f"abc{i:04d}" for i in range(20)]  # ~8 chars each
        findings = classify_opaque_tokens("col_short", values)
        assert findings == []

    def test_english_prose_does_not_fire(self):
        """Natural language has entropy ~3.5-4.0, should not trigger."""
        values = [
            "The quick brown fox jumps over the lazy dog",
            "Customer support ticket regarding billing issue",
            "Please contact us at the address provided below",
        ] * 7
        findings = classify_opaque_tokens("col_text", values)
        assert findings == []

    def test_empty_values(self):
        assert classify_opaque_tokens("col_empty", []) == []
        assert classify_opaque_tokens("col_blank", ["", "", ""]) == []

    def test_mixed_opaque_and_normal(self):
        """If less than 50% of values are high-entropy, don't fire."""
        opaque = [secrets.token_urlsafe(32) for _ in range(5)]
        normal = [f"normal_value_{i}" for i in range(15)]
        findings = classify_opaque_tokens("col_mixed", opaque + normal)
        assert findings == []

    def test_confidence_capped_at_095(self):
        """Even perfect entropy columns cap at 0.95."""
        values = [secrets.token_urlsafe(64) for _ in range(30)]
        findings = classify_opaque_tokens("col_perfect", values)
        assert len(findings) == 1
        assert findings[0].confidence <= 0.95

    def test_evidence_contains_entropy_info(self):
        values = [secrets.token_urlsafe(32) for _ in range(20)]
        findings = classify_opaque_tokens("col", values)
        assert "mean_entropy" in findings[0].evidence
        assert "bits/char" in findings[0].evidence
