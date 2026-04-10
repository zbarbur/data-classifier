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

_PATTERNS_DIR = Path(__file__).parent
_DEFAULT_PATTERNS_FILE = _PATTERNS_DIR / "default_patterns.json"


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

    validator: str = ""
    """Name of secondary validator to apply (e.g. ``luhn``, ``ssn_zeros``)."""

    examples_match: list[str] = field(default_factory=list)
    """Values that SHOULD match this pattern (for testing)."""

    examples_no_match: list[str] = field(default_factory=list)
    """Values that should NOT match (for false positive testing)."""


def load_default_patterns() -> list[ContentPattern]:
    """Load the bundled default pattern library."""
    with open(_DEFAULT_PATTERNS_FILE) as fh:
        raw = json.load(fh)
    return [ContentPattern(**p) for p in raw["patterns"]]
