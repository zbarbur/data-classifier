"""Tests for data_classifier.core.types dataclasses."""

import dataclasses

import pytest

from data_classifier.core.types import SpanDetection


def test_span_detection_is_frozen_dataclass():
    """SpanDetection instances are immutable (frozen)."""
    span = SpanDetection(
        text="alice@example.com",
        entity_type="EMAIL",
        confidence=0.95,
        start=12,
        end=29,
    )
    assert span.text == "alice@example.com"
    assert span.entity_type == "EMAIL"
    assert span.confidence == 0.95
    assert span.start == 12
    assert span.end == 29

    # Verify frozen: attempt to mutate raises FrozenInstanceError
    with pytest.raises(dataclasses.FrozenInstanceError):
        span.confidence = 0.5  # type: ignore[misc]


def test_span_detection_equality_enables_set_dedup():
    """SpanDetection is hashable and deduplicatable in sets."""
    a = SpanDetection(text="x", entity_type="EMAIL", confidence=0.9, start=0, end=1)
    b = SpanDetection(text="x", entity_type="EMAIL", confidence=0.9, start=0, end=1)
    assert a == b
    assert hash(a) == hash(b)

    # Verify deduplication in sets
    span_set = {a, b}
    assert len(span_set) == 1
