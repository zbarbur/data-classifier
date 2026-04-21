"""Unit tests for the M4f-d1 opaque-column decoder stage."""

from __future__ import annotations

import base64

import pytest

from tests.benchmarks.meta_classifier.llm_labeler_router import try_decode_opaque_column


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


class TestTryDecodeOpaqueColumn:
    def test_base64_json_payloads_decode_and_reroute(self):
        """The canonical Phase 3a case: JWT-style JSON payloads."""
        values = [
            _b64('{"user":"alice@example.com","role":"admin"}'),
            _b64('{"user":"bob@example.org","role":"user"}'),
            _b64('{"user":"carol@site.co","role":"guest"}'),
        ]
        result = try_decode_opaque_column(values)
        assert result is not None, "base64 JSON must decode"
        decoded, new_shape = result
        assert new_shape == "free_text_heterogeneous"
        assert len(decoded) == 3
        assert decoded[0] == '{"user":"alice@example.com","role":"admin"}'
        assert "bob@example.org" in decoded[1]

    def test_eth_hex_does_not_decode(self):
        """Shape-specific opaque (ETH addresses) must fall through."""
        values = [
            "0xc400b9d93a23b0be5d41ab337ad605988aef8463",
            "0x3df7390ea4f9d7ca5a7f30ab52d18fd4f247bf44",
            "0x1440ec793ae50fa046b95bfeca5af475b6003f9e",
        ]
        result = try_decode_opaque_column(values)
        assert result is None, "hex-prefixed addresses must not trigger base64 decode"

    def test_btc_hash_does_not_decode(self):
        """64-char hex hashes (BTC tx hashes) must fall through."""
        values = [
            "0" * 64,  # synthetic but shape-valid
            "a" * 64,
            "1" * 64,
        ]
        result = try_decode_opaque_column(values)
        assert result is None

    def test_random_high_entropy_tokens_do_not_decode(self):
        """Session-token-like strings where the bytes don't form readable text."""
        values = [_b64("".join(chr((i + j) % 256) for j in range(32))) for i in range(10)]
        # These are base64 of binary noise → decoded bytes include control chars
        # and should fall below the printable-rate threshold.
        result = try_decode_opaque_column(values)
        assert result is None, "noisy byte payloads must not misroute as text"

    def test_mixed_column_below_threshold(self):
        """If < min_success_rate decode cleanly, whole column stays opaque."""
        values = [
            _b64('{"k":"v"}'),  # decodes
            "0xabcdef" + "0" * 34,  # doesn't (hex, fails validate=True)
            "0xfedcba" + "1" * 34,  # doesn't
            "0x012345" + "2" * 34,  # doesn't
            "0x678901" + "3" * 34,  # doesn't
        ]
        # 1/5 = 20% success rate, well below default 80%
        result = try_decode_opaque_column(values)
        assert result is None

    def test_all_decode_clean_text(self):
        """Base64-wrapped plain text (e.g., log messages) decodes."""
        values = [
            _b64("2026-04-21T10:00:00 INFO user login succeeded"),
            _b64("2026-04-21T10:00:01 WARN rate limit hit"),
            _b64("2026-04-21T10:00:02 ERROR database timeout"),
        ]
        result = try_decode_opaque_column(values)
        assert result is not None
        decoded, new_shape = result
        assert new_shape == "free_text_heterogeneous"
        assert "INFO user login" in decoded[0]

    def test_missing_padding_is_tolerated(self):
        """Some base64 producers strip trailing '=' — the decoder pads before decoding."""
        # Strip any trailing = to simulate unpadded output
        values = [_b64('{"email":"x@y.z"}').rstrip("=") for _ in range(5)]
        result = try_decode_opaque_column(values)
        assert result is not None
        decoded, _ = result
        assert "x@y.z" in decoded[0]

    def test_empty_column_returns_none(self):
        """Defensive: an empty values list is a degenerate case, not a decoder fire."""
        assert try_decode_opaque_column([]) is None

    def test_preserves_column_length_on_partial_failures(self):
        """Values that individually fail decode pass through in the returned list
        so downstream length/position assumptions are preserved."""
        values = [
            _b64('{"a":1}'),  # ok
            _b64('{"b":2}'),  # ok
            _b64('{"c":3}'),  # ok
            _b64('{"d":4}'),  # ok
            "0xbadhex" + "0" * 34,  # fails — but column still fires (4/5 = 80%)
        ]
        result = try_decode_opaque_column(values)
        assert result is not None, "80% success hits the threshold exactly"
        decoded, _ = result
        assert len(decoded) == 5
        assert decoded[4].startswith("0x"), "failing value passes through unchanged"

    def test_threshold_is_configurable(self):
        """Tighten min_success_rate to force otherwise-decodable columns to fail."""
        values = [_b64('{"a":1}'), "not_base64_at_all", "also_not"]
        # default 80% → fails (1/3)
        assert try_decode_opaque_column(values) is None
        # 30% → passes
        result = try_decode_opaque_column(values, min_success_rate=0.3)
        assert result is not None


@pytest.mark.integration
@pytest.mark.skipif(
    not __import__("os").environ.get("ANTHROPIC_API_KEY"),
    reason="live Anthropic API call — set ANTHROPIC_API_KEY to enable",
)
class TestDecoderIntegratedWithLabeler:
    """End-to-end: opaque-token row with decodable base64 content goes through
    the decoder and returns predictions from the heterogeneous branch.

    Marked integration so CI doesn't rely on live API calls. Run locally
    with ``pytest -m integration tests/benchmarks/meta_classifier/test_opaque_decoder.py``.
    """

    def test_base64_email_payloads_predict_email(self):
        import anthropic

        from tests.benchmarks.meta_classifier.llm_labeler import label_column
        from tests.benchmarks.meta_classifier.llm_labeler_router import (
            build_system_prompt_for_shape,
            try_decode_opaque_column,
        )

        values = [_b64(f'{{"user":"user{i}@example.com","role":"admin"}}') for i in range(20)]
        decoder_result = try_decode_opaque_column(values)
        assert decoder_result is not None
        decoded, new_shape = decoder_result
        assert new_shape == "free_text_heterogeneous"

        row = {
            "column_id": "test_base64_emails",
            "values": decoded,
            "encoding": "plaintext",
            "source": "unit_test",
            "source_reference": "synthetic",
            "true_labels": ["EMAIL"],
            "true_shape": new_shape,
        }
        client = anthropic.Anthropic()
        system = build_system_prompt_for_shape(new_shape)
        call = label_column(client, row, system)
        assert call.error is None, f"API error: {call.error}"
        assert "EMAIL" in call.pred, f"expected EMAIL in pred, got {call.pred}"
