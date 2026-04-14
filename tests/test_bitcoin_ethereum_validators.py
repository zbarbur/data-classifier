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

import pytest

from data_classifier.engines.validators import (
    bitcoin_address_check,
    ethereum_address_check,
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
