"""Tests for EU-format date-of-birth classification (Sprint 12 retirement).

The Sprint 6 ``DATE_OF_BIRTH_EU`` subtype was retired in Sprint 12 after the
Sprint 11 Phase 10 family A/B analysis showed the split was a classification
mistake: format does not indicate jurisdiction, the distinction is
unresolvable for ambiguous day<=12 cases, and GDPR / CCPA / HIPAA treat
dates of birth as PII regardless of format. See
``docs/research/meta_classifier/sprint11_family_ab_result.md`` for the full
reasoning and ``backlog/sprint12-retire-date-of-birth-eu-subtype.yaml`` for
the taxonomy-cleanup spec.

These tests pin the post-retirement behaviour:

* Unambiguous EU-format strings (e.g. ``15/03/1985``) must still classify
  as ``DATE_OF_BIRTH`` via the ``dob_european`` regex. The pattern
  survives; only the emitted ``entity_type`` label changes.
* Unambiguous US-format strings still classify as ``DATE_OF_BIRTH`` via
  the legacy ``date_of_birth_format`` regex.
* Ambiguous values (day<=12, month<=12) classify as ``DATE_OF_BIRTH``
  without producing any ``DATE_OF_BIRTH_EU`` finding — the whole point
  of the retirement is that we no longer try to report both subtypes.
* Invalid dates still reject cleanly.
* ``DATE_OF_BIRTH_EU`` is absent from the ``standard.yaml`` profile,
  from every pattern's emitted ``entity_type``, and from the taxonomy
  map ``ENTITY_TYPE_TO_FAMILY``. The compatibility alias was removed
  in Sprint 14 after the v6 meta-classifier retrain.
"""

from __future__ import annotations

import pytest

from data_classifier import ColumnInput, classify_columns, load_profile
from data_classifier.core.taxonomy import ENTITY_TYPE_TO_FAMILY


@pytest.fixture
def profile():
    return load_profile("standard")


def _entity_types(findings) -> set[str]:
    return {f.entity_type for f in findings}


class TestDateOfBirthEuFormatClassifiesAsDateOfBirth:
    """EU-format DOBs (DD/MM/YYYY, DD.MM.YYYY) collapse to DATE_OF_BIRTH."""

    @pytest.mark.parametrize(
        "dob",
        [
            "15/03/1985",
            "31/12/1990",
            "25.06.1978",
            "13/01/2000",  # day=13, unambiguously EU-format
        ],
    )
    def test_eu_only_format_classifies_as_date_of_birth(self, dob: str, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="geburtsdatum",
            sample_values=[dob, dob, dob],
        )
        findings = classify_columns([col], profile)
        types = _entity_types(findings)
        assert "DATE_OF_BIRTH" in types
        # Regression guard: the retired subtype must not come back.
        assert "DATE_OF_BIRTH_EU" not in types


class TestDateOfBirthUsUnambiguous:
    """US-format DOBs (MM/DD/YYYY) classify as DATE_OF_BIRTH — unchanged by retirement."""

    @pytest.mark.parametrize(
        "dob",
        [
            "03/15/1985",
            "12-25-2000",
            "07/31/1995",
        ],
    )
    def test_us_only_format_detected(self, dob: str, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="dob",
            sample_values=[dob, dob, dob],
        )
        findings = classify_columns([col], profile)
        types = _entity_types(findings)
        assert "DATE_OF_BIRTH" in types
        assert "DATE_OF_BIRTH_EU" not in types


class TestDateOfBirthAmbiguous:
    """Ambiguous day<=12 + month<=12 values resolve to a single DATE_OF_BIRTH finding.

    Before Sprint 12 these would emit both ``DATE_OF_BIRTH`` and
    ``DATE_OF_BIRTH_EU`` for downstream jurisdiction-aware disambiguation.
    After the retirement there is no second subtype to emit — the pipeline
    reports ``DATE_OF_BIRTH`` once, which is correct because format does
    not identify jurisdiction and the sensitivity / regulatory scope is
    identical regardless.
    """

    @pytest.mark.parametrize(
        "dob",
        [
            "04/03/1990",
            "01/12/1985",
            "12/01/2000",
            "05/06/1975",
        ],
    )
    def test_ambiguous_dates_land_in_date_of_birth(self, dob: str, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="col_data",  # neutral — no column-name-engine bias
            sample_values=[dob, dob, dob],
        )
        findings = classify_columns([col], profile)
        types = _entity_types(findings)
        assert "DATE_OF_BIRTH" in types, f"ambiguous {dob} did not produce DATE_OF_BIRTH: {types}"
        assert "DATE_OF_BIRTH_EU" not in types, f"retired subtype leaked for {dob}: {types}"


class TestDateOfBirthInvalid:
    """Clearly-invalid dates should not match either pattern."""

    @pytest.mark.parametrize(
        "bad",
        [
            "32/13/2000",  # day 32, month 13 — invalid under both
            "00/00/0000",  # all zeros
            "not a date",
        ],
    )
    def test_invalid_dates_rejected(self, bad: str, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="col",
            sample_values=[bad, bad, bad],
        )
        findings = classify_columns([col], profile)
        types = _entity_types(findings)
        assert "DATE_OF_BIRTH" not in types
        assert "DATE_OF_BIRTH_EU" not in types


class TestDateOfBirthEuRetiredFromTaxonomy:
    """Pin that the Sprint 12 retirement + Sprint 14 v6 retrain fully
    removed ``DATE_OF_BIRTH_EU`` from the taxonomy — no compatibility
    alias, no one-hot slot, no class label.
    """

    def test_family_map_has_no_date_of_birth_eu(self) -> None:
        """Sprint 14 cleanup: DOB_EU alias removed after v6 retrain."""
        assert "DATE_OF_BIRTH_EU" not in ENTITY_TYPE_TO_FAMILY

    def test_date_of_birth_still_in_date_family(self) -> None:
        assert ENTITY_TYPE_TO_FAMILY["DATE_OF_BIRTH"] == "DATE"

    def test_standard_profile_has_no_date_of_birth_eu_rule(self) -> None:
        """The emission path is fully retired — ``standard.yaml`` has
        no rule that produces ``DATE_OF_BIRTH_EU`` findings.
        """
        profile = load_profile("standard")
        entity_types = {rule.entity_type for rule in profile.rules}
        assert "DATE_OF_BIRTH_EU" not in entity_types
        assert "DATE_OF_BIRTH" in entity_types
