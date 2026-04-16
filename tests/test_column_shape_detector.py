from data_classifier.core.types import ClassificationFinding, ColumnInput


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
    engine_findings = {"regex": [_finding("EMAIL")]}
    result = detect_column_shape(column, engine_findings)
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
    engine_findings = {
        "regex": [_finding("EMAIL"), _finding("IP_ADDRESS"), _finding("DATE_TIME")],
    }
    result = detect_column_shape(column, engine_findings)
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
    engine_findings = {"regex": []}
    result = detect_column_shape(column, engine_findings)
    assert result.shape == "opaque_tokens"
    assert result.dict_word_ratio < 0.1


def test_empty_sample_values_defaults_to_structured_single():
    from data_classifier.orchestrator.shape_detector import detect_column_shape

    column = ColumnInput(column_id="col_1", column_name="unknown", sample_values=[])
    result = detect_column_shape(column, {})
    assert result.shape == "structured_single"
    assert result.avg_len_normalized == 0.0
