"""Shared test fixtures for data_classifier tests."""

from __future__ import annotations

import pytest

from data_classifier import ClassificationProfile, load_profile
from data_classifier.core.types import ColumnInput


@pytest.fixture
def standard_profile() -> ClassificationProfile:
    """Load the bundled standard classification profile."""
    return load_profile("standard")


@pytest.fixture
def make_column():
    """Factory fixture for creating ColumnInput instances."""

    def _make(
        name: str,
        *,
        column_id: str = "",
        sample_values: list[str] | None = None,
        data_type: str = "STRING",
    ) -> ColumnInput:
        return ColumnInput(
            column_name=name,
            column_id=column_id or f"test:table:{name}",
            data_type=data_type,
            sample_values=sample_values or [],
        )

    return _make
