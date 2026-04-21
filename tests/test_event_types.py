"""Tests for event types."""


def test_column_shape_event_default_construction():
    from data_classifier.events.types import ColumnShapeEvent

    event = ColumnShapeEvent(
        column_id="col_1",
        shape="structured_single",
        avg_len_normalized=0.15,
        dict_word_ratio=0.0,
        cardinality_ratio=0.9,
        n_cascade_entities=1,
        column_name_hint_applied=False,
    )
    assert event.shape == "structured_single"
    assert event.per_value_inference_ms is None
    assert event.sampled_row_count is None
    assert event.run_id == ""
    assert event.timestamp  # ISO timestamp populated by default_factory


def test_column_shape_event_with_item_b_latency_fields():
    from data_classifier.events.types import ColumnShapeEvent

    event = ColumnShapeEvent(
        column_id="col_1",
        shape="free_text_heterogeneous",
        avg_len_normalized=0.72,
        dict_word_ratio=0.45,
        cardinality_ratio=1.0,
        n_cascade_entities=4,
        column_name_hint_applied=True,
        per_value_inference_ms=1280,
        sampled_row_count=60,
    )
    assert event.per_value_inference_ms == 1280
    assert event.sampled_row_count == 60
