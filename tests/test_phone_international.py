"""Regex-level tests for international phone coverage (Sprint 7).

Sprint 6 closed with the Ai4Privacy PHONE column at 0% regex match rate:
52% of that corpus has ``+CC`` prefixes in multi-segment mixed-separator
formats (``+543 51-082.8035``), and 48% uses ``0``- or ``00``-prefixed
local/international-access formats (``076 1352.8018``, ``00758-30091``).
The Sprint 6 ``international_phone`` regex only allows a single separator
after the country code, so it fails on both sub-populations.

These tests target the regexes directly (via ``re2.compile``) rather than
the full ``classify_columns`` pipeline because:

1. The ``column_name_engine`` will emit PHONE findings based on the column
   name alone (e.g. ``column_name='phone'``) regardless of content, which
   would hide regex failures behind pipeline successes.

2. The Sprint 7 acceptance criterion ``match_ratio >= 0.70`` measures
   per-value regex matching in the content pipeline — the same level this
   file tests.

Real samples are drawn from ``tests/fixtures/corpora/ai4privacy_sample.json``.
"""

from __future__ import annotations

import pytest
import re2

from data_classifier.patterns import ContentPattern, load_default_patterns


@pytest.fixture(scope="module")
def patterns_by_name() -> dict[str, ContentPattern]:
    return {p.name: p for p in load_default_patterns()}


def _full_match(pattern_str: str, value: str) -> bool:
    """Return True if the regex matches with at least 80% value coverage.

    80% (not 100%) because real phone strings sometimes have leading/trailing
    whitespace, punctuation, or label prefixes that aren't worth anchoring on.
    """
    m = re2.compile(pattern_str).search(value)
    if m is None:
        return False
    coverage = (m.end() - m.start()) / len(value.strip())
    return coverage >= 0.80


class TestInternationalPhonePlusPrefixed:
    """``international_phone`` must match +CC + multi-segment mixed-separator."""

    @pytest.mark.parametrize(
        "value",
        [
            # Real Ai4Privacy samples (all currently 0% match)
            "+543 51-082.8035",  # Argentina, 3 groups, mixed space/dash/dot
            "+51-063-367.7939",  # Peru, dash + dot
            # Canonical multi-segment international formats
            "+44 20 7946 0958",  # UK London — 4 space-separated groups
            "+49 30 1234567",  # Germany — 2 groups, long second
            "+33 1 42 34 56 78",  # France — 5 one/two-digit groups
            "+81 3 1234 5678",  # Japan — 3 groups
            "+61 2 9876 5432",  # Australia — 3 groups
            "+1-555-867-5309",  # US international, dashes
            "+1 555 867 5309",  # US international, spaces
        ],
    )
    def test_multi_segment_matched(self, value: str, patterns_by_name: dict[str, ContentPattern]) -> None:
        pattern = patterns_by_name["international_phone"]
        assert _full_match(pattern.regex, value), (
            f"{value!r} not fully matched by international_phone regex {pattern.regex!r}"
        )


class TestInternationalPhoneLocalPrefixed:
    """New ``international_phone_local`` pattern must match 0/00-prefixed
    multi-segment formats without requiring a ``+`` sign.
    """

    @pytest.mark.parametrize(
        "value",
        [
            # Real Ai4Privacy samples
            "076 1352.8018",
            "01881.881.151-3030",
            "0070-07 986.4979",
            "00758-30091",
            "099 3802-9499",
            "082-1814520",
            "0161.773766341",
            # Additional canonical non-+ formats
            "020 7946 0958",  # UK local
            "0911 1234567",  # DE local
        ],
    )
    def test_local_format_matched(self, value: str, patterns_by_name: dict[str, ContentPattern]) -> None:
        assert "international_phone_local" in patterns_by_name, (
            "Pattern 'international_phone_local' must be added to "
            "default_patterns.json for Sprint 7 international phone coverage."
        )
        pattern = patterns_by_name["international_phone_local"]
        assert _full_match(pattern.regex, value.strip()), (
            f"{value!r} not fully matched by international_phone_local regex {pattern.regex!r}"
        )


class TestExistingUsFormatsNotRegressed:
    """Sprint 2/5 US formats must still match their regex."""

    @pytest.mark.parametrize(
        "value",
        [
            "555-867-5309",
            "(555) 867-5309",
            "+1-555-867-5309",
            "5558675309",
            "555.867.5309",
        ],
    )
    def test_us_formats_still_matched(self, value: str, patterns_by_name: dict[str, ContentPattern]) -> None:
        us = patterns_by_name["us_phone_formatted"]
        intl = patterns_by_name["international_phone"]
        # Either the US regex or the intl regex should match it
        matched = _full_match(us.regex, value) or _full_match(intl.regex, value)
        assert matched, (
            f"Regression: {value!r} no longer matches us_phone_formatted "
            f"({us.regex!r}) or international_phone ({intl.regex!r})"
        )


class TestPhoneRegexPrecision:
    """Precision guards: non-phone digit strings must NOT match any phone regex."""

    @pytest.mark.parametrize(
        "value",
        [
            # Decimal numbers
            "3.14159",
            "0.5",
            "100.25",
            # IBAN (starts with letters)
            "DE89 3704 0044 0532 0130 00",
            # Date-like
            "2026-04-12",
            # Too short
            "12",
            "0",
            "00",
            # Credit card (16 digits, no + prefix, no trunk 0)
            "4111 1111 1111 1111",
        ],
    )
    def test_non_phone_rejected(self, value: str, patterns_by_name: dict[str, ContentPattern]) -> None:
        pattern_names = [
            "us_phone_formatted",
            "international_phone",
        ]
        # international_phone_local may or may not exist yet; include if present
        if "international_phone_local" in patterns_by_name:
            pattern_names.append("international_phone_local")
        for name in pattern_names:
            pattern = patterns_by_name[name]
            assert not _full_match(pattern.regex, value), (
                f"False positive: {value!r} fully matched by {name} regex {pattern.regex!r}"
            )


class TestAi4PrivacyCoverage:
    """End-to-end regex coverage on the Ai4Privacy PHONE sample corpus.

    Matches the Sprint 7 acceptance criterion: ``match_ratio >= 0.70``.
    A value counts as matched if ANY of the phone regexes covers
    at least 80% of the value.
    """

    def test_coverage_exceeds_70_percent(self, patterns_by_name: dict[str, ContentPattern]) -> None:
        import json
        from pathlib import Path

        fixture = Path(__file__).parent / "fixtures" / "corpora" / "ai4privacy_sample.json"
        data = json.loads(fixture.read_text())
        phones = [r["value"] for r in data if r.get("entity_type") == "PHONE"]
        assert len(phones) >= 1000, f"Expected at least 1000 PHONE rows in Ai4Privacy sample, got {len(phones)}"

        pattern_names = ["us_phone_formatted", "international_phone"]
        if "international_phone_local" in patterns_by_name:
            pattern_names.append("international_phone_local")
        compiled = [re2.compile(patterns_by_name[n].regex) for n in pattern_names]

        matched = 0
        for value in phones:
            stripped = value.strip()
            if not stripped:
                continue
            for regex in compiled:
                m = regex.search(stripped)
                if m and (m.end() - m.start()) / len(stripped) >= 0.80:
                    matched += 1
                    break

        match_ratio = matched / len(phones)
        assert match_ratio >= 0.70, (
            f"Ai4Privacy PHONE coverage {match_ratio:.1%} below 70% "
            f"target ({matched}/{len(phones)} matched). "
            f"Patterns tried: {pattern_names}"
        )
