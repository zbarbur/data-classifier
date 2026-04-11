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


class TestAwsSecretKeyPattern:
    """Tests for the redesigned aws_secret_key pattern with context requirements."""

    @pytest.fixture(autouse=True)
    def _load_pattern(self):
        matches = [p for p in _PATTERNS if p.name == "aws_secret_key"]
        assert len(matches) == 1, "Expected exactly one aws_secret_key pattern"
        self.pattern = matches[0]

    def test_base_confidence_is_low(self):
        """Base confidence should be low enough that it needs context boost to be actionable."""
        assert self.pattern.confidence <= 0.40, (
            f"aws_secret_key base confidence {self.pattern.confidence} is too high — "
            "pattern is too broad without context"
        )

    def test_has_context_words_boost(self):
        """Pattern must have context_words_boost to require AWS-specific context."""
        assert len(self.pattern.context_words_boost) >= 3, (
            "aws_secret_key needs context_words_boost for AWS-specific keywords"
        )

    def test_context_words_include_aws_keywords(self):
        """Context boost words should include common AWS secret key field names."""
        boost_lower = {w.lower() for w in self.pattern.context_words_boost}
        for keyword in ["aws_secret", "secret_access_key"]:
            assert keyword in boost_lower, f"Missing expected context boost word: {keyword}"

    def test_has_context_words_suppress(self):
        """Pattern should suppress on hash/checksum contexts to reduce FPs."""
        assert len(self.pattern.context_words_suppress) >= 2, (
            "aws_secret_key needs context_words_suppress for hash/checksum contexts"
        )

    def test_suppress_words_include_hash_keywords(self):
        """Context suppress words should include hash-related terms."""
        suppress_lower = {w.lower() for w in self.pattern.context_words_suppress}
        for keyword in ["sha", "hash", "checksum"]:
            assert keyword in suppress_lower, f"Missing expected context suppress word: {keyword}"

    def test_validator_is_aws_secret_not_hex(self):
        """Pattern should still use the aws_secret_not_hex validator."""
        assert self.pattern.validator == "aws_secret_not_hex"

    def test_has_stopwords(self):
        """Pattern should retain stopwords for placeholder values."""
        assert len(self.pattern.stopwords) > 0


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
