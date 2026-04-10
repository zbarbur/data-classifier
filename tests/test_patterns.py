"""Tests for the content pattern library.

Validates every pattern in default_patterns.json:
- Compiles in RE2
- examples_match values match the regex
- examples_no_match values do NOT match the regex
- Validators accept/reject correctly
"""

from __future__ import annotations

import pytest
import re2

from data_classifier.patterns import load_default_patterns

_PATTERNS = load_default_patterns()


@pytest.mark.parametrize(
    "pattern",
    _PATTERNS,
    ids=[p.name for p in _PATTERNS],
)
class TestPatternExamples:
    def test_compiles_in_re2(self, pattern):
        """Pattern regex compiles without error in RE2."""
        re2.compile(pattern.regex)

    def test_examples_match(self, pattern):
        """Every examples_match value matches the regex."""
        compiled = re2.compile(pattern.regex)
        for example in pattern.examples_match:
            assert compiled.search(example), f"Pattern '{pattern.name}' should match '{example}' but didn't"

    def test_examples_no_match(self, pattern):
        """Every examples_no_match value does NOT match the regex."""
        compiled = re2.compile(pattern.regex)
        for example in pattern.examples_no_match:
            assert not compiled.search(example), f"Pattern '{pattern.name}' should NOT match '{example}' but did"

    def test_has_required_metadata(self, pattern):
        """Pattern has all required metadata fields."""
        assert pattern.name, "Pattern must have a name"
        assert pattern.entity_type, "Pattern must have an entity_type"
        assert pattern.category in ("PII", "Financial", "Credential", "Health"), f"Invalid category: {pattern.category}"
        assert pattern.sensitivity in ("LOW", "MEDIUM", "HIGH", "CRITICAL"), (
            f"Invalid sensitivity: {pattern.sensitivity}"
        )
        assert 0.0 < pattern.confidence <= 1.0, f"Confidence must be (0, 1], got {pattern.confidence}"


class TestPatternLibraryIntegrity:
    def test_no_duplicate_names(self):
        """All pattern names are unique."""
        names = [p.name for p in _PATTERNS]
        assert len(names) == len(set(names)), f"Duplicate names: {[n for n in names if names.count(n) > 1]}"

    def test_re2_set_compiles(self):
        """All patterns compile together into an RE2 Set."""
        s = re2.Set(re2._Anchor.UNANCHORED)
        for p in _PATTERNS:
            s.Add(p.regex)
        s.Compile()  # should not raise

    def test_minimum_pattern_count(self):
        """Library ships with a minimum number of patterns."""
        assert len(_PATTERNS) >= 40, f"Expected 40+ patterns, got {len(_PATTERNS)}"

    def test_all_categories_covered(self):
        """All four categories have at least one pattern."""
        categories = {p.category for p in _PATTERNS}
        for expected in ("PII", "Financial", "Credential", "Health"):
            assert expected in categories, f"Missing category: {expected}"
