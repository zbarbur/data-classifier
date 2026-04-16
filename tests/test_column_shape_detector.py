import pytest

from data_classifier.core.types import ClassificationFinding, ColumnInput
from tests.benchmarks.meta_classifier.sprint12_safety_audit import (
    _build_heterogeneous_fixtures,
)


def _finding(entity_type: str) -> ClassificationFinding:
    return ClassificationFinding(
        column_id="col_1",
        entity_type=entity_type,
        category="PII",
        sensitivity="medium",
        confidence=0.9,
        regulatory=[],
        engine="regex",
        evidence="test",
    )


def test_structured_single_short_values_one_entity():
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(
        column_id="col_1",
        column_name="email",
        sample_values=["alice@ex.com", "bob@ex.org", "carol@site.co"] * 4,
    )
    result = detect_column_shape(column, [_finding("EMAIL")])
    assert result.shape == "structured_single"
    assert result.avg_len_normalized < 0.3
    assert result.n_cascade_entities == 1
    assert result.column_name_hint_applied is False


def test_free_text_heterogeneous_long_values_many_entities():
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    log_line = "2026-04-16T10:15:30 INFO user alice@example.com login from 10.0.1.5"
    column = ColumnInput(
        column_id="col_1",
        column_name="log_line",
        sample_values=[log_line] * 10,
    )
    result = detect_column_shape(column, [_finding("EMAIL"), _finding("IP_ADDRESS"), _finding("DATE_TIME")])
    assert result.shape == "free_text_heterogeneous"
    assert result.avg_len_normalized >= 0.3
    assert result.dict_word_ratio >= 0.1


def test_opaque_tokens_no_dictionary_words():
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(
        column_id="col_1",
        column_name="jwt_token",
        sample_values=[
            "eyJ1c2VyIjoiYWxpY2VAZXhhbXBsZS5jb20iLCJyb2xlIjoiYWRtaW4ifQ==",
            "eyJ1c2VyIjoiYm9iQGV4YW1wbGUub3JnIiwicm9sZSI6InVzZXIifQ==",
        ]
        * 5,
    )
    result = detect_column_shape(column, [])
    assert result.shape == "opaque_tokens"
    assert result.dict_word_ratio < 0.1


def test_empty_sample_values_defaults_to_structured_single():
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(column_id="col_1", column_name="unknown", sample_values=[])
    result = detect_column_shape(column, [])
    assert result.shape == "structured_single"
    assert result.avg_len_normalized == 0.0


def test_short_values_multiple_entities_routes_to_opaque():
    """Regression test: structured_single requires BOTH short values AND <= 1 entity.
    When the cascade finds multiple entities on short values, the column must fall
    through the structured check and land in opaque_tokens (assuming low dict_word_ratio).
    """
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(
        column_id="col_1",
        column_name="token",
        sample_values=["a1b2c3d4", "e5f6g7h8", "i9j0k1l2"] * 4,
    )
    result = detect_column_shape(column, [_finding("EMAIL"), _finding("PHONE")])
    assert result.avg_len_normalized < 0.3
    assert result.n_cascade_entities == 2
    assert result.dict_word_ratio < 0.1
    assert result.shape == "opaque_tokens"


def test_long_values_zero_entities_opaque_tokens():
    """Regression test: long values with no cascade entities still route correctly.
    Covers the case where a base64-like column has no regex matches but its values
    are long. Must land in opaque_tokens, not structured_single.
    """
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(
        column_id="col_1",
        column_name="hash",
        sample_values=["a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0" * 2] * 10,
    )
    result = detect_column_shape(column, [])
    assert result.avg_len_normalized >= 0.3
    assert result.n_cascade_entities == 0
    assert result.dict_word_ratio < 0.1
    assert result.shape == "opaque_tokens"


# ── Column-name tiebreaker tests (Sprint 13 scoping Q1 decision) ──────────
# Fixture construction: 1 value with 'error' (dict word) + 19 filler values
# of ~32 chars produce avg_len_norm ≈ 0.32 and dict_word_ratio = 0.05 —
# both inside the middle band ([0.3, 0.45] × [0.05, 0.15]).
_TIEBREAKER_FILLER = [f"xkqzmpfw_{i:04d}_jnrt_vbcd_xyz_end_" for i in range(19)]
_TIEBREAKER_WITH_DICT_WORD = ["error_0001_xkqzmpfw_jnrt_vbcd_xyz"] + _TIEBREAKER_FILLER


def test_ambiguous_middle_band_column_name_points_to_hetero():
    """Column name 'log_line' should tip an ambiguous signal toward heterogeneous."""
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(
        column_id="col_1",
        column_name="log_line",  # known heterogeneous hint
        sample_values=_TIEBREAKER_WITH_DICT_WORD,
    )
    result = detect_column_shape(column, [])
    assert 0.3 <= result.avg_len_normalized <= 0.45
    assert 0.05 <= result.dict_word_ratio <= 0.15
    assert result.shape == "free_text_heterogeneous"
    assert result.column_name_hint_applied is True


def test_ambiguous_middle_band_column_name_points_to_structured():
    """Column name 'email' should tip an ambiguous signal toward structured_single."""
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(
        column_id="col_1",
        column_name="email",  # known structured hint
        sample_values=_TIEBREAKER_WITH_DICT_WORD,
    )
    result = detect_column_shape(column, [])
    assert 0.3 <= result.avg_len_normalized <= 0.45
    assert 0.05 <= result.dict_word_ratio <= 0.15
    assert result.shape == "structured_single"
    assert result.column_name_hint_applied is True


def test_unambiguous_signal_ignores_column_name_hint():
    """Even 'log_line' column name should not override strong structured signals."""
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(
        column_id="col_1",
        column_name="log_line",  # misleading column name
        sample_values=["alice@ex.com", "bob@ex.org"] * 5,  # strong structured signal
    )
    result = detect_column_shape(column, [_finding("EMAIL")])
    assert result.shape == "structured_single"
    assert result.column_name_hint_applied is False  # content decisive — hint didn't fire


def test_tiebreaker_does_not_override_content_authoritative_heterogeneous():
    """Content router decisively picks free_text_heterogeneous at dict_ratio >= 0.1;
    the tiebreaker must NOT override that even with a 'structured' hint like 'email'.
    Regression guard for the Task 4 middle-band overlap fix.
    """
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    # Build a fixture that lands around dict_ratio ≈ 0.12 (clearly above the 0.1
    # content-authoritative threshold) with avg_len_norm in the former middle-band
    # range. A mix of dictionary-word-containing values and random-looking ones.
    values = ["data point for user record " + "x" * 20 for _ in range(3)]
    values += ["token_" + "x" * 30 for _ in range(22)]
    column = ColumnInput(
        column_id="col_1",
        column_name="email",  # structured hint — must NOT override
        sample_values=values,
    )
    result = detect_column_shape(column, [])
    assert result.dict_word_ratio >= 0.1  # content-authoritative zone
    assert result.shape == "free_text_heterogeneous"
    assert result.column_name_hint_applied is False


def test_structured_tiebreaker_requires_n_cascade_le_1():
    """If the tiebreaker fires toward 'structured', it must also honor the
    n_cascade <= 1 guard that the content router's structured_single requires.
    A middle-band column with a structured name but 2+ cascade entities must NOT
    be misrouted to structured_single.
    """
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    # Middle-band fixture: long-ish values with some dictionary words to
    # land in [0.3, 0.45] × [0.05, <0.1]. Reuse the same base as the
    # existing tiebreaker tests but with exactly one dict-word value.
    values = ["error_0001_xkqzmpfw_jnrt_vbcd_xyz"] + [f"xkqzmpfw_{i:04d}_jnrt_vbcd_xyz_end_" for i in range(19)]
    column = ColumnInput(
        column_id="col_1",
        column_name="email",  # structured hint
        sample_values=values,
    )
    # Two cascade entities — structured_single shouldn't apply
    result = detect_column_shape(column, [_finding("EMAIL"), _finding("PHONE")])
    assert result.n_cascade_entities == 2
    # Tiebreaker's structured branch refused to fire → shape is whatever content decided
    # (opaque_tokens per the else branch), NOT structured_single
    assert result.shape != "structured_single"
    assert result.column_name_hint_applied is False


# ── Sprint 13 Item A acceptance-criteria fixtures ──────────────────────────
# Test suite covering all 3 shapes: 6 heterogeneous from the Sprint 12
# safety audit (the exact fixtures that made Q3 verdict RED), plus
# 4 homogeneous structured, plus 2 opaque-token shapes.


@pytest.mark.parametrize(
    "fixture_name,expected_shape",
    [
        # Heterogeneous fixtures from Sprint 12 safety audit §3:
        ("original_q3_log", "free_text_heterogeneous"),
        ("apache_access_log", "free_text_heterogeneous"),
        ("json_event_log", "free_text_heterogeneous"),
        ("support_chat_messages", "free_text_heterogeneous"),
        ("kafka_event_stream", "free_text_heterogeneous"),
    ],
)
def test_q3_heterogeneous_fixtures_route_away_from_structured(fixture_name: str, expected_shape: str) -> None:
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    fixtures = _build_heterogeneous_fixtures()
    samples = fixtures[fixture_name]
    column = ColumnInput(
        column_id=fixture_name,
        column_name=fixture_name,
        sample_values=samples,
    )
    # For this integration-lite test we pass an empty findings list —
    # the content signals (avg_len + dict_word_ratio) alone must
    # correctly classify heterogeneous shapes away from structured_single.
    # When the full orchestrator path runs, post-merge findings will be
    # passed; the test here verifies the detector's robustness under
    # the worst case (no cascade signal).
    result = detect_column_shape(column, [])
    assert result.shape == expected_shape, (
        f"{fixture_name}: expected {expected_shape}, got {result.shape} "
        f"(avg_len={result.avg_len_normalized:.3f}, "
        f"dict_word={result.dict_word_ratio:.3f})"
    )


def test_q3_base64_fixture_routes_to_opaque_tokens() -> None:
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    fixtures = _build_heterogeneous_fixtures()
    samples = fixtures["base64_encoded_payloads"]
    column = ColumnInput(
        column_id="base64_encoded_payloads",
        column_name="jwt_payload",
        sample_values=samples,
    )
    result = detect_column_shape(column, [])
    assert result.shape == "opaque_tokens"


@pytest.mark.parametrize(
    "fixture_values,column_name,expected_shape",
    [
        # Homogeneous structured fixtures:
        (
            ["alice@example.com", "bob@example.org", "carol@test.io"] * 4,
            "email",
            "structured_single",
        ),
        (
            ["123-45-6789", "987-65-4321", "555-44-3322"] * 4,
            "ssn",
            "structured_single",
        ),
        (
            ["4111111111111111", "5555555555554444", "3782822463100051"] * 4,
            "credit_card",
            "structured_single",
        ),
        (
            ["+1-555-123-4567", "+44 20 7946 0958", "+1 (415) 555-0199"] * 4,
            "phone",
            "structured_single",
        ),
        # Additional opaque-token fixture: SHA-256 hex hashes (no dictionary
        # words, high entropy, not base64).
        (
            [
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
                "fcde2b2edba56bf408601fb721fe9b5c338d10ee429ea04fae5511b68fbf8fb9",
            ]
            * 4,
            "digest",
            "opaque_tokens",
        ),
    ],
)
def test_homogeneous_and_opaque_fixtures(fixture_values: list[str], column_name: str, expected_shape: str) -> None:
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(
        column_id=column_name,
        column_name=column_name,
        sample_values=fixture_values,
    )
    result = detect_column_shape(column, [])
    assert result.shape == expected_shape, (
        f"{column_name}: expected {expected_shape}, got {result.shape} "
        f"(avg_len={result.avg_len_normalized:.3f}, "
        f"dict_word={result.dict_word_ratio:.3f})"
    )
