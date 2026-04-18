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
from data_classifier.patterns._decoder import decode_encoded_strings

_PATTERNS = load_default_patterns()


def _decode_example(value: str) -> str:
    """Decode xor:/b64:-prefixed examples to raw text."""
    if value.startswith(("xor:", "b64:")):
        decoded = decode_encoded_strings([value])
        return decoded[0] if decoded else value
    return value


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
            decoded = _decode_example(example)
            assert compiled.search(decoded), f"Pattern '{pattern.name}' should match '{decoded[:80]}...' but didn't"

    def test_examples_no_match(self, pattern):
        """Every examples_no_match value does NOT match the regex."""
        compiled = re2.compile(pattern.regex)
        for example in pattern.examples_no_match:
            decoded = _decode_example(example)
            assert not compiled.search(decoded), (
                f"Pattern '{pattern.name}' should NOT match '{decoded[:80]}...' but did"
            )

    def test_has_required_metadata(self, pattern):
        """Pattern has all required metadata fields."""
        assert pattern.name, "Pattern must have a name"
        assert pattern.entity_type, "Pattern must have an entity_type"
        assert pattern.category in ("PII", "Financial", "Credential", "Health"), f"Invalid category: {pattern.category}"
        assert pattern.sensitivity in ("LOW", "MEDIUM", "HIGH", "CRITICAL"), (
            f"Invalid sensitivity: {pattern.sensitivity}"
        )
        assert 0.0 < pattern.confidence <= 1.0, f"Confidence must be (0, 1], got {pattern.confidence}"


class TestHealthPatternAudit:
    """Regression: HEALTH patterns must not fire on non-health data.

    Sprint 5 fix — icd10_code pattern was too broad (matching any letter+2digits),
    causing ghost FPs on columns with generic alphanumeric codes.
    """

    def test_icd10_requires_decimal(self):
        """ICD-10 pattern must require the decimal portion to match."""
        icd_pattern = next(p for p in _PATTERNS if p.name == "icd10_code")
        compiled = re2.compile(icd_pattern.regex)

        # Should match full ICD-10 codes with decimal
        assert compiled.search("E11.9"), "Should match E11.9"
        assert compiled.search("J06.9"), "Should match J06.9"
        assert compiled.search("M54.5"), "Should match M54.5"
        assert compiled.search("I10.0"), "Should match I10.0"

        # Should NOT match bare letter+2digits (too generic)
        assert not compiled.search("A01"), "Should NOT match A01 (too generic)"
        assert not compiled.search("B12"), "Should NOT match B12 (too generic)"
        assert not compiled.search("C99"), "Should NOT match C99 (too generic)"

    def test_icd10_low_confidence(self):
        """ICD-10 pattern must have low base confidence (needs context)."""
        icd_pattern = next(p for p in _PATTERNS if p.name == "icd10_code")
        assert icd_pattern.confidence <= 0.35, (
            f"ICD-10 confidence {icd_pattern.confidence} too high — should be <= 0.35 to avoid FPs"
        )

    def test_icd10_has_context_words(self):
        """ICD-10 pattern should have context words for boosting and suppression."""
        icd_pattern = next(p for p in _PATTERNS if p.name == "icd10_code")
        assert len(icd_pattern.context_words_boost) > 0, "Should have boost context words"
        assert len(icd_pattern.context_words_suppress) > 0, "Should have suppress context words"

    def test_icd10_no_match_on_product_codes(self):
        """ICD-10 should not match common product/version codes."""
        icd_pattern = next(p for p in _PATTERNS if p.name == "icd10_code")
        compiled = re2.compile(icd_pattern.regex)
        for code in ["SKU123", "V8", "R2D2", "T800"]:
            assert not compiled.search(code), f"Should NOT match {code}"


class TestSsnConfidenceGating:
    """Regression: SSN pattern must not fire without context.

    Sprint 5 fix — SSN no-dashes pattern must have low base confidence
    so it stays below min_confidence (0.5) without column-name or format context.
    The formatted SSN (with dashes) is a strong format signal and surfaces normally.
    """

    def test_ssn_no_dashes_below_threshold(self):
        """SSN no-dashes pattern must have confidence below 0.5."""
        ssn_pattern = next(p for p in _PATTERNS if p.name == "us_ssn_no_dashes")
        assert ssn_pattern.confidence < 0.5, (
            f"SSN no-dashes confidence {ssn_pattern.confidence} too high — must be below 0.5"
        )

    def test_ssn_formatted_has_high_confidence(self):
        """SSN formatted pattern (with dashes) should have high confidence."""
        ssn_pattern = next(p for p in _PATTERNS if p.name == "us_ssn_formatted")
        assert ssn_pattern.confidence >= 0.90, (
            f"SSN formatted confidence {ssn_pattern.confidence} too low — dashes are a strong signal"
        )

    def test_ssn_no_dashes_has_context_boost(self):
        """SSN no-dashes pattern should have context boost words."""
        ssn_pattern = next(p for p in _PATTERNS if p.name == "us_ssn_no_dashes")
        assert len(ssn_pattern.context_words_boost) > 0
        boost_lower = {w.lower() for w in ssn_pattern.context_words_boost}
        assert "ssn" in boost_lower or "social security" in boost_lower

    def test_ssn_no_dashes_stays_below_with_many_matches(self):
        """Even with many matches, SSN no-dashes should not exceed 0.5."""
        from data_classifier.engines.regex_engine import _compute_sample_confidence

        ssn_pattern = next(p for p in _PATTERNS if p.name == "us_ssn_no_dashes")
        # Test with many matches (>20), which gives the 1.05 multiplier
        conf = _compute_sample_confidence(ssn_pattern.confidence, matches=50, validated=50)
        assert conf < 0.50, f"SSN no-dashes with 50 matches: {conf} >= 0.50"

    def test_ssn_formatted_surfaces_with_dashes(self):
        """SSN with dashes pattern should surface above threshold."""
        from data_classifier.engines.regex_engine import _compute_sample_confidence

        ssn_pattern = next(p for p in _PATTERNS if p.name == "us_ssn_formatted")
        # Even with few matches
        conf = _compute_sample_confidence(ssn_pattern.confidence, matches=3, validated=3)
        assert conf >= 0.50, f"SSN formatted with 3 matches: {conf} < 0.50"


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
