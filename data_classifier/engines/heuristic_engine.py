"""Heuristic statistics engine — classifies columns by value distribution signals.

Analyzes sample value distributions (cardinality, entropy, length consistency,
character class ratios) to produce classification findings.  Key use case:
disambiguating SSN vs ABA routing numbers — high cardinality implies SSN
(unique per person), low cardinality implies ABA (few bank routing numbers
reused across rows).

This engine produces standalone findings.  The orchestrator's "highest
confidence wins" deduplication handles disambiguation naturally when
combined with regex engine findings.
"""

from __future__ import annotations

import logging
import math
from collections import Counter

from data_classifier.config import load_engine_config
from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
)
from data_classifier.engines.interface import ClassificationEngine

logger = logging.getLogger(__name__)


# ── Pure signal computation functions ───────────────────────────────────────


def compute_cardinality_ratio(values: list[str]) -> float:
    """Chao-1 bias-corrected distinctness estimate, ratioed against sample size.

    Starts from the observed distinct count ``D`` and adds the Chao-1
    richness correction ``f1 * (f1 - 1) / (2 * (f2 + 1))`` to account
    for unseen species implied by the singleton/doubleton structure,
    where ``f1`` is the number of values that appear exactly once and
    ``f2`` is the number that appear exactly twice. The ``+1`` in the
    denominator is Chao's bias-corrected form — it keeps the estimator
    well-defined when ``f2 == 0``.

    When ``f1 == 0`` (every value appears two or more times) the
    correction collapses to zero and the result equals the naive
    ``D / N``.  When ``f1 > 0`` the estimate grows toward the true
    cardinality; this is the case we care about for low-sample-count
    columns where the naive ratio systematically undercounts richness.

    Args:
        values: Sample values from the column.

    Returns:
        Float clipped to ``[0.0, 1.0]``.  ``1.0`` still means "every
        sampled value is unique and the sample is too small to rule
        out unbounded richness" — callers that need absolute counts
        should consult ``ColumnStats`` instead.
    """
    if not values:
        return 0.0
    n = len(values)
    counts = Counter(values)
    observed_distinct = len(counts)
    f1 = sum(1 for c in counts.values() if c == 1)
    f2 = sum(1 for c in counts.values() if c == 2)
    estimated_distinct = observed_distinct + (f1 * (f1 - 1)) / (2.0 * (f2 + 1))
    ratio = estimated_distinct / n
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio


def compute_shannon_entropy(value: str) -> float:
    """Compute Shannon entropy in bits per character for a single value.

    Args:
        value: A single string value.

    Returns:
        Entropy in bits/char.  Higher means more random/uniform distribution.
    """
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    entropy = 0.0
    for count in counts.values():
        prob = count / length
        if prob > 0:
            entropy -= prob * math.log2(prob)
    return entropy


def compute_avg_entropy(values: list[str]) -> float:
    """Compute average Shannon entropy across all values.

    Args:
        values: Sample values from the column.

    Returns:
        Average entropy in bits/char.
    """
    if not values:
        return 0.0
    entropies = [compute_shannon_entropy(v) for v in values if v]
    if not entropies:
        return 0.0
    return sum(entropies) / len(entropies)


def compute_length_stats(values: list[str]) -> dict:
    """Compute length distribution statistics.

    Args:
        values: Sample values from the column.

    Returns:
        Dict with keys: mean, stddev, min, max, uniform (bool).
        ``uniform`` is True when all values have the same length.
    """
    if not values:
        return {"mean": 0.0, "stddev": 0.0, "min": 0, "max": 0, "uniform": True}

    lengths = [len(v) for v in values]
    n = len(lengths)
    mean = sum(lengths) / n
    variance = sum((ln - mean) ** 2 for ln in lengths) / n
    stddev = math.sqrt(variance)
    min_len = min(lengths)
    max_len = max(lengths)
    uniform = min_len == max_len

    return {
        "mean": mean,
        "stddev": stddev,
        "min": min_len,
        "max": max_len,
        "uniform": uniform,
    }


def compute_char_class_ratios(values: list[str]) -> dict:
    """Compute character class ratios across all values.

    For each value, determine its dominant character class, then compute the
    fraction of values in each class.

    Args:
        values: Sample values from the column.

    Returns:
        Dict with keys: digit_ratio, alpha_ratio, alnum_ratio, special_ratio.
        Each is the fraction of values that are purely that class.
    """
    if not values:
        return {"digit_ratio": 0.0, "alpha_ratio": 0.0, "alnum_ratio": 0.0, "special_ratio": 0.0}

    n = len(values)
    digit_count = 0
    alpha_count = 0
    alnum_count = 0
    special_count = 0

    for v in values:
        if not v:
            continue
        if v.isdigit():
            digit_count += 1
        elif v.isalpha():
            alpha_count += 1
        elif v.isalnum():
            alnum_count += 1
        else:
            special_count += 1

    return {
        "digit_ratio": digit_count / n,
        "alpha_ratio": alpha_count / n,
        "alnum_ratio": alnum_count / n,
        "special_ratio": special_count / n,
    }


def compute_char_class_diversity(value: str) -> int:
    """Count how many character classes are present in a single value.

    Classes: uppercase, lowercase, digits, special characters.
    Returns 0-4.  Real secrets typically use 3-4 classes; numeric IDs
    use 1, natural text uses 2-3 (but rarely has digits + special together).
    """
    if not value:
        return 0
    classes = 0
    has_upper = has_lower = has_digit = has_special = False
    for c in value:
        if c.isupper():
            has_upper = True
        elif c.islower():
            has_lower = True
        elif c.isdigit():
            has_digit = True
        else:
            has_special = True
    classes = sum([has_upper, has_lower, has_digit, has_special])
    return classes


def compute_avg_char_class_diversity(values: list[str]) -> float:
    """Average character class diversity across all values.

    Returns 0.0-4.0.  Higher means values use more character classes,
    which is a strong signal for credential-like content.
    """
    if not values:
        return 0.0
    diversities = [compute_char_class_diversity(v) for v in values if v]
    if not diversities:
        return 0.0
    return sum(diversities) / len(diversities)


# ── Dictionary-word-ratio feature (Sprint 11 Phase 7) ───────────────────────
#
# Motivation: distinguish English-text-heavy columns (passwords, names,
# descriptions — often dictionary-word placeholder data) from random-looking
# identifier columns (hashes, API tokens, UUIDs — no dictionary words).
#
# Definition: a value "contains a dictionary word" if, after tokenizing on
# [a-z]+ boundaries, any token of at least `min_token_length` characters is
# present in the curated English content-words list. The column's ratio is
# the fraction of values that contain at least one such dictionary word.
#
# Word list: data_classifier/patterns/content_words.json — ~2300 curated
# common English content words (5+ chars). Explicitly excludes credential
# prefix tokens (the handful of short words that appear verbatim in real
# payment-processor keys, version-control PATs, and cloud service tokens)
# as well as ambiguous technical terms (git, hash, uuid, sha, md5, aws,
# gcp, http, code) so legitimate credentials are not falsely rejected.
#
# The list is loaded lazily on first call and cached as a frozenset.


import re as _re  # noqa: E402 — local alias to avoid adding a top-level re import

_CONTENT_WORDS: frozenset[str] | None = None
_CONTENT_WORDS_MIN_LEN: int = 5
_CONTENT_WORDS_TOKEN_RE = _re.compile(r"[a-z]+")


def _load_content_words_once() -> frozenset[str]:
    """Load content_words.json and return a frozenset of lowercase words.

    Subsequent calls return the cached set.  If the file is missing or
    malformed, returns an empty set so the caller (compute_dictionary_word_ratio)
    gracefully degrades to a 0.0 ratio instead of raising.
    """
    global _CONTENT_WORDS, _CONTENT_WORDS_MIN_LEN
    if _CONTENT_WORDS is not None:
        return _CONTENT_WORDS

    import json
    from pathlib import Path

    path = Path(__file__).parent.parent / "patterns" / "content_words.json"
    try:
        with path.open() as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _CONTENT_WORDS = frozenset()
        return _CONTENT_WORDS

    min_len = int(raw.get("min_token_length", 5))
    words = raw.get("content_words", [])
    _CONTENT_WORDS_MIN_LEN = min_len
    _CONTENT_WORDS = frozenset(w.lower() for w in words if isinstance(w, str) and len(w) >= min_len)
    return _CONTENT_WORDS


def _value_contains_dictionary_word(value: str) -> bool:
    """True iff the value contains at least one English content word
    (lowercased, 5+ chars) after [a-z]+ tokenization.

    Examples:
      >>> _value_contains_dictionary_word("password123")  # True
      >>> _value_contains_dictionary_word("admin_backup")  # True
      >>> _value_contains_dictionary_word("xk9fpq2vLcHmsdFt")  # False
      >>> _value_contains_dictionary_word("a8B3cD2eF1gH9iJ0kL")  # False
    """
    words = _load_content_words_once()
    if not words:
        return False
    tokens = _CONTENT_WORDS_TOKEN_RE.findall(value.lower())
    for t in tokens:
        if len(t) >= _CONTENT_WORDS_MIN_LEN and t in words:
            return True
    return False


def compute_dictionary_word_ratio(values: list[str]) -> float:
    """Fraction of sample values that contain at least one English content word.

    Args:
        values: Sample values from the column.

    Returns:
        Float between 0.0 and 1.0.  0.0 means no value contains a dictionary
        word (random-looking identifiers / hashes / tokens).  1.0 means every
        value contains at least one English content word (passwords, names,
        descriptions, text).
    """
    if not values:
        return 0.0
    hits = sum(1 for v in values if v and _value_contains_dictionary_word(v))
    return hits / len(values)


# ── OPAQUE_SECRET detection (Sprint 8 Item 4) ───────────────────────────────
#
# Multi-signal guard for high-entropy credential-shaped values that do NOT
# match any specific pattern. Per the memory file
# ``feedback_entropy_secondary.md`` entropy alone produced 37 false positives,
# so this function fires only when ALL of the following hold:
#   1. column name contains a credential hint keyword
#      (prevents FPs on UUIDs, hashes, tokens in unrelated columns)
#   2. average entropy > ~4.5 bits/char (non-language randomness)
#   3. non-language char-class profile (multi-class OR non-alpha mix)
#   4. value length in range 20-200 (filters short IDs and long blobs)
#   5. high per-column distinct ratio (>=0.9 — real secrets are unique)
#
# Condition 1 substitutes for "no other engine claimed the row" because
# inside a single engine we have no cross-engine coordination; instead we
# gate emission on the column name being a credential-like column.

# Column name substrings that hint at a credential column.
_OPAQUE_SECRET_COLUMN_HINTS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "passphrase",
        "passcode",
        "pwd",
        "secret",
        "token",
        "credential",
        "credentials",
        "api_key",
        "apikey",
        "auth",
    }
)

_OPAQUE_MIN_ENTROPY = 4.5
_OPAQUE_MIN_LENGTH = 20
_OPAQUE_MAX_LENGTH = 200
_OPAQUE_MIN_DIVERSITY = 3
_OPAQUE_MIN_DISTINCT_RATIO = 0.9


def _column_name_has_credential_hint(column_name: str | None) -> bool:
    if not column_name:
        return False
    lowered = column_name.lower()
    return any(hint in lowered for hint in _OPAQUE_SECRET_COLUMN_HINTS)


def opaque_secret_detection(values: list[str], column_name: str | None) -> tuple[bool, str]:
    """Multi-signal opaque-secret detector for credential-gated columns.

    Fires only when ALL five conditions hold:
        1. column name hints at a credential column (see
           ``_OPAQUE_SECRET_COLUMN_HINTS``);
        2. average Shannon entropy >= 4.5 bits/char;
        3. length in [20, 200] for the majority of samples;
        4. average char-class diversity >= 3 (non-language randomness);
        5. distinct-value ratio >= 0.9 (values are nearly unique per row).

    Args:
        values: Non-empty list of sample values from the column.
        column_name: The column name (used as a gate, never standalone).

    Returns:
        Tuple of ``(is_opaque_secret, evidence_string)``.  If the column
        fails any condition, returns ``(False, reason)``.
    """
    # Condition 1: column-name gate.  Without this, entropy-only signals
    # caused 37 FPs in Sprint 4 — see feedback_entropy_secondary.md.
    if not _column_name_has_credential_hint(column_name):
        return False, f"column '{column_name}' lacks credential hint"

    # Filter empties for the other stats
    non_empty = [v for v in values if v]
    if len(non_empty) < 2:
        return False, "not enough non-empty samples"

    # Condition 4 (cheap): length window
    lengths = [len(v) for v in non_empty]
    in_range = sum(1 for ln in lengths if _OPAQUE_MIN_LENGTH <= ln <= _OPAQUE_MAX_LENGTH)
    if in_range / len(non_empty) < 0.5:
        return False, "length distribution outside 20-200 range"

    # Condition 3: diversity
    avg_diversity = compute_avg_char_class_diversity(non_empty)
    if avg_diversity < _OPAQUE_MIN_DIVERSITY:
        return False, f"avg diversity {avg_diversity:.2f} < {_OPAQUE_MIN_DIVERSITY}"

    # Condition 2: entropy (always CONFIRM another signal, never standalone)
    avg_entropy = compute_avg_entropy(non_empty)
    if avg_entropy < _OPAQUE_MIN_ENTROPY:
        return False, f"avg entropy {avg_entropy:.2f} < {_OPAQUE_MIN_ENTROPY}"

    # Condition 5: distinctness
    distinct_ratio = compute_cardinality_ratio(non_empty)
    if distinct_ratio < _OPAQUE_MIN_DISTINCT_RATIO:
        return False, f"distinct ratio {distinct_ratio:.2f} < {_OPAQUE_MIN_DISTINCT_RATIO}"

    evidence = (
        f"opaque_secret_detection: column='{column_name}' "
        f"entropy={avg_entropy:.2f} diversity={avg_diversity:.2f} "
        f"length_in_range={in_range}/{len(non_empty)} "
        f"distinct_ratio={distinct_ratio:.2f}"
    )
    return True, evidence


# ── Engine ──────────────────────────────────────────────────────────────────


class HeuristicEngine(ClassificationEngine):
    """Heuristic statistics engine — order 3 in the cascade.

    Analyzes column sample value distributions to produce classification
    findings based on cardinality, entropy, length consistency, and
    character class ratios.
    """

    name = "heuristic_stats"
    order = 3
    min_confidence = 0.0
    supported_modes = frozenset({"structured"})

    def __init__(self) -> None:
        self._config: dict | None = None

    def startup(self) -> None:
        """Load engine configuration from engine_defaults.yaml."""
        full_config = load_engine_config()
        self._config = full_config.get("heuristic_engine", {})

    def _ensure_config(self) -> None:
        """Lazily load config if startup() was not called."""
        if self._config is None:
            self.startup()

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Classify a column using heuristic statistical signals.

        Returns findings based on cardinality, entropy, length, and
        character class analysis of sample values.
        """
        self._ensure_config()

        min_samples = self._config["min_samples"]
        signals_config = self._config["signals"]
        cardinality_config = signals_config["cardinality"]
        char_class_config = signals_config["char_class"]

        # Thresholds from config — no hardcoded fallbacks
        low_cardinality = cardinality_config["low_threshold"]
        high_cardinality = cardinality_config["high_threshold"]
        digit_purity = char_class_config["digit_purity_threshold"]

        values = column.sample_values

        # Check minimum sample count
        if len(values) < min_samples:
            return []

        # Compute signals
        cardinality = compute_cardinality_ratio(values)
        length_stats = compute_length_stats(values)
        char_ratios = compute_char_class_ratios(values)

        # Use ColumnStats if available for cardinality (connector pre-computed)
        if column.stats and column.stats.total_count > 0 and column.stats.distinct_count > 0:
            cardinality = column.stats.distinct_count / column.stats.total_count

        findings: list[ClassificationFinding] = []

        # ── Rule: High cardinality + all-digits + uniform length 9 → SSN ──
        if (
            cardinality >= high_cardinality
            and char_ratios["digit_ratio"] >= digit_purity
            and length_stats["uniform"]
            and length_stats["mean"] == 9
        ):
            confidence = 0.70 + 0.15 * cardinality  # 0.82-0.85 for high cardinality
            confidence = min(confidence, 0.95)
            if confidence >= min_confidence:
                findings.append(
                    ClassificationFinding(
                        column_id=column.column_id,
                        entity_type="SSN",
                        category="PII",
                        sensitivity="CRITICAL",
                        confidence=round(confidence, 4),
                        regulatory=["HIPAA", "CCPA", "GDPR"],
                        engine=self.name,
                        evidence=(
                            f"Heuristic: cardinality={cardinality:.2f} (high), "
                            f"uniform length=9, digit_ratio={char_ratios['digit_ratio']:.2f}"
                        ),
                    )
                )

        # ── Rule: Low cardinality + all-digits + uniform length 9 → ABA_ROUTING ──
        if (
            cardinality <= low_cardinality
            and char_ratios["digit_ratio"] >= digit_purity
            and length_stats["uniform"]
            and length_stats["mean"] == 9
        ):
            confidence = 0.75 + 0.10 * (1.0 - cardinality)  # higher when more repeated
            confidence = min(confidence, 0.90)
            if confidence >= min_confidence:
                findings.append(
                    ClassificationFinding(
                        column_id=column.column_id,
                        entity_type="ABA_ROUTING",
                        category="Financial",
                        sensitivity="HIGH",
                        confidence=round(confidence, 4),
                        regulatory=["GLBA", "PCI-DSS"],
                        engine=self.name,
                        evidence=(
                            f"Heuristic: cardinality={cardinality:.2f} (low), "
                            f"uniform length=9, digit_ratio={char_ratios['digit_ratio']:.2f}"
                        ),
                    )
                )

        # NOTE: Specific CREDENTIAL formats (API keys, JWTs, PEM keys) are handled
        # by the regex engine. Structured KV secret detection is handled by the
        # secret scanner (order=4). The heuristic engine's only credential-related
        # rule is OPAQUE_SECRET: a column-gated, multi-signal catch-all for
        # high-entropy credential-shaped values that did not match any pattern.
        # See ``opaque_secret_detection`` docstring for the five guard conditions.

        is_opaque, opaque_evidence = opaque_secret_detection(values, column.column_name)
        if is_opaque:
            # Conservative confidence — this is a heuristic signal, not a shape
            # match. The orchestrator may still defer to higher-authority engines
            # if they produced a more specific finding for the same column.
            confidence = 0.75
            if confidence >= min_confidence:
                findings.append(
                    ClassificationFinding(
                        column_id=column.column_id,
                        entity_type="OPAQUE_SECRET",
                        category="Credential",
                        sensitivity="CRITICAL",
                        confidence=round(confidence, 4),
                        regulatory=["SOC2", "ISO27001"],
                        engine=self.name,
                        evidence=opaque_evidence,
                    )
                )

        return findings
