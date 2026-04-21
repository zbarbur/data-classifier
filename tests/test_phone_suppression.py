"""Tests for directional PHONE suppression on numeric-format PII columns.

Sprint 14: DATE_OF_BIRTH and CREDIT_CARD values (digit-heavy with separators)
spuriously match PHONE regex, inflating n_cascade_entities to 2 and causing
the column-shape router to misroute them to opaque_tokens instead of
structured_single. The fix adds directional PHONE suppression: when
DATE_OF_BIRTH or CREDIT_CARD co-occurs with PHONE, PHONE is always
suppressed (it's always the false positive on these formats).
"""

from data_classifier import ColumnInput, classify_columns
from data_classifier.orchestrator.shape_detector import detect_column_shape


def test_dob_column_routes_to_structured_single(standard_profile):
    """DATE_OF_BIRTH column must not be misrouted to opaque_tokens via spurious PHONE."""
    col = ColumnInput(
        column_name="info",
        column_id="numeric_pii:dob",
        sample_values=[
            "1985-03-15",
            "1990-07-22",
            "1978-11-03",
            "2001-01-30",
            "1965-06-18",
            "1993-09-07",
            "1972-12-25",
            "1988-04-12",
            "2000-02-29",
            "1955-08-14",
            "1998-10-05",
            "1983-05-21",
            "1970-03-09",
            "1995-07-16",
            "1962-11-28",
        ],
    )
    findings = classify_columns([col], standard_profile, min_confidence=0.0)

    # PHONE must be suppressed
    entity_types = {f.entity_type for f in findings}
    assert "PHONE" not in entity_types, f"PHONE should be suppressed, got {entity_types}"
    assert "DATE" in entity_types or "DATE_OF_BIRTH" in entity_types, (
        f"DATE or DATE_OF_BIRTH expected, got {entity_types}"
    )

    # Must route to structured_single (not opaque_tokens)
    shape = detect_column_shape(col, findings)
    assert shape.shape == "structured_single", (
        f"Expected structured_single, got {shape.shape} (n_cascade={shape.n_cascade_entities})"
    )


def test_credit_card_column_routes_to_structured_single(standard_profile):
    """CREDIT_CARD column must not be misrouted to opaque_tokens via spurious PHONE."""
    col = ColumnInput(
        column_name="col1",
        column_id="numeric_pii:cc",
        sample_values=[
            "4111-1111-1111-1111",
            "4222-2222-2222-2222",
            "4012-8888-8888-1881",
            "4532-0150-0298-4543",
            "4716-6388-5468-9005",
            "5100-0000-0000-0008",
            "5112-3456-7890-1234",
            "5200-8282-8282-8210",
            "5399-9999-9999-9999",
            "5425-2334-3010-9903",
            "4539-5781-2345-6789",
            "4556-7375-8689-9855",
            "4916-3388-1234-5678",
            "4024-0071-0902-2766",
            "4485-9836-5217-3456",
        ],
    )
    findings = classify_columns([col], standard_profile, min_confidence=0.0)

    entity_types = {f.entity_type for f in findings}
    assert "PHONE" not in entity_types, f"PHONE should be suppressed, got {entity_types}"
    assert "CREDIT_CARD" in entity_types, f"CREDIT_CARD expected, got {entity_types}"

    shape = detect_column_shape(col, findings)
    assert shape.shape == "structured_single", (
        f"Expected structured_single, got {shape.shape} (n_cascade={shape.n_cascade_entities})"
    )


def test_real_phone_column_not_suppressed(standard_profile):
    """Actual phone number columns must NOT have PHONE suppressed."""
    col = ColumnInput(
        column_name="data",
        column_id="numeric_pii:real_phone",
        sample_values=[
            "(212) 555-0101",
            "(312) 555-0202",
            "(415) 555-0303",
            "(617) 555-0404",
            "(713) 555-0505",
            "(202) 555-0606",
            "(310) 555-0707",
            "(404) 555-0808",
            "(503) 555-0909",
            "(702) 555-1010",
        ],
    )
    findings = classify_columns([col], standard_profile, min_confidence=0.0)

    entity_types = {f.entity_type for f in findings}
    assert "PHONE" in entity_types, f"PHONE should be present for real phone data, got {entity_types}"

    shape = detect_column_shape(col, findings)
    assert shape.shape == "structured_single"


def test_phone_not_suppressed_without_winner(standard_profile):
    """PHONE should not be suppressed when no winning entity co-occurs."""
    col = ColumnInput(
        column_name="contact",
        column_id="numeric_pii:phone_only",
        sample_values=[
            "+1-555-123-4567",
            "+44 20 7946 0958",
            "+1 (415) 555-0199",
            "+1-555-987-6543",
            "+1 (212) 555-0100",
        ],
    )
    findings = classify_columns([col], standard_profile, min_confidence=0.0)
    entity_types = {f.entity_type for f in findings}
    assert "PHONE" in entity_types


def test_npi_phone_collision_still_works(standard_profile):
    """The existing NPI-PHONE symmetric collision pair must still function."""
    from data_classifier.core.types import ClassificationFinding
    from data_classifier.orchestrator.orchestrator import Orchestrator

    orchestrator = Orchestrator.__new__(Orchestrator)

    # Simulate NPI + PHONE with big gap (should suppress via symmetric pair)
    findings = {
        "NPI": ClassificationFinding(
            column_id="test",
            entity_type="NPI",
            category="HEALTHCARE",
            sensitivity="high",
            confidence=0.90,
            regulatory=[],
            engine="regex",
            evidence="test",
        ),
        "PHONE": ClassificationFinding(
            column_id="test",
            entity_type="PHONE",
            category="PII",
            sensitivity="medium",
            confidence=0.60,
            regulatory=[],
            engine="regex",
            evidence="test",
        ),
    }
    result = orchestrator._resolve_collisions(findings)
    # NPI should win with gap 0.30 > 0.15
    assert "NPI" in result
    assert "PHONE" not in result
