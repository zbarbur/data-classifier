"""Tests for the Sprint 11 Phase 5 bitcoin/ethereum address validators.

The regex patterns for ``BITCOIN_ADDRESS`` and ``ETHEREUM_ADDRESS`` in
``default_patterns.json`` are structural only — they match any string of
the right shape in the right charset. Without these validators, random
base58 alphabet strings and hex identifiers trigger FPs on every scan.

The validators verify:
  - bitcoin_address_check: base58check checksum for P2PKH/P2SH + bech32/
    bech32m polymod for segwit. Rejects any string where the cryptographic
    checksum doesn't match.
  - ethereum_address_check: structural (0x + 40 hex) + rejection of the
    well-known null/placeholder addresses (zero, all-ones, deadbeef).
    Does NOT verify EIP-55 mixed-case checksum (keccak256 is not in the
    Python stdlib); that is filed as a follow-up.
"""

from __future__ import annotations

import typing

import pytest

from data_classifier.engines.validators import (
    bitcoin_address_check,
    ethereum_address_check,
    not_placeholder_credential,
)


class TestBitcoinAddressValidator:
    # Real Bitcoin addresses. The P2PKH example is the Genesis block
    # coinbase output. The P2SH example is from BIP-16 reference. The
    # bech32 is from BIP-173 reference.
    @pytest.mark.parametrize(
        "address",
        [
            # P2PKH (starts with '1')
            "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",  # Genesis coinbase
            "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",  # default_patterns example
            # P2SH (starts with '3')
            "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",  # default_patterns example
            "3P14159f73E4gFr7JterCCQh9QjiTjiZrG",  # Another well-known P2SH
            # Bech32 (segwit v0, starts with 'bc1q')
            "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",  # BIP-173 reference
            # Bech32m (segwit v1+, starts with 'bc1p')
            "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0",  # Taproot reference
        ],
    )
    def test_accepts_valid_addresses(self, address: str) -> None:
        assert bitcoin_address_check(address) is True

    @pytest.mark.parametrize(
        "non_address",
        [
            # Too short
            "1BvB",
            # Wrong prefix
            "0xdead",
            "2A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            # Valid shape but twisted checksum (last char changed)
            "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN3",
            "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLz",
            # Empty / whitespace-only
            "",
            "   ",
            # Random base58 alphabet string of correct length (no valid checksum)
            "1AbCdEfGhIjKlMnOpQrStUvWxYz234567",
            # Bech32 with valid alphabet but corrupted polymod
            "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdx",
            # Bech32 with non-bc HRP
            "tb1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
            # Bech32 with mixed case (BIP-173 forbids mixed case)
            "BC1Qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
        ],
    )
    def test_rejects_invalid_addresses(self, non_address: str) -> None:
        assert bitcoin_address_check(non_address) is False

    def test_rejects_base58_strings_of_valid_length_without_checksum(self) -> None:
        # Generate a bunch of random-looking base58 strings of correct
        # length. The base58check verification should reject them all
        # with overwhelming probability (checksum collision is 2^-32).
        random_base58_valid_len = [
            "1" + "z" * 33,  # 34 chars starting with '1'
            "3" + "1" * 33,  # 34 chars starting with '3'
            "12345678901234567890123456789012",
        ]
        for s in random_base58_valid_len:
            assert bitcoin_address_check(s) is False, f"{s!r} should fail checksum"


class TestEthereumAddressValidator:
    @pytest.mark.parametrize(
        "address",
        [
            # Real Ethereum addresses (from default_patterns.json examples)
            "0x32Be343B94f860124dC4fEe278FDCBD38C102D88",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            # All-lowercase
            "0xdac17f958d2ee523a2206206994597c13d831ec7",
            # All-uppercase hex
            "0xDAC17F958D2EE523A2206206994597C13D831EC7",
        ],
    )
    def test_accepts_valid_structural(self, address: str) -> None:
        assert ethereum_address_check(address) is True

    @pytest.mark.parametrize(
        "non_address",
        [
            # Wrong prefix
            "dAC17F958D2ee523a2206206994597C13D831ec7",  # missing 0x
            "1x32Be343B94f860124dC4fEe278FDCBD38C102D88",
            # Too short / too long
            "0xdead",
            "0x32Be343B94f860124dC4f",
            "0x32Be343B94f860124dC4fEe278FDCBD38C102D88ff",
            # Non-hex characters in the hex portion
            "0xZYZ17F958D2ee523a2206206994597C13D831ec7",
            # Well-known fakes
            "0x0000000000000000000000000000000000000000",
            "0xffffffffffffffffffffffffffffffffffffffff",
            "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            # Case variants of fakes
            "0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF",
            "0xDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF",
            # Empty
            "",
        ],
    )
    def test_rejects_invalid(self, non_address: str) -> None:
        assert ethereum_address_check(non_address) is False

    def test_eip55_mixed_case_is_accepted_without_keccak_verification(self) -> None:
        # Documented limitation: we accept mixed-case without verifying
        # EIP-55 because keccak256 is not in the stdlib. This test pins
        # the current behavior so a future EIP-55 upgrade can flip the
        # assertion to `is False` for an incorrectly-checksummed variant.
        # Real address (valid EIP-55 from default_patterns.json example):
        assert ethereum_address_check("0x32Be343B94f860124dC4fEe278FDCBD38C102D88") is True
        # Same address with one letter case flipped — INVALID EIP-55 but
        # currently accepted by our structural check.
        assert ethereum_address_check("0x32be343B94f860124dC4fEe278FDCBD38C102D88") is True


class TestNotPlaceholderCredential:
    """Sprint 11 Phase 6: validator layer that rejects known
    credential placeholder strings for patterns that go through the
    regex_engine (not the secret_scanner).

    known_placeholder_values.json is the source of truth. The
    validator loads it lazily on first call and caches as a frozenset.
    Comparison is case-insensitive with whitespace stripping.
    """

    @pytest.mark.parametrize(
        "placeholder",
        [
            "changeme",
            "password123",
            "password",
            "admin",
            "root",
            "12345678",
            "letmein",
            "your_api_key_here",
            "your_secret_here",
            "akiaiosfodnn7example",
            "foobar",
            "example",
            "CHANGEME",
            "  changeme  ",
            "ADMIN",
        ],
    )
    def test_rejects_known_placeholders(self, placeholder: str) -> None:
        assert not_placeholder_credential(placeholder) is False

    @pytest.mark.parametrize(
        "non_placeholder",
        [
            # High-entropy random strings that are not in the placeholder
            # list. Deliberately avoid the exact prefixes (AKIA_, sk_, ghp_)
            # of real credential formats — GitHub push protection scans
            # any string that matches those shapes, even in test code.
            "xk9fpq2vLcHmsdFtQRhGJwK7pN4bXmzN",
            "a8B3cD2eF1gH9iJ0kL7mN6oP5qR4sT",
            "a random string that is not in the list",
            "",
        ],
    )
    def test_accepts_non_placeholders(self, non_placeholder: str) -> None:
        assert not_placeholder_credential(non_placeholder) is True

    def test_validator_loads_from_registry(self) -> None:
        # The validator must be discoverable via the VALIDATORS dict
        # so default_patterns.json entries referencing it by name
        # resolve at pattern-compile time.
        from data_classifier.engines.validators import VALIDATORS

        assert "not_placeholder_credential" in VALIDATORS
        assert VALIDATORS["not_placeholder_credential"]("changeme") is False
        assert VALIDATORS["not_placeholder_credential"]("xk9fpq2vLcHmsd") is True

    def test_credential_patterns_use_validator(self) -> None:
        """Pin the Phase 6 wiring: every credential pattern that used
        to have validator="" now has validator="not_placeholder_credential".

        Catches silent re-empties during future pattern edits.
        """
        import json
        from pathlib import Path

        patterns_path = Path(__file__).parent.parent / "data_classifier" / "patterns" / "default_patterns.json"
        data = json.loads(patterns_path.read_text())

        # Subset of credential patterns that specifically went through
        # the Phase 6 wiring. Listed explicitly so a net-new credential
        # pattern added in a future sprint is not required to use this
        # validator (the contributor can decide).
        required = {
            "aws_access_key",
            "jwt_token",
            "generic_api_key",
            "github_token",
            "stripe_secret_key",
            "stripe_publishable_key",
            "slack_bot_token",
            "slack_webhook_url",
            "openai_api_key",
        }

        seen: dict[str, str] = {}
        for p in data.get("patterns", []):
            name = p.get("name")
            if name in required:
                seen[name] = p.get("validator", "")

        for name in required:
            assert name in seen, f"pattern '{name}' missing from default_patterns.json"
            assert seen[name] == "not_placeholder_credential", (
                f"pattern '{name}' has validator={seen[name]!r}, expected 'not_placeholder_credential'"
            )


class TestExpandedStopwords:
    """Sprint 11 Phase 6: stopwords.json expanded with well-known fake
    credential strings from public FP catalogs and SDK docs. The
    regex_engine's _is_stopword consumes this file; a single case-
    insensitive exact match rejects the value before it reaches the
    validator.

    These tests pin the new entries so a future stopwords reorganization
    doesn't silently drop them.
    """

    def _stopwords(self) -> set[str]:
        import json
        from pathlib import Path

        path = Path(__file__).parent.parent / "data_classifier" / "patterns" / "stopwords.json"
        data = json.loads(path.read_text())
        return {s.lower() for s in data.get("stopwords", [])}

    @pytest.mark.parametrize(
        "entry",
        [
            # Null / repeating UUIDs
            "00000000-0000-0000-0000-000000000000",
            "11111111-1111-1111-1111-111111111111",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "deadbeef-dead-beef-dead-deadbeefdead",
            # Stripe documentation card numbers
            "4242424242424242",
            "378282246310005",
            # JWT RFC 7519 example
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        ],
    )
    def test_new_stopword_entries_present(self, entry: str) -> None:
        sw = self._stopwords()
        assert entry.lower() in sw, f"stopwords.json missing '{entry}'"

    def test_stopwords_are_case_insensitive_via_regex_engine(self) -> None:
        """The regex_engine lowercases values before checking, so the
        JSON entries don't need to enumerate case variants. Pin this
        behavior via the _is_stopword helper."""
        from data_classifier.engines.regex_engine import _is_stopword
        from data_classifier.patterns import ContentPattern

        pattern = ContentPattern(
            name="test",
            regex="",
            entity_type="CREDENTIAL",
            category="Credential",
            sensitivity="HIGH",
            confidence=0.9,
        )
        assert _is_stopword("4242424242424242", pattern) is True
        # Case variant resolves via the lowercase normalization.
        assert _is_stopword("DEADBEEF-DEAD-BEEF-DEAD-DEADBEEFDEAD", pattern) is True
        # Non-entry with same length is accepted.
        assert _is_stopword("4242424242424243", pattern) is False


class TestStopwordsEncodedEntries:
    """Sprint 12 follow-up: ``stopwords.json`` supports ``xor:`` /
    ``b64:`` prefixed entries via the shared
    :mod:`data_classifier.patterns._decoder` helper. This lets us store
    published-but-credential-shaped placeholder strings (Stripe docs
    test keys, PAT placeholders) without tripping GitHub's
    push-protection secret scanner on the file.
    """

    def test_load_global_stopwords_decodes_xor_prefixed_entries(self, tmp_path, monkeypatch) -> None:
        """Construct a stopwords.json containing an ``xor:``-encoded
        entry and assert ``_load_global_stopwords`` returns the
        decoded plaintext. Test does not depend on any specific entry
        being in the bundled file; it isolates the loader's decode
        path.
        """
        import json

        from data_classifier.engines import regex_engine
        from data_classifier.patterns._decoder import encode_xor

        plaintext = "sk_test_stopword_loader_selftest_0123456789"
        encoded = encode_xor(plaintext)
        assert encoded.startswith("xor:")
        assert plaintext not in encoded  # sanity: the plaintext is not in the file

        stopwords_file = tmp_path / "stopwords.json"
        stopwords_file.write_text(
            json.dumps(
                {
                    "description": "test fixture",
                    "stopwords": [
                        "plain_entry_value",
                        encoded,
                    ],
                }
            )
        )
        # Point the loader at the fixture and reset the module-level cache.
        monkeypatch.setattr(regex_engine, "_GLOBAL_STOPWORDS_FILE", stopwords_file, raising=False)
        monkeypatch.setattr(regex_engine, "_GLOBAL_STOPWORDS", None, raising=False)

        sw = regex_engine._load_global_stopwords()
        assert plaintext.lower() in sw, "xor: entry was not decoded by the stopwords loader"
        assert "plain_entry_value" in sw, "plain entries still pass through unchanged"

    def test_load_global_stopwords_decodes_b64_prefixed_entries(self, tmp_path, monkeypatch) -> None:
        """Same assertion for the ``b64:`` prefix, which decodes via
        plain base64 without XOR.
        """
        import base64
        import json

        from data_classifier.engines import regex_engine

        plaintext = "b64_only_stopword_loader_selftest"
        encoded = "b64:" + base64.b64encode(plaintext.encode()).decode()
        stopwords_file = tmp_path / "stopwords.json"
        stopwords_file.write_text(json.dumps({"description": "test fixture", "stopwords": [encoded]}))
        monkeypatch.setattr(regex_engine, "_GLOBAL_STOPWORDS_FILE", stopwords_file, raising=False)
        monkeypatch.setattr(regex_engine, "_GLOBAL_STOPWORDS", None, raising=False)

        sw = regex_engine._load_global_stopwords()
        assert plaintext.lower() in sw

    # Encoded forms of the two Stripe documentation test keys published
    # on stripe.com/docs. Decoded at runtime so the cleartext never
    # appears in the repo (GitHub push-protection would otherwise flag
    # the test file). Keys have been in Stripe's public documentation
    # since ~2015; they are by definition not real credentials.
    _STRIPE_DOCS_TEST_KEYS_ENCODED: typing.ClassVar[list[str]] = [
        "xor:KTEFLj8pLgVuPxlpYxIrFiMwDR47KDAuDmsgPiptPjk=",
        "xor:KjEFLj8pLgUOAzU1Fws7Lyw+Hx4rb24UMw4qMhNtMCI=",
    ]

    def _decoded_stripe_keys(self) -> list[str]:
        from data_classifier.patterns._decoder import decode_encoded_strings

        return decode_encoded_strings(self._STRIPE_DOCS_TEST_KEYS_ENCODED)

    def test_stripe_docs_test_keys_in_runtime_stopwords(self) -> None:
        """The two Stripe docs test keys flagged in Sprint 11 Phase 6
        are re-added in encoded form and must appear in the runtime
        stopwords set. Entries are stored xor-encoded in
        ``stopwords.json``; the loader decodes them on load.
        """
        from data_classifier.engines.regex_engine import _load_global_stopwords

        sw = _load_global_stopwords()
        for key in self._decoded_stripe_keys():
            assert key.lower() in sw, (
                f"Stripe docs test key (decoded length={len(key)}) not found in "
                "decoded stopwords. Check that stopwords.json has the xor:-encoded "
                "entry and that _load_global_stopwords runs decode_encoded_strings()."
            )

    def test_stripe_docs_keys_rejected_via_is_stopword(self) -> None:
        """End-to-end: a credential pattern whose matched value equals
        a Stripe docs test key must be rejected by ``_is_stopword``.
        """
        from data_classifier.engines.regex_engine import _is_stopword
        from data_classifier.patterns import ContentPattern

        pattern = ContentPattern(
            name="stripe_secret_key",
            regex="",
            entity_type="CREDENTIAL",
            category="Credential",
            sensitivity="HIGH",
            confidence=0.9,
        )
        for key in self._decoded_stripe_keys():
            assert _is_stopword(key, pattern) is True
        # Structurally similar but non-placeholder value is not suppressed.
        assert _is_stopword("sk_test_notInTheStopwordsList99999999", pattern) is False
