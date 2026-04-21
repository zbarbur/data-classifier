"""Curated pattern library for content-based classification.

Patterns are defined in ``default_patterns.json`` and loaded once at module
import.  Each pattern has: name, regex (RE2-compatible), category, entity_type,
sensitivity, confidence, validators, and test examples.

The pattern library is separate from the profile YAML:
- **Profile YAML** defines column-name matching rules (which entity types to
  detect, in what order, with what confidence).  Profile-configurable.
- **Pattern library** defines content-matching regexes (how to detect entity
  values in sample data).  Curated by the library; consumer-extensible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from data_classifier.patterns._decoder import decode_encoded_strings

_PATTERNS_DIR = Path(__file__).parent
_DEFAULT_PATTERNS_FILE = _PATTERNS_DIR / "default_patterns.json"

__all__ = [
    "ContentPattern",
    "load_default_patterns",
]


@dataclass
class ContentPattern:
    """A single content-matching regex pattern with metadata."""

    name: str
    """Unique pattern identifier (e.g. ``us_ssn``, ``credit_card_luhn``)."""

    regex: str
    """RE2-compatible regex pattern."""

    entity_type: str
    """Classification entity type this pattern detects."""

    category: str
    """Data category: PII, Financial, Credential, Health."""

    sensitivity: str
    """Default sensitivity level."""

    confidence: float
    """Base confidence when this pattern matches."""

    description: str = ""
    """Human-readable description of what this pattern detects."""

    display_name: str = ""
    """Short human-friendly label (e.g. ``AWS Access Key``, ``GitHub Token``).
    Used in client-facing findings.  If empty, derived from ``name``."""

    validator: str = ""
    """Name of secondary validator to apply (e.g. ``luhn``, ``ssn_zeros``)."""

    examples_match: list[str] = field(default_factory=list)
    """Values that SHOULD match this pattern (for testing)."""

    examples_no_match: list[str] = field(default_factory=list)
    """Values that should NOT match (for false positive testing)."""

    context_words_boost: list[str] = field(default_factory=list)
    """Words near a match that INCREASE confidence (e.g. 'ssn' near a 9-digit number)."""

    context_words_suppress: list[str] = field(default_factory=list)
    """Words near a match that DECREASE confidence (e.g. 'order' near a 9-digit number)."""

    stopwords: list[str] = field(default_factory=list)
    """Known placeholder values — if the match equals a stopword, confidence → 0."""

    allowlist_patterns: list[str] = field(default_factory=list)
    """Regex patterns — if any matches the extracted value, confidence → 0."""

    requires_column_hint: bool = False
    """If True, this pattern only fires when the column name contains one of
    ``column_hint_keywords``. Used for patterns that would produce catastrophic
    false positives on content alone (e.g. random password detection)."""

    column_hint_keywords: list[str] = field(default_factory=list)
    """Case-insensitive substrings to search for in the column name when
    ``requires_column_hint`` is True. Any match allows the pattern to fire."""


# Backwards-compatibility alias for the shared decoder. Prefer importing
# ``decode_encoded_strings`` from ``data_classifier.patterns._decoder``
# in new code; this shim keeps older imports (``_decode_examples``)
# working until they're migrated.
_decode_examples = decode_encoded_strings


def load_default_patterns() -> list[ContentPattern]:
    """Load the bundled default pattern library.

    Credential examples are XOR-encoded in the JSON and decoded at load time.
    """
    with open(_DEFAULT_PATTERNS_FILE) as fh:
        raw = json.load(fh)

    patterns = []
    for p in raw["patterns"]:
        p["examples_match"] = decode_encoded_strings(p.get("examples_match", []))
        p["examples_no_match"] = decode_encoded_strings(p.get("examples_no_match", []))
        patterns.append(ContentPattern(**p))
    return patterns
