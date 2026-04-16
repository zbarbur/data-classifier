"""Tests for the Sprint 11 family taxonomy and the
``ClassificationFinding.family`` auto-population invariant.

Covers:
* The taxonomy module's coverage and stable vocabulary.
* ``family_for`` dispatch: known types map correctly, unknown types
  fall back to singleton, empty inputs map to empty output.
* ``ClassificationFinding.__post_init__`` auto-populates ``family``
  from ``entity_type`` when it is left empty at construction time.
* Explicit ``family`` argument survives ``__post_init__`` untouched.
* Every entity_type declared in the standard profile has a family
  mapping (no silent singletons in shipped data).
"""

from __future__ import annotations

import pytest

from data_classifier import (
    ENTITY_TYPE_TO_FAMILY,
    FAMILIES,
    ClassificationFinding,
    ColumnInput,
    classify_columns,
    family_for,
    load_profile,
)


class TestFamilyForDispatch:
    def test_known_entity_type_maps_to_family(self):
        assert family_for("EMAIL") == "CONTACT"
        assert family_for("CREDIT_CARD") == "PAYMENT_CARD"
        assert family_for("IBAN") == "FINANCIAL"
        assert family_for("API_KEY") == "CREDENTIAL"
        assert family_for("SSN") == "GOVERNMENT_ID"
        assert family_for("DATE_OF_BIRTH") == "DATE"
        # Compatibility alias for meta-classifier v3 shadow predictions
        # (see data_classifier/core/taxonomy.py). Removed in Sprint 13
        # v4 retrain.
        assert family_for("DATE_OF_BIRTH_EU") == "DATE"

    def test_empty_and_none_map_to_empty(self):
        # Callers need to distinguish "no prediction" from "unknown
        # subtype" — both falsy inputs collapse to empty string.
        assert family_for("") == ""
        assert family_for(None) == ""

    def test_unknown_type_falls_back_to_singleton(self, caplog: pytest.LogCaptureFixture):
        with caplog.at_level("WARNING"):
            result = family_for("NOT_A_REAL_TYPE_ZZZ")
        assert result == "NOT_A_REAL_TYPE_ZZZ"
        assert any("no family mapping" in rec.message for rec in caplog.records)


class TestFamilyVocabulary:
    def test_families_tuple_is_sorted_and_unique(self):
        assert list(FAMILIES) == sorted(set(FAMILIES))

    def test_every_family_in_tuple_has_at_least_one_subtype(self):
        # Each declared family must have at least one entity_type
        # pointing at it, otherwise the family is vestigial.
        mapped = set(ENTITY_TYPE_TO_FAMILY.values())
        missing = set(FAMILIES) - mapped
        assert not missing, f"Families declared but not used: {missing}"

    def test_every_mapped_family_is_declared(self):
        # The reverse — every family that appears in the mapping
        # must also be listed in FAMILIES so reporting is stable.
        mapped = set(ENTITY_TYPE_TO_FAMILY.values())
        undeclared = mapped - set(FAMILIES)
        assert not undeclared, f"Families used but not declared in FAMILIES: {undeclared}"


class TestFindingAutoPopulate:
    def _make_finding(self, *, entity_type: str, family: str = "") -> ClassificationFinding:
        return ClassificationFinding(
            column_id="col_test",
            entity_type=entity_type,
            category="PII",
            sensitivity="HIGH",
            confidence=0.9,
            regulatory=[],
            engine="test",
            family=family,
        )

    def test_family_auto_populated_from_entity_type(self):
        # Construct without family — __post_init__ fills it.
        finding = self._make_finding(entity_type="EMAIL")
        assert finding.family == "CONTACT"

    def test_family_auto_populated_for_all_known_types(self):
        # Every entity type in the taxonomy map must auto-populate
        # correctly when findings are constructed via the normal API.
        for entity_type, expected_family in ENTITY_TYPE_TO_FAMILY.items():
            finding = self._make_finding(entity_type=entity_type)
            assert finding.family == expected_family, (
                f"Expected family={expected_family} for {entity_type}, got {finding.family}"
            )

    def test_explicit_family_arg_survives_post_init(self):
        # Callers who want to override the family (e.g. a test that
        # exercises an invalid family value) can still pass it
        # explicitly and __post_init__ must not clobber it.
        finding = self._make_finding(entity_type="EMAIL", family="OVERRIDE")
        assert finding.family == "OVERRIDE"

    def test_unknown_entity_type_falls_back_to_singleton(self):
        finding = self._make_finding(entity_type="NOT_A_REAL_TYPE_ZZZ")
        assert finding.family == "NOT_A_REAL_TYPE_ZZZ"

    def test_empty_entity_type_leaves_family_empty(self):
        finding = self._make_finding(entity_type="")
        assert finding.family == ""


class TestProfileCoverage:
    def test_every_profile_entity_type_has_a_family(self):
        # Every entity type declared in standard.yaml must be
        # covered by the family taxonomy. This guards against the
        # common "added a new pattern but forgot to update the
        # taxonomy" regression.
        profile = load_profile("standard")
        profile_types = {rule.entity_type for rule in profile.rules}

        missing = profile_types - set(ENTITY_TYPE_TO_FAMILY.keys())
        assert not missing, (
            f"Profile entity types without a family mapping: {sorted(missing)}. "
            f"Update data_classifier/core/taxonomy.py::ENTITY_TYPE_TO_FAMILY."
        )


class TestEndToEndFamilyOnFinding:
    """Family field is populated on findings returned from the public API.

    The unit tests above exercise ``__post_init__`` directly on synthetic
    findings. This class closes the gap caught by the upstream
    ``855f60c`` review: anything reachable through ``classify_columns``
    must also have an end-to-end test, so a future refactor that bypasses
    ``__post_init__`` (e.g. ``dataclass(field(init=False))``) cannot
    silently strip the field.
    """

    @pytest.fixture(scope="class")
    def profile(self):
        return load_profile("standard")

    @pytest.mark.parametrize(
        ("column_name", "sample_values", "expected_family"),
        [
            ("email_address", ["alice@example.com", "bob@example.org"], "CONTACT"),
            ("credit_card", ["4111111111111111", "5500000000000004"], "PAYMENT_CARD"),
        ],
    )
    def test_classify_columns_populates_family(self, profile, column_name, sample_values, expected_family):
        findings = classify_columns(
            [ColumnInput(column_name=column_name, sample_values=sample_values)],
            profile,
            min_confidence=0.0,
        )
        assert findings, f"expected at least one finding for {column_name}"
        # Every finding (not just the top one) must carry a non-empty
        # family that matches the expected family for its entity_type.
        for f in findings:
            assert f.family, f"family unset on finding {f.entity_type!r}"
            assert f.family == family_for(f.entity_type)
        assert any(f.family == expected_family for f in findings), (
            f"no finding landed in expected family {expected_family}; "
            f"got {[(f.entity_type, f.family) for f in findings]}"
        )
