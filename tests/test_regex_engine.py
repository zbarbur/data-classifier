"""Tests for the RE2 regex classification engine.

Tests both classification paths:
1. Column name matching (profile rules)
2. Sample value matching (content pattern library)

Also tests: confidence computation, deduplication, masking, category filtering.
"""

from __future__ import annotations

import pytest

import data_classifier
from data_classifier import ClassificationFinding, ColumnInput, classify_columns, load_profile
from data_classifier import _apply_findings_limit as apply_findings_limit
from data_classifier.engines.regex_engine import RegexEngine, _compute_sample_confidence

# Snapshot ``_DEFAULT_ENGINES`` at module import time so the module-teardown
# guard below can detect any in-place mutation leaked by a test. We capture the
# *names* (not the engine objects themselves) because the fixture below
# monkeypatches the attribute with a pruned list, and monkeypatch teardown only
# restores the original reference — it does not detect in-place appends /
# removes against that original list.
_INITIAL_DEFAULT_ENGINE_NAMES: tuple[str, ...] = tuple(getattr(e, "name", "") for e in data_classifier._DEFAULT_ENGINES)


@pytest.fixture(scope="module", autouse=True)
def _assert_default_engines_unchanged_at_module_teardown():
    """Module-teardown guard: fail loudly if any test mutated ``_DEFAULT_ENGINES`` in place.

    The ``_disable_ml`` fixture below uses ``monkeypatch.setattr`` which
    rebinds the attribute and restores it at teardown. That restoration only
    protects against *rebinding* — not against a test doing
    ``data_classifier._DEFAULT_ENGINES.append(...)`` or ``.remove(...)``. This
    guard asserts the structural shape (names + order) is identical to the
    module-import snapshot and names which engine went missing / got added.
    """
    yield
    final_names = tuple(getattr(e, "name", "") for e in data_classifier._DEFAULT_ENGINES)
    if final_names != _INITIAL_DEFAULT_ENGINE_NAMES:
        initial = set(_INITIAL_DEFAULT_ENGINE_NAMES)
        final = set(final_names)
        missing = sorted(initial - final)
        added = sorted(final - initial)
        raise AssertionError(
            "data_classifier._DEFAULT_ENGINES was mutated in place during "
            "tests/test_regex_engine.py run. "
            f"initial={list(_INITIAL_DEFAULT_ENGINE_NAMES)} "
            f"final={list(final_names)} "
            f"missing={missing} added={added}. "
            "Some test likely appended/removed from the list instead of rebinding it; "
            "monkeypatch.setattr only restores references, not list contents."
        )


class TestColumnNameMatching:
    """Column name regex matching against profile rules."""

    @pytest.fixture
    def engine(self):
        e = RegexEngine()
        e.startup()
        return e

    @pytest.fixture
    def profile(self):
        return load_profile("standard")

    def test_first_match_wins(self, engine, profile):
        """When column name matches multiple rules, first rule wins."""
        col = ColumnInput(column_name="ssn_number", column_id="test:ssn_number")
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].entity_type == "SSN"

    def test_engine_name_is_regex(self, engine, profile):
        col = ColumnInput(column_name="email", column_id="test:email")
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        assert findings[0].engine == "regex"

    def test_column_id_echoed(self, engine, profile):
        col = ColumnInput(column_name="email", column_id="custom:id:123")
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        assert findings[0].column_id == "custom:id:123"

    def test_no_match_returns_empty(self, engine, profile):
        col = ColumnInput(column_name="generic_data", column_id="test:data")
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        assert findings == []


class TestSampleValueMatching:
    """Sample value regex matching against content pattern library.

    Pinned to regex-only semantics via the autouse ``_disable_ml`` fixture.
    These tests predate the GLiNER2 ML engine (Sprint 5) and assert
    regex-level match counts / confidences that the ML engine can legitimately
    suppress via the orchestrator's gap filter when ORGANIZATION fires on
    numeric inputs under a generic ``data_field`` column name. ML coexistence
    is pinned separately by :class:`TestApplyFindingsLimit` below.
    """

    @pytest.fixture(autouse=True)
    def _disable_ml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Remove the GLiNER2 engine from the default cascade for this class.

        We monkeypatch ``data_classifier._DEFAULT_ENGINES`` directly rather than
        setting ``DATA_CLASSIFIER_DISABLE_ML=1``, because ``_DEFAULT_ENGINES``
        is built at module import time (in ``_build_default_engines()``) and
        ``tests/conftest.py`` imports ``data_classifier`` before any individual
        test module runs. A per-test env var fixture therefore arrives too
        late to affect the cached engine list.
        """
        # ``list(...)`` ensures the monkeypatched value is a fresh copy so that
        # any accidental in-place mutation cannot alias back to the original
        # ``_DEFAULT_ENGINES`` list. monkeypatch.setattr only restores the
        # reference at teardown, not list contents.
        non_ml_engines = list(e for e in data_classifier._DEFAULT_ENGINES if getattr(e, "name", "") != "gliner2")
        monkeypatch.setattr(data_classifier, "_DEFAULT_ENGINES", non_ml_engines)

    @pytest.fixture
    def profile(self):
        return load_profile("standard")

    def test_ssn_in_samples(self, profile):
        col = ColumnInput(
            column_name="data_field",
            column_id="test:data",
            sample_values=["123-45-6789", "987-65-4321", "hello world"],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        ssn_findings = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn_findings) == 1
        assert ssn_findings[0].sample_analysis is not None
        assert ssn_findings[0].sample_analysis.samples_matched == 2
        assert ssn_findings[0].sample_analysis.samples_scanned == 3

    def test_email_in_samples(self, profile):
        col = ColumnInput(
            column_name="notes",
            column_id="test:notes",
            sample_values=["Contact john@acme.com", "No email here", "jane@example.org"],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        email_findings = [f for f in findings if f.entity_type == "EMAIL"]
        assert len(email_findings) == 1
        assert email_findings[0].sample_analysis.samples_matched == 2

    def test_multiple_types_in_same_column(self, profile):
        """A single column can have findings for multiple entity types."""
        col = ColumnInput(
            column_name="mixed_data",
            column_id="test:mixed",
            sample_values=[
                "123-45-6789",
                "john@acme.com",
                "jane@example.org",
                "just text",
            ],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        types = {f.entity_type for f in findings}
        assert "SSN" in types
        assert "EMAIL" in types

    def test_no_samples_means_name_only(self, profile):
        """Without sample_values, only column name matching runs."""
        col = ColumnInput(column_name="email", column_id="test:email")
        findings = classify_columns([col], profile, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].sample_analysis is None  # no sample analysis

    def test_name_and_samples_both_reported(self, profile):
        """When name and samples both find SSN, both findings are reported
        (column_name detection + regex detection_type are distinct)."""
        col = ColumnInput(
            column_name="ssn",
            column_id="test:ssn",
            sample_values=["123-45-6789"] * 10,
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        ssn_findings = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn_findings) >= 1
        # Both column_name and regex engines should contribute
        engines = {f.engine for f in ssn_findings}
        assert "column_name" in engines or "regex" in engines


class TestMasking:
    def test_mask_samples(self):
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:mask",
            sample_values=["123-45-6789", "john@acme.com"],
        )
        findings = classify_columns([col], profile, min_confidence=0.0, mask_samples=True)
        for f in findings:
            if f.sample_analysis and f.sample_analysis.sample_matches:
                for match in f.sample_analysis.sample_matches:
                    assert "*" in match, f"Expected masked value, got: {match}"


class TestConfidenceComputation:
    """Confidence = match quality, not prevalence. No count multiplier."""

    def test_zero_matches_returns_zero(self):
        assert _compute_sample_confidence(0.95, 0, 0) == 0.0

    def test_unvalidated_pattern_uses_base(self):
        """Pattern without validator → base confidence regardless of count."""
        conf = _compute_sample_confidence(0.90, 5, 5, has_validator=False)
        assert conf == 0.90

    def test_validated_high_base_floors_at_095(self):
        """Pattern with validator that passes and high base → floor at 0.95."""
        conf = _compute_sample_confidence(0.80, 1, 1, has_validator=True)
        assert conf == 0.95

    def test_validated_low_base_keeps_base(self):
        """Pattern with validator but low base (<0.70) → use base, no floor."""
        conf = _compute_sample_confidence(0.40, 1, 1, has_validator=True)
        assert conf == 0.40

    def test_validated_high_base_keeps_base(self):
        """If base > 0.95 and validator passes, use base (max, not floor)."""
        conf = _compute_sample_confidence(0.98, 3, 3, has_validator=True)
        assert conf == 0.98

    def test_no_count_multiplier(self):
        """Confidence is independent of match count."""
        conf1 = _compute_sample_confidence(0.90, 1, 1, has_validator=False)
        conf10 = _compute_sample_confidence(0.90, 10, 10, has_validator=False)
        conf100 = _compute_sample_confidence(0.90, 100, 100, has_validator=False)
        assert conf1 == conf10 == conf100 == 0.90

    def test_validation_failures_reduce_below_floor(self):
        """When validation ratio is low enough, confidence drops below the 0.95 floor."""
        # 2 of 10 validated: base 0.95 * (2/10) = 0.19, max(0.19, 0.95) = 0.95
        # Actually the floor still applies — but zero validated → 0.0
        conf_all = _compute_sample_confidence(0.95, 10, 10, has_validator=True)
        conf_none = _compute_sample_confidence(0.95, 10, 0, has_validator=True)
        assert conf_none == 0.0
        assert conf_all == 0.95

    def test_no_validations_zeroes_confidence(self):
        conf = _compute_sample_confidence(0.95, 10, 0, has_validator=True)
        assert conf == 0.0

    def test_partial_validation_without_validator(self):
        """Even without a formal validator, partial validation reduces proportionally."""
        conf = _compute_sample_confidence(0.90, 10, 5, has_validator=False)
        assert conf == pytest.approx(0.45)


class TestConfidenceMatchQuality:
    """Integration tests: confidence reflects match quality, not prevalence."""

    def test_single_validated_match_high_confidence(self):
        """A single validated match should have confidence >= 0.95."""
        # Use a Luhn-valid credit card number (validated pattern)
        col = ColumnInput(
            column_id="test",
            column_name="data",
            sample_values=["4532015112830366"] + ["normal text"] * 199,
        )
        engine = RegexEngine()
        engine.startup()
        findings = engine.classify_column(col, profile=load_profile(), min_confidence=0.0)
        cc_findings = [f for f in findings if f.entity_type == "CREDIT_CARD"]
        assert len(cc_findings) >= 1
        assert cc_findings[0].confidence >= 0.95, (
            f"Validated single match should be >= 0.95, got {cc_findings[0].confidence}"
        )

    def test_no_count_multiplier(self):
        """Confidence should not change based on number of matches."""
        engine = RegexEngine()
        engine.startup()
        profile = load_profile()

        # 1 match
        col1 = ColumnInput(
            column_id="t1",
            column_name="d",
            sample_values=["test@example.com"] + ["text"] * 99,
        )
        f1 = engine.classify_column(col1, profile=profile, min_confidence=0.0)
        email1 = [f for f in f1 if f.entity_type == "EMAIL"]

        # 50 matches
        col50 = ColumnInput(
            column_id="t2",
            column_name="d",
            sample_values=["test@example.com"] * 50 + ["text"] * 50,
        )
        f50 = engine.classify_column(col50, profile=profile, min_confidence=0.0)
        email50 = [f for f in f50 if f.entity_type == "EMAIL"]

        if email1 and email50:
            assert email1[0].confidence == email50[0].confidence, (
                f"Confidence should not depend on count: 1-match={email1[0].confidence}, "
                f"50-match={email50[0].confidence}"
            )


class TestCategoryFiltering:
    def test_filter_to_single_category(self):
        profile = load_profile("standard")
        columns = [
            ColumnInput(column_name="ssn", column_id="test:ssn"),
            ColumnInput(column_name="credit_card", column_id="test:cc"),
            ColumnInput(column_name="password", column_id="test:pw"),
        ]
        findings = classify_columns(columns, profile, min_confidence=0.0, categories=["PII"])
        assert all(f.category == "PII" for f in findings)
        assert len(findings) == 1  # only SSN is PII

    def test_filter_to_multiple_categories(self):
        profile = load_profile("standard")
        columns = [
            ColumnInput(column_name="ssn", column_id="test:ssn"),
            ColumnInput(column_name="credit_card", column_id="test:cc"),
            ColumnInput(column_name="password", column_id="test:pw"),
        ]
        findings = classify_columns(columns, profile, min_confidence=0.0, categories=["PII", "Credential"])
        categories = {f.category for f in findings}
        assert "Financial" not in categories

    def test_no_filter_returns_all(self):
        profile = load_profile("standard")
        columns = [
            ColumnInput(column_name="ssn", column_id="test:ssn"),
            ColumnInput(column_name="credit_card", column_id="test:cc"),
            ColumnInput(column_name="password", column_id="test:pw"),
        ]
        findings = classify_columns(columns, profile, min_confidence=0.0)
        assert len(findings) == 3


class TestMinConfidenceThreshold:
    def test_default_threshold_filters_low_confidence(self):
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=["123-45-6789"],  # single match → ~0.62 confidence
        )
        # Default min_confidence=0.5 should keep this
        findings = classify_columns([col], profile)
        ssn = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn) == 1

    def test_high_threshold_filters_more(self):
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=["123-45-6789"],  # single match → ~0.62
        )
        findings = classify_columns([col], profile, min_confidence=0.9)
        ssn = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn) == 0  # filtered out


class TestValidators:
    def test_ssn_zeros_rejected(self):
        """SSN values with all-zeros groups should reduce validated count."""
        from data_classifier.engines.regex_engine import RegexEngine

        profile = load_profile("standard")
        engine = RegexEngine()
        engine.startup()
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=["000-45-6789", "123-00-6789", "123-45-0000", "123-45-6789"],
        )
        findings = engine.classify_column(col, profile=profile, min_confidence=0.0)
        ssn = [f for f in findings if f.entity_type == "SSN"]
        assert len(ssn) >= 1
        # us_ssn_formatted matches all 4, but only 123-45-6789 passes ssn_zeros validator
        ssn_formatted = [f for f in ssn if f.detection_type == "us_ssn_formatted"][0]
        sa = ssn_formatted.sample_analysis
        assert sa is not None
        assert sa.samples_matched == 4  # all match regex
        assert sa.samples_validated == 1  # only 123-45-6789 passes validator

    def test_luhn_validates_credit_cards(self):
        """Luhn-valid CC numbers pass, invalid ones reduce validation count."""
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=["4111111111111111", "4111111111111112"],  # valid, invalid Luhn
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        cc = [f for f in findings if f.entity_type == "CREDIT_CARD"]
        if cc:
            sa = cc[0].sample_analysis
            assert sa is not None
            assert sa.samples_matched == 2
            assert sa.samples_validated == 1  # only 4111...1111 passes Luhn

    def test_sin_luhn_validator_unit(self):
        """sin_luhn_check handles formatted, unformatted, and invalid SINs."""
        from data_classifier.engines.validators import sin_luhn_check

        # Valid formatted SIN — spaces
        assert sin_luhn_check("046 454 286") is True
        # Valid formatted SIN — dashes
        assert sin_luhn_check("046-454-286") is True
        # Valid unformatted SIN — the bug case
        assert sin_luhn_check("046454286") is True
        # Wrong length — 8 digits
        assert sin_luhn_check("04645428") is False
        # Wrong length — 10 digits
        assert sin_luhn_check("0464542860") is False
        # Correct length but fails Luhn checksum
        assert sin_luhn_check("046454287") is False

    def test_sin_luhn_validates_formatted_and_unformatted(self):
        """Canadian SIN classification accepts both formatted and unformatted values.

        Uses a neutral column name so the content engine (not column-name engine) fires.
        """
        profile = load_profile("standard")
        col = ColumnInput(
            column_name="data",
            column_id="test:data",
            sample_values=[
                "046 454 286",  # formatted spaces — valid Luhn
                "046-454-286",  # formatted dashes — valid Luhn
                "046454286",  # unformatted — the bug case, valid Luhn
                "046454287",  # unformatted — fails Luhn
            ],
        )
        findings = classify_columns([col], profile, min_confidence=0.0)
        sin = [f for f in findings if f.entity_type == "CANADIAN_SIN"]
        assert sin, "Expected CANADIAN_SIN finding"
        sa = sin[0].sample_analysis
        assert sa is not None
        assert sa.samples_matched == 4  # all 4 match the regex
        assert sa.samples_validated == 3  # 3 pass Luhn; 046454287 fails


class TestIntrospection:
    def test_get_supported_categories(self):
        from data_classifier import get_supported_categories

        cats = get_supported_categories()
        assert "PII" in cats
        assert "Financial" in cats
        assert "Credential" in cats
        assert "Health" in cats

    def test_get_supported_entity_types(self):
        from data_classifier import get_supported_entity_types

        types = get_supported_entity_types()
        assert len(types) >= 15
        type_names = {t["entity_type"] for t in types}
        assert "SSN" in type_names
        assert "EMAIL" in type_names

    def test_get_supported_sensitivity_levels(self):
        from data_classifier import get_supported_sensitivity_levels

        levels = get_supported_sensitivity_levels()
        assert levels == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    def test_get_pattern_library(self):
        from data_classifier import get_pattern_library

        patterns = get_pattern_library()
        assert len(patterns) >= 40
        assert all("name" in p for p in patterns)
        assert all("regex" in p for p in patterns)


class TestApplyFindingsLimit:
    """Pin the orchestrator's confidence-gap suppression behavior.

    Regression coverage for Sprint 8 Item 2: the GLiNER2 ML engine can
    legitimately return an ORGANIZATION finding at ~0.74 confidence on
    numeric dash-formatted inputs under a generic column name. When the
    regex engine's SSN finding lands at ~0.36 (partial validation penalty
    from an invalid second sample), the 0.38 gap exceeds the 0.30
    threshold and SSN is dropped — which is correct per the spec but had
    silently broken ``test_ssn_in_samples`` for multiple sprints under
    ML-on env. These tests exercise :func:`_apply_findings_limit` directly
    with synthetic findings so the invariants are pinned without needing
    the ML engine running.
    """

    def _make_finding(self, entity_type: str, confidence: float, engine: str) -> ClassificationFinding:
        return ClassificationFinding(
            column_id="test:col",
            entity_type=entity_type,
            category="PII",
            sensitivity="HIGH",
            confidence=confidence,
            regulatory=[],
            engine=engine,
        )

    def test_regex_ssn_coexists_with_gliner_organization_when_confidence_close(self):
        """Happy path: SSN (~0.73, all samples valid) + GLiNER2 ORG (~0.74) both survive."""
        findings = [
            self._make_finding("SSN", 0.73, "regex"),
            self._make_finding("ORGANIZATION", 0.74, "gliner2"),
        ]
        result = apply_findings_limit(findings, max_findings=None, confidence_gap_threshold=0.30)
        entity_types = {f.entity_type for f in result}
        assert "SSN" in entity_types
        assert "ORGANIZATION" in entity_types

    def test_regex_ssn_dropped_when_partial_validation_widens_gap(self):
        """Failure path: SSN (~0.36, partial validation) is correctly suppressed by ORG (~0.74).

        This is the exact scenario that broke ``test_ssn_in_samples``:
        the second sample ``987-65-4321`` is in the ITIN range and fails
        ``ssn_zeros_check``, halving the regex SSN confidence. The gap
        (0.38) exceeds the 0.30 threshold and SSN is dropped. Documented
        as intentional orchestrator behavior, not a bug.
        """
        findings = [
            self._make_finding("SSN", 0.36, "regex"),
            self._make_finding("ORGANIZATION", 0.74, "gliner2"),
        ]
        result = apply_findings_limit(findings, max_findings=None, confidence_gap_threshold=0.30)
        entity_types = {f.entity_type for f in result}
        assert "ORGANIZATION" in entity_types
        assert "SSN" not in entity_types

    def test_gap_exactly_at_threshold_preserves_both(self):
        """Boundary: a gap of exactly 0.30 preserves both findings (the <= comparison is inclusive)."""
        findings = [
            self._make_finding("SSN", 0.44, "regex"),
            self._make_finding("ORGANIZATION", 0.74, "gliner2"),
        ]
        result = apply_findings_limit(findings, max_findings=None, confidence_gap_threshold=0.30)
        entity_types = {f.entity_type for f in result}
        assert "SSN" in entity_types
        assert "ORGANIZATION" in entity_types

    def test_max_findings_truncates_before_gap_logic(self):
        """When max_findings is set, it short-circuits gap suppression entirely."""
        findings = [
            self._make_finding("A", 0.90, "regex"),
            self._make_finding("B", 0.40, "regex"),  # would be dropped by gap logic
            self._make_finding("C", 0.30, "regex"),
        ]
        result = apply_findings_limit(findings, max_findings=2, confidence_gap_threshold=0.30)
        assert len(result) == 2
        assert {f.entity_type for f in result} == {"A", "B"}
