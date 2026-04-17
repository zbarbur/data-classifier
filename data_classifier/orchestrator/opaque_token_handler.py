"""Opaque-token handler (Sprint 13 Item C).

Classifies columns of high-entropy alphanumeric tokens — JWTs, base64
payloads, hex hashes, session IDs, API tokens — that the cascade's
regex and secret_scanner don't match because they lack key-value structure.

The handler computes Shannon entropy of the character distribution per
sample value. Columns where the mean entropy exceeds the threshold
(~4.0 bits/char) and mean length exceeds 20 characters emit
OPAQUE_SECRET. This is deliberately conservative: short strings and
low-entropy values (e.g., UUIDs with mostly hex chars) fall through
to the cascade.

No ML dependency — pure stats on character distributions.
"""

from __future__ import annotations

import math
from collections import Counter

from data_classifier.core.types import ClassificationFinding, SampleAnalysis

# Shannon entropy threshold for the "high-entropy" path.
# base64/JWT/session tokens: 4.5-5.5, English prose: 3.9-4.4.
# 4.2 separates cleanly with the space-ratio guard below.
_ENTROPY_THRESHOLD: float = 4.2

# Minimum mean character length to consider a column "opaque token".
_MIN_MEAN_LENGTH: float = 20.0

# Minimum fraction of sample values that must exceed the entropy
# threshold (or the hex-hash path) for the column to emit.
_MIN_COVERAGE: float = 0.5

# Space ratio above which a value is considered prose, not a token.
# English prose has 15-20% spaces; tokens have near 0%.
_MAX_SPACE_RATIO: float = 0.05

# Hex-hash path: values with only hex chars [0-9a-fA-F] and length
# >= 32 are likely hashes even though their entropy (~3.8) is below
# the main threshold.
_HEX_MIN_LENGTH: int = 32
_HEX_CHARS: frozenset[str] = frozenset("0123456789abcdefABCDEF")


def _shannon_entropy(s: str) -> float:
    """Compute Shannon entropy in bits/char for a string."""
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _is_hex_hash(s: str) -> bool:
    """True if the string looks like a hex-encoded hash (32+ hex chars)."""
    return len(s) >= _HEX_MIN_LENGTH and all(c in _HEX_CHARS for c in s)


def _is_opaque_value(s: str) -> bool:
    """True if a single value looks like an opaque token (not prose)."""
    if not s or len(s) < _MIN_MEAN_LENGTH:
        return False
    space_ratio = s.count(" ") / len(s)
    if space_ratio > _MAX_SPACE_RATIO:
        return False
    if _is_hex_hash(s):
        return True
    return _shannon_entropy(s) >= _ENTROPY_THRESHOLD


def classify_opaque_tokens(
    column_id: str,
    sample_values: list[str],
) -> list[ClassificationFinding]:
    """Classify opaque-token columns by Shannon entropy + hex detection.

    Two paths:
      1. High-entropy path: entropy >= 4.2 bits/char AND space ratio < 5%
         (catches base64, JWTs, session IDs, URL-safe tokens).
      2. Hex-hash path: all chars are hex AND length >= 32
         (catches SHA-256, MD5, etc. which have lower entropy ~3.8).

    Returns a single OPAQUE_SECRET finding if >= 50% of values match
    either path, or empty list otherwise.
    """
    if not sample_values:
        return []

    non_empty = [v for v in sample_values if v and len(v.strip()) > 0]
    if not non_empty:
        return []

    opaque_count = sum(1 for v in non_empty if _is_opaque_value(v))
    coverage = opaque_count / len(non_empty)

    if coverage < _MIN_COVERAGE:
        return []

    mean_length = sum(len(v) for v in non_empty) / len(non_empty)
    mean_entropy = sum(_shannon_entropy(v) for v in non_empty) / len(non_empty)

    # Confidence scales with coverage and entropy distance above threshold.
    confidence = min(0.95, 0.6 + 0.2 * max(0, mean_entropy - _ENTROPY_THRESHOLD) + 0.15 * coverage)

    return [
        ClassificationFinding(
            column_id=column_id,
            entity_type="OPAQUE_SECRET",
            category="Credential",
            sensitivity="HIGH",
            confidence=round(confidence, 4),
            regulatory=["GDPR"],
            engine="entropy",
            evidence=(
                f"Entropy-based: mean_entropy={mean_entropy:.2f} bits/char, "
                f"mean_length={mean_length:.0f}, "
                f"coverage={coverage:.0%} of values above {_ENTROPY_THRESHOLD} threshold"
            ),
            sample_analysis=SampleAnalysis(
                samples_scanned=len(non_empty),
                samples_matched=opaque_count,
                samples_validated=opaque_count,
                match_ratio=coverage,
                sample_matches=[v[:40] + "..." if len(v) > 40 else v for v in non_empty[:5]],
            ),
        )
    ]
