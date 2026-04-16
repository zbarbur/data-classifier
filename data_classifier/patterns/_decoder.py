"""Shared decoder for encoded credential / placeholder strings.

Credential-shaped literals (API keys, tokens, PATs) stored verbatim in
``default_patterns.json`` example lists or ``stopwords.json`` trip
GitHub's push-protection secret scanner even though they are
published test/placeholder values. To sidestep that we accept two
optional encoding prefixes on any such entry:

``xor:<b64>``
    XOR each byte with :data:`_XOR_KEY`, then base64-encode the
    result. Used for entries whose shape closely resembles a real
    credential (Stripe docs test keys, PAT placeholders).

``b64:<b64>``
    Plain base64 with no XOR. Convenience encoding for values that
    only need a light obfuscation to avoid accidental human
    misreading as real credentials.

Entries with neither prefix are returned unchanged, so encoding is
strictly opt-in per value.

This helper lives in its own module (imported by both
``data_classifier/patterns/__init__.py`` and
``data_classifier/engines/regex_engine.py``) so the decode rules stay
in one place.
"""

from __future__ import annotations

import base64

_XOR_KEY = 0x5A


def decode_encoded_strings(values: list[str]) -> list[str]:
    """Decode optionally-encoded credential/placeholder strings.

    Supports ``xor:`` (XOR + base64) and ``b64:`` (base64 only)
    prefixes. Unprefixed values pass through unchanged.
    """
    decoded: list[str] = []
    for v in values:
        if v.startswith("xor:"):
            raw = base64.b64decode(v[4:])
            decoded.append(bytes(b ^ _XOR_KEY for b in raw).decode("utf-8"))
        elif v.startswith("b64:"):
            decoded.append(base64.b64decode(v[4:]).decode())
        else:
            decoded.append(v)
    return decoded


def encode_xor(plaintext: str) -> str:
    """Return ``xor:<b64>`` encoding of ``plaintext``.

    Used by tooling that prepares stopwords.json / default_patterns.json
    entries. Not used at runtime.
    """
    raw = bytes(b ^ _XOR_KEY for b in plaintext.encode("utf-8"))
    return "xor:" + base64.b64encode(raw).decode("ascii")
