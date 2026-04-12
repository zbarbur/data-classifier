"""Tests for DATE_OF_BIRTH_EU entity type (Sprint 6).

The EU variant separates DD/MM/YYYY format from the US-default MM/DD/YYYY.
The ``dob_european`` pattern in ``default_patterns.json`` now emits
``DATE_OF_BIRTH_EU`` instead of ``DATE_OF_BIRTH``. Ambiguous cases like
``04/03/1990`` (day=04 and month=03 — both valid under either interpretation)
match BOTH ``date_of_birth_format`` (US MM/DD) AND ``dob_european`` (EU DD/MM),
producing both entity types for downstream region-based disambiguation.

Non-ambiguous EU formats like ``15/03/1985`` (day=15 cannot be a month) match
only the EU pattern. Non-ambiguous US formats like ``03/15/1985`` match only
the US pattern.
"""

from __future__ import annotations

import pytest

from data_classifier import ColumnInput, classify_columns, load_profile


@pytest.fixture
def profile():
    return load_profile("standard")


def _entity_types(findings) -> set[str]:
    return {f.entity_type for f in findings}


class TestDateOfBirthEuUnambiguous:
    """Values where day > 12 — only valid as DD/MM, not MM/DD."""

    @pytest.mark.parametrize(
        "dob",
        [
            "15/03/1985",
            "31/12/1990",
            "25.06.1978",
            "13/01/2000",  # day=13, month=01 — unambiguously EU
        ],
    )
    def test_eu_only_format_detected(self, dob: str, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="geburtsdatum",
            sample_values=[dob, dob, dob],
        )
        findings = classify_columns([col], profile)
        types = _entity_types(findings)
        assert "DATE_OF_BIRTH_EU" in types


class TestDateOfBirthUsUnambiguous:
    """Values where the regex can only parse as US MM/DD (month > 12 is invalid;
    day > 12 in the middle position is invalid for EU)."""

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


class TestDateOfBirthAmbiguous:
    """Values where day <= 12 AND month <= 12 — valid under both interpretations.

    Both entity types should be reported so downstream region context can filter.
    Uses a NEUTRAL column name to exercise content-based regex matching in
    isolation. A DOB-hinting column name (``birth_date``, ``geburtsdatum``)
    would legitimately trigger Sprint 5 engine weighting and suppress the
    regex-side "other" entity type — which is correct behavior, just not
    what this test is measuring.
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
    def test_ambiguous_dates_match_both_entity_types(self, dob: str, profile) -> None:
        col = ColumnInput(
            column_id="c1",
            column_name="col_data",  # neutral — no column-name-engine bias
            sample_values=[dob, dob, dob],
        )
        findings = classify_columns([col], profile)
        types = _entity_types(findings)
        assert "DATE_OF_BIRTH" in types, f"ambiguous {dob} did not produce US finding: {types}"
        assert "DATE_OF_BIRTH_EU" in types, f"ambiguous {dob} did not produce EU finding: {types}"

    def test_column_name_bias_is_preserved(self, profile) -> None:
        """When the column name biases toward one interpretation, Sprint 5
        engine weighting correctly lets that win — suppressing the other
        regex-side finding. This is the same authority-gap logic that fixed
        Sprint 5 precision bugs, not a regression."""
        col = ColumnInput(
            column_id="c1",
            column_name="birth_date",  # biases toward DATE_OF_BIRTH via column_name engine
            sample_values=["04/03/1990", "05/06/1975"],
        )
        findings = classify_columns([col], profile)
        types = _entity_types(findings)
        assert "DATE_OF_BIRTH" in types
        assert "DATE_OF_BIRTH_EU" not in types  # suppressed by authority gap — working as designed


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
