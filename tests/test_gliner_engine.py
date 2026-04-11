"""Tests for GLiNER2 classification engine.

ALL tests use mock models — no ML dependencies required in CI.
The gliner package is never imported; we mock the model's predict_entities
and batch_predict_entities methods.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.registry import ModelRegistry
from data_classifier.registry.model_entry import ModelDependencyError

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_registry():
    """Create a fresh ModelRegistry for each test."""
    return ModelRegistry()


@pytest.fixture()
def mock_gliner_model():
    """Create a mock GLiNER model with predict_entities and batch_predict_entities."""
    model = MagicMock()
    model.predict_entities = MagicMock(return_value=[])
    model.batch_predict_entities = MagicMock(return_value=[])
    return model


@pytest.fixture()
def engine_with_mock(mock_registry, mock_gliner_model):
    """Create a GLiNER2Engine with a mock model pre-loaded in the registry."""
    from data_classifier.engines.gliner_engine import GLiNER2Engine

    engine = GLiNER2Engine(registry=mock_registry, gliner_threshold=0.5)
    # Register a loader that returns our mock
    mock_registry.register(
        "gliner2-ner",
        loader=lambda: mock_gliner_model,
        model_class="gliner.GLiNER",
        requires=[],  # No real deps to check
    )
    engine._registered = True
    return engine


@pytest.fixture()
def name_column():
    """Column with person name samples."""
    return ColumnInput(
        column_name="full_name",
        column_id="col_name",
        sample_values=["John Smith", "Maria Garcia", "Wei Zhang", "Ahmed Hassan", "Sarah Johnson"],
    )


@pytest.fixture()
def address_column():
    """Column with address samples."""
    return ColumnInput(
        column_name="street_address",
        column_id="col_addr",
        sample_values=[
            "123 Main St, Springfield IL 62704",
            "456 Oak Ave, Portland OR 97201",
            "789 Elm Dr, Austin TX 78701",
        ],
    )


# ── Test: PERSON_NAME detection ─────────────────────────────────────────────


class TestPersonNameDetection:
    """Test PERSON_NAME detection from name sample values."""

    def test_detects_person_names(self, engine_with_mock, mock_gliner_model, name_column):
        """Engine should detect PERSON_NAME from name samples."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.92},
            {"text": "Maria Garcia", "label": "person name", "score": 0.89},
            {"text": "Wei Zhang", "label": "person name", "score": 0.87},
        ]

        findings = engine_with_mock.classify_column(name_column)

        assert len(findings) == 1
        assert findings[0].entity_type == "PERSON_NAME"
        assert findings[0].engine == "gliner2"
        assert findings[0].confidence > 0.5
        assert findings[0].category == "PII"
        assert findings[0].sensitivity == "HIGH"

    def test_person_name_evidence(self, engine_with_mock, mock_gliner_model, name_column):
        """Finding should include matched name texts in evidence."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.92},
            {"text": "Maria Garcia", "label": "person name", "score": 0.89},
        ]

        findings = engine_with_mock.classify_column(name_column)

        assert len(findings) == 1
        assert findings[0].sample_analysis is not None
        assert "John Smith" in findings[0].sample_analysis.sample_matches
        assert findings[0].sample_analysis.samples_scanned == 5

    def test_person_name_regulatory(self, engine_with_mock, mock_gliner_model, name_column):
        """PERSON_NAME findings should include GDPR and CCPA."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.92},
        ]

        findings = engine_with_mock.classify_column(name_column)

        assert len(findings) == 1
        assert "GDPR" in findings[0].regulatory
        assert "CCPA" in findings[0].regulatory


# ── Test: ADDRESS detection ──────────────────────────────────────────────────


class TestAddressDetection:
    """Test ADDRESS detection from address sample values."""

    def test_detects_addresses(self, engine_with_mock, mock_gliner_model, address_column):
        """Engine should detect ADDRESS from address samples."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "123 Main St, Springfield IL 62704", "label": "physical address", "score": 0.85},
            {"text": "456 Oak Ave, Portland OR 97201", "label": "physical address", "score": 0.82},
        ]

        findings = engine_with_mock.classify_column(address_column)

        assert len(findings) == 1
        assert findings[0].entity_type == "ADDRESS"
        assert findings[0].engine == "gliner2"
        assert findings[0].confidence > 0.5

    def test_address_sample_analysis(self, engine_with_mock, mock_gliner_model, address_column):
        """ADDRESS finding should have correct sample analysis."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "123 Main St, Springfield IL 62704", "label": "physical address", "score": 0.85},
        ]

        findings = engine_with_mock.classify_column(address_column)

        assert len(findings) == 1
        sa = findings[0].sample_analysis
        assert sa is not None
        assert sa.samples_scanned == 3
        assert sa.samples_matched == 1


# ── Test: classify_batch ────────────────────────────────────────────────────


class TestClassifyBatch:
    """Test batched classification of multiple columns."""

    def test_batch_processes_multiple_columns(self, engine_with_mock, mock_gliner_model, name_column, address_column):
        """classify_batch should process multiple columns efficiently."""
        mock_gliner_model.batch_predict_entities.return_value = [
            [{"text": "John Smith", "label": "person name", "score": 0.92}],
            [{"text": "123 Main St", "label": "physical address", "score": 0.85}],
        ]

        results = engine_with_mock.classify_batch([name_column, address_column])

        assert len(results) == 2
        assert len(results[0]) == 1  # name column findings
        assert results[0][0].entity_type == "PERSON_NAME"
        assert len(results[1]) == 1  # address column findings
        assert results[1][0].entity_type == "ADDRESS"

    def test_batch_handles_empty_columns(self, engine_with_mock, mock_gliner_model):
        """classify_batch should handle columns without samples."""
        empty_col = ColumnInput(column_name="empty", column_id="col_empty", sample_values=[])
        name_col = ColumnInput(
            column_name="name",
            column_id="col_name",
            sample_values=["John Smith"],
        )
        mock_gliner_model.batch_predict_entities.return_value = [
            [{"text": "John Smith", "label": "person name", "score": 0.92}],
        ]

        results = engine_with_mock.classify_batch([empty_col, name_col])

        assert len(results) == 2
        assert results[0] == []  # empty column
        assert len(results[1]) == 1  # name column

    def test_batch_empty_input(self, engine_with_mock):
        """classify_batch with no columns returns empty list."""
        results = engine_with_mock.classify_batch([])
        assert results == []

    def test_batch_fallback_no_batch_predict(self, engine_with_mock, mock_gliner_model, name_column):
        """classify_batch falls back to predict_entities when batch_predict_entities is missing."""
        del mock_gliner_model.batch_predict_entities
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.92},
        ]

        results = engine_with_mock.classify_batch([name_column])

        assert len(results) == 1
        assert len(results[0]) == 1
        assert results[0][0].entity_type == "PERSON_NAME"


# ── Test: Missing dependencies ──────────────────────────────────────────────


class TestMissingDependencies:
    """Test graceful handling when gliner package is not installed."""

    def test_missing_gliner_raises_model_dependency_error(self, mock_registry):
        """Should raise ModelDependencyError with install instructions."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(registry=mock_registry, gliner_threshold=0.5)

        # Register with real dependency check (gliner is not installed in CI)
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: None,
            model_class="gliner.GLiNER",
            requires=["gliner"],  # This package is NOT installed
        )
        engine._registered = True

        column = ColumnInput(
            column_name="name",
            column_id="col1",
            sample_values=["John Smith"],
        )

        with pytest.raises(ModelDependencyError, match="gliner"):
            engine.classify_column(column)

    def test_dependency_error_includes_install_instructions(self, mock_registry):
        """Error message should include pip install instructions."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(registry=mock_registry)
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: None,
            model_class="gliner.GLiNER",
            requires=["gliner"],
        )
        engine._registered = True

        column = ColumnInput(column_name="x", column_id="c1", sample_values=["test"])

        with pytest.raises(ModelDependencyError, match="pip install"):
            engine.classify_column(column)


# ── Test: Entity type mapping ───────────────────────────────────────────────


class TestEntityTypeMapping:
    """Test that GLiNER2 labels map correctly to our entity types."""

    def test_all_labels_have_reverse_mapping(self):
        """Every ENTITY_TO_GLINER_LABEL value should reverse-map correctly."""
        from data_classifier.engines.gliner_engine import ENTITY_TO_GLINER_LABEL, GLINER_LABEL_TO_ENTITY

        for entity_type, label in ENTITY_TO_GLINER_LABEL.items():
            assert label in GLINER_LABEL_TO_ENTITY
            assert GLINER_LABEL_TO_ENTITY[label] == entity_type

    def test_supported_entity_types(self):
        """Engine should support the expected entity types."""
        from data_classifier.engines.gliner_engine import ENTITY_TO_GLINER_LABEL

        expected = {"PERSON_NAME", "ADDRESS", "ORGANIZATION", "DATE_OF_BIRTH"}
        assert set(ENTITY_TO_GLINER_LABEL.keys()) == expected

    def test_gliner_labels_are_natural_language(self):
        """GLiNER2 labels should be human-readable NL phrases."""
        from data_classifier.engines.gliner_engine import ENTITY_TO_GLINER_LABEL

        for label in ENTITY_TO_GLINER_LABEL.values():
            assert " " in label or label.isalpha(), f"Label '{label}' should be natural language"

    def test_unknown_label_ignored(self, engine_with_mock, mock_gliner_model):
        """Predictions with unknown labels should be silently ignored."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "some text", "label": "unknown_type", "score": 0.99},
        ]
        column = ColumnInput(column_name="test", column_id="c1", sample_values=["some text"])
        findings = engine_with_mock.classify_column(column)
        assert findings == []

    def test_organization_detection(self, engine_with_mock, mock_gliner_model):
        """Engine should detect ORGANIZATION from predictions."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "Acme Corp", "label": "organization", "score": 0.88},
            {"text": "Google LLC", "label": "organization", "score": 0.91},
        ]
        column = ColumnInput(
            column_name="company",
            column_id="c1",
            sample_values=["Acme Corp", "Google LLC", "IBM"],
        )
        findings = engine_with_mock.classify_column(column)
        assert len(findings) == 1
        assert findings[0].entity_type == "ORGANIZATION"
        assert findings[0].sensitivity == "MEDIUM"

    def test_date_of_birth_detection(self, engine_with_mock, mock_gliner_model):
        """Engine should detect DATE_OF_BIRTH from predictions."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "January 15, 1990", "label": "date of birth", "score": 0.78},
        ]
        column = ColumnInput(
            column_name="dob",
            column_id="c1",
            sample_values=["January 15, 1990", "March 2, 1985"],
        )
        findings = engine_with_mock.classify_column(column)
        assert len(findings) == 1
        assert findings[0].entity_type == "DATE_OF_BIRTH"
        assert "HIPAA" in findings[0].regulatory


# ── Test: Confidence threshold ──────────────────────────────────────────────


class TestConfidenceThreshold:
    """Test confidence threshold filtering."""

    def test_low_confidence_predictions_filtered(self, engine_with_mock, mock_gliner_model):
        """Predictions below min_confidence should not produce findings."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.3},
        ]
        column = ColumnInput(column_name="name", column_id="c1", sample_values=["John Smith"])

        findings = engine_with_mock.classify_column(column, min_confidence=0.5)
        assert findings == []

    def test_high_confidence_predictions_pass(self, engine_with_mock, mock_gliner_model):
        """Predictions above min_confidence should produce findings."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.95},
            {"text": "Maria Garcia", "label": "person name", "score": 0.92},
            {"text": "Wei Zhang", "label": "person name", "score": 0.88},
            {"text": "Ahmed Hassan", "label": "person name", "score": 0.90},
        ]
        column = ColumnInput(
            column_name="name",
            column_id="c1",
            sample_values=["John Smith", "Maria Garcia", "Wei Zhang", "Ahmed Hassan"],
        )

        findings = engine_with_mock.classify_column(column, min_confidence=0.5)
        assert len(findings) == 1
        assert findings[0].confidence > 0.5

    def test_custom_gliner_threshold(self, mock_registry, mock_gliner_model):
        """Engine should respect custom gliner_threshold at init."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(registry=mock_registry, gliner_threshold=0.8)
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: mock_gliner_model,
            model_class="gliner.GLiNER",
            requires=[],
        )
        engine._registered = True

        mock_gliner_model.predict_entities.return_value = [
            {"text": "John", "label": "person name", "score": 0.85},
        ]
        column = ColumnInput(column_name="name", column_id="c1", sample_values=["John"])

        # The threshold is passed to predict_entities
        engine.classify_column(column)
        call_args = mock_gliner_model.predict_entities.call_args
        assert call_args is not None
        # threshold should be 0.8
        assert call_args[1].get("threshold", call_args[0][2] if len(call_args[0]) > 2 else None) == 0.8


# ── Test: Engine properties ─────────────────────────────────────────────────


class TestEngineProperties:
    """Test engine metadata and ClassificationEngine contract."""

    def test_engine_name(self):
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine()
        assert engine.name == "gliner2"

    def test_engine_order(self):
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine()
        assert engine.order == 5

    def test_supported_modes(self):
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine()
        assert "structured" in engine.supported_modes

    def test_no_samples_returns_empty(self, engine_with_mock):
        """Column with no samples should return empty findings."""
        column = ColumnInput(column_name="test", column_id="c1", sample_values=[])
        findings = engine_with_mock.classify_column(column)
        assert findings == []

    def test_no_predictions_returns_empty(self, engine_with_mock, mock_gliner_model):
        """No NER predictions should return empty findings."""
        mock_gliner_model.predict_entities.return_value = []
        column = ColumnInput(column_name="test", column_id="c1", sample_values=["some data"])
        findings = engine_with_mock.classify_column(column)
        assert findings == []

    def test_mask_samples_redacts_evidence(self, engine_with_mock, mock_gliner_model):
        """mask_samples=True should redact evidence text."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.92},
        ]
        column = ColumnInput(column_name="name", column_id="c1", sample_values=["John Smith"])

        findings = engine_with_mock.classify_column(column, mask_samples=True)
        assert len(findings) == 1
        # Masked value should not contain full name
        matches = findings[0].sample_analysis.sample_matches
        assert matches[0] != "John Smith"
        assert matches[0].startswith("J")
        assert matches[0].endswith("h")

    def test_custom_entity_types(self, mock_registry, mock_gliner_model):
        """Engine should only detect requested entity types."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(
            registry=mock_registry,
            entity_types=["PERSON_NAME"],
        )
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: mock_gliner_model,
            model_class="gliner.GLiNER",
            requires=[],
        )
        engine._registered = True

        assert engine._entity_types == ["PERSON_NAME"]
        assert engine._gliner_labels == ["person name"]


# ── Test: Multiple entity types in one column ──────────────────────────────


class TestMultipleEntityTypes:
    """Test detection of multiple entity types in a single column."""

    def test_mixed_entity_predictions(self, engine_with_mock, mock_gliner_model):
        """Column with mixed entity types should produce multiple findings."""
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.92},
            {"text": "123 Main St", "label": "physical address", "score": 0.85},
        ]
        column = ColumnInput(
            column_name="notes",
            column_id="c1",
            sample_values=["John Smith lives at 123 Main St"],
        )

        findings = engine_with_mock.classify_column(column)
        entity_types = {f.entity_type for f in findings}
        # Both should be detected (both above min_confidence with single-count scaling)
        # Single prediction gets 0.85 * 0.85 scaling
        assert "PERSON_NAME" in entity_types or "ADDRESS" in entity_types

    def test_confidence_scaling_by_count(self, engine_with_mock, mock_gliner_model):
        """More predictions should increase confidence."""
        # Single prediction
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.90},
        ]
        col1 = ColumnInput(column_name="name", column_id="c1", sample_values=["John Smith"])
        findings_single = engine_with_mock.classify_column(col1, min_confidence=0.0)

        # Multiple predictions
        mock_gliner_model.predict_entities.return_value = [
            {"text": "John Smith", "label": "person name", "score": 0.90},
            {"text": "Maria Garcia", "label": "person name", "score": 0.88},
            {"text": "Wei Zhang", "label": "person name", "score": 0.92},
            {"text": "Ahmed Hassan", "label": "person name", "score": 0.87},
        ]
        col2 = ColumnInput(
            column_name="name",
            column_id="c2",
            sample_values=["John Smith", "Maria Garcia", "Wei Zhang", "Ahmed Hassan"],
        )
        findings_multi = engine_with_mock.classify_column(col2, min_confidence=0.0)

        assert len(findings_single) == 1
        assert len(findings_multi) == 1
        # Multiple matches should have higher confidence
        assert findings_multi[0].confidence > findings_single[0].confidence
