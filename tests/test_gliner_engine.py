"""Tests for GLiNER2 classification engine.

ALL tests use mock models — no ML dependencies required in CI.
The gliner2 package is never imported; we mock the model's extract_entities method.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from data_classifier.core.types import ColumnInput
from data_classifier.registry import ModelRegistry
from data_classifier.registry.model_entry import ModelDependencyError

# ── Helper: build GLiNER2-style extract_entities response ─────────────────


def _gliner_predictions(entities: dict[str, list[tuple[str, float]]]) -> list[dict]:
    """Build mock GLiNER v1 predict_entities response.

    Args:
        entities: {gliner_label: [(text, score), ...]}
    """
    return [
        {"text": text, "label": label, "score": score} for label, matches in entities.items() for text, score in matches
    ]


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_registry():
    """Create a fresh ModelRegistry for each test."""
    return ModelRegistry()


@pytest.fixture()
def mock_gliner_model():
    """Create a mock GLiNER2 model with extract_entities."""
    model = MagicMock()
    model.predict_entities = MagicMock(return_value=[])
    return model


@pytest.fixture()
def engine_with_mock(mock_registry, mock_gliner_model):
    """Create a GLiNER2Engine with a mock model pre-loaded in the registry."""
    from data_classifier.engines.gliner_engine import GLiNER2Engine

    engine = GLiNER2Engine(registry=mock_registry, gliner_threshold=0.5)
    mock_registry.register(
        "gliner2-ner",
        loader=lambda: mock_gliner_model,
        model_class="gliner.GLiNER",
        requires=[],
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
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [("John Smith", 0.92), ("Maria Garcia", 0.89), ("Wei Zhang", 0.87)],
            }
        )

        findings = engine_with_mock.classify_column(name_column)

        assert len(findings) == 1
        assert findings[0].entity_type == "PERSON_NAME"
        assert findings[0].engine == "gliner2"
        assert findings[0].confidence > 0.5
        assert findings[0].category == "PII"
        assert findings[0].sensitivity == "HIGH"

    def test_person_name_evidence(self, engine_with_mock, mock_gliner_model, name_column):
        """Finding should include matched name texts in evidence."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [("John Smith", 0.92), ("Maria Garcia", 0.89)],
            }
        )

        findings = engine_with_mock.classify_column(name_column)

        assert len(findings) == 1
        assert findings[0].sample_analysis is not None
        assert "John Smith" in findings[0].sample_analysis.sample_matches
        assert findings[0].sample_analysis.samples_scanned == 5

    def test_person_name_regulatory(self, engine_with_mock, mock_gliner_model, name_column):
        """PERSON_NAME findings should include GDPR and CCPA."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [("John Smith", 0.92)],
            }
        )

        findings = engine_with_mock.classify_column(name_column)

        assert len(findings) == 1
        assert "GDPR" in findings[0].regulatory
        assert "CCPA" in findings[0].regulatory


# ── Test: ADDRESS detection ──────────────────────────────────────────────────


class TestAddressDetection:
    """Test ADDRESS detection from address sample values."""

    def test_detects_addresses(self, engine_with_mock, mock_gliner_model, address_column):
        """Engine should detect ADDRESS from address samples."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "street address": [
                    ("123 Main St, Springfield IL 62704", 0.85),
                    ("456 Oak Ave, Portland OR 97201", 0.82),
                ],
            }
        )

        findings = engine_with_mock.classify_column(address_column)

        assert len(findings) == 1
        assert findings[0].entity_type == "ADDRESS"
        assert findings[0].engine == "gliner2"
        assert findings[0].confidence > 0.5

    def test_address_sample_analysis(self, engine_with_mock, mock_gliner_model, address_column):
        """ADDRESS finding should have correct sample analysis."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "street address": [("123 Main St, Springfield IL 62704", 0.85)],
            }
        )

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
        """classify_batch should process multiple columns."""
        mock_gliner_model.predict_entities.side_effect = [
            _gliner_predictions({"person": [("John Smith", 0.92)]}),
            _gliner_predictions({"street address": [("123 Main St", 0.85)]}),
        ]

        results = engine_with_mock.classify_batch([name_column, address_column])

        assert len(results) == 2
        assert len(results[0]) == 1
        assert results[0][0].entity_type == "PERSON_NAME"
        assert len(results[1]) == 1
        assert results[1][0].entity_type == "ADDRESS"

    def test_batch_handles_empty_columns(self, engine_with_mock, mock_gliner_model):
        """classify_batch should handle columns without samples."""
        empty_col = ColumnInput(column_name="empty", column_id="col_empty", sample_values=[])
        name_col = ColumnInput(column_name="name", column_id="col_name", sample_values=["John Smith"])
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [("John Smith", 0.92)],
            }
        )

        results = engine_with_mock.classify_batch([empty_col, name_col])

        assert len(results) == 2
        assert results[0] == []
        assert len(results[1]) == 1

    def test_batch_empty_input(self, engine_with_mock):
        """classify_batch with no columns returns empty list."""
        results = engine_with_mock.classify_batch([])
        assert results == []


# ── Test: Missing dependencies ──────────────────────────────────────────────


class TestMissingDependencies:
    """Test graceful handling when gliner2 package is not installed."""

    def test_missing_gliner2_raises_model_dependency_error(self, mock_registry):
        """Should raise ModelDependencyError with install instructions."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(registry=mock_registry, gliner_threshold=0.5)
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: None,
            model_class="gliner.GLiNER",
            requires=["gliner2_fake_pkg"],  # Not installed
        )
        engine._registered = True

        column = ColumnInput(column_name="name", column_id="col1", sample_values=["John Smith"])

        with pytest.raises(ModelDependencyError, match="gliner2_fake_pkg"):
            engine.classify_column(column)

    def test_dependency_error_includes_install_instructions(self, mock_registry):
        """Error message should include pip install instructions."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(registry=mock_registry)
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: None,
            model_class="gliner.GLiNER",
            requires=["gliner2_fake_pkg"],
        )
        engine._registered = True

        column = ColumnInput(column_name="x", column_id="c1", sample_values=["test"])

        with pytest.raises(ModelDependencyError, match="pip install"):
            engine.classify_column(column)


# ── Test: Entity type mapping ───────────────────────────────────────────────


class TestEntityTypeMapping:
    """Test that GLiNER2 labels map correctly to our entity types."""

    def test_all_labels_have_reverse_mapping(self):
        """Every label should reverse-map correctly."""
        from data_classifier.engines.gliner_engine import ENTITY_LABEL_DESCRIPTIONS, GLINER_LABEL_TO_ENTITY

        for entity_type, (label, _desc) in ENTITY_LABEL_DESCRIPTIONS.items():
            assert label in GLINER_LABEL_TO_ENTITY
            assert GLINER_LABEL_TO_ENTITY[label] == entity_type

    def test_supported_entity_types(self):
        """Engine should support the expected entity types."""
        from data_classifier.engines.gliner_engine import ENTITY_LABEL_DESCRIPTIONS

        expected = {
            "PERSON_NAME",
            "ADDRESS",
            "ORGANIZATION",
            "DATE_OF_BIRTH",
            "PHONE",
            "SSN",
            "EMAIL",
            "IP_ADDRESS",
        }
        assert set(ENTITY_LABEL_DESCRIPTIONS.keys()) == expected

    def test_all_labels_have_descriptions(self):
        """Every entity type should have a non-empty description."""
        from data_classifier.engines.gliner_engine import ENTITY_LABEL_DESCRIPTIONS

        for entity_type, (label, desc) in ENTITY_LABEL_DESCRIPTIONS.items():
            assert label, f"{entity_type} has empty label"
            assert desc, f"{entity_type} has empty description"
            assert len(desc) > 10, f"{entity_type} description too short"

    def test_unknown_label_ignored(self, engine_with_mock, mock_gliner_model):
        """Predictions with unknown labels should be silently ignored."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "unknown_type": [("some text", 0.99)],
            }
        )
        column = ColumnInput(column_name="test", column_id="c1", sample_values=["some text"])
        findings = engine_with_mock.classify_column(column)
        assert findings == []

    def test_organization_detection(self, engine_with_mock, mock_gliner_model):
        """Engine should detect ORGANIZATION from predictions."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "organization": [("Acme Corp", 0.88), ("Google LLC", 0.91)],
            }
        )
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
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "date of birth": [("January 15, 1990", 0.78)],
            }
        )
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
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [("John Smith", 0.3)],
            }
        )
        column = ColumnInput(column_name="name", column_id="c1", sample_values=["John Smith"])

        findings = engine_with_mock.classify_column(column, min_confidence=0.5)
        assert findings == []

    def test_high_confidence_predictions_pass(self, engine_with_mock, mock_gliner_model):
        """Predictions above min_confidence should produce findings."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [
                    ("John Smith", 0.95),
                    ("Maria Garcia", 0.92),
                    ("Wei Zhang", 0.88),
                    ("Ahmed Hassan", 0.90),
                ],
            }
        )
        column = ColumnInput(
            column_name="name",
            column_id="c1",
            sample_values=["John Smith", "Maria Garcia", "Wei Zhang", "Ahmed Hassan"],
        )

        findings = engine_with_mock.classify_column(column, min_confidence=0.5)
        assert len(findings) == 1
        assert findings[0].confidence > 0.5


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
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({})
        column = ColumnInput(column_name="test", column_id="c1", sample_values=["some data"])
        findings = engine_with_mock.classify_column(column)
        assert findings == []

    def test_mask_samples_redacts_evidence(self, engine_with_mock, mock_gliner_model):
        """mask_samples=True should redact evidence text."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [("John Smith", 0.92)],
            }
        )
        column = ColumnInput(column_name="name", column_id="c1", sample_values=["John Smith"])

        findings = engine_with_mock.classify_column(column, mask_samples=True)
        assert len(findings) == 1
        matches = findings[0].sample_analysis.sample_matches
        assert matches[0] != "John Smith"
        assert matches[0].startswith("J")
        assert matches[0].endswith("h")

    def test_custom_entity_types(self, mock_registry, mock_gliner_model):
        """Engine should only detect requested entity types."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(registry=mock_registry, entity_types=["PERSON_NAME"])
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: mock_gliner_model,
            model_class="gliner.GLiNER",
            requires=[],
        )
        engine._registered = True

        assert engine._entity_types == ["PERSON_NAME"]
        assert "person" in engine._gliner_labels


# ── Test: Multiple entity types in one column ──────────────────────────────


class TestMultipleEntityTypes:
    """Test detection of multiple entity types in a single column."""

    def test_mixed_entity_predictions(self, engine_with_mock, mock_gliner_model):
        """Column with mixed entity types should produce findings for both."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [("John Smith", 0.92)],
                "street address": [("123 Main St", 0.85)],
            }
        )
        column = ColumnInput(
            column_name="notes",
            column_id="c1",
            sample_values=["John Smith lives at 123 Main St"],
        )

        findings = engine_with_mock.classify_column(column)
        entity_types = {f.entity_type for f in findings}
        # ADDRESS is more specific and should suppress PERSON_NAME (dedup)
        assert "ADDRESS" in entity_types

    def test_confidence_scaling_by_count(self, engine_with_mock, mock_gliner_model):
        """More predictions should increase confidence."""
        # Single prediction
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [("John Smith", 0.90)],
            }
        )
        col1 = ColumnInput(column_name="name", column_id="c1", sample_values=["John Smith"])
        findings_single = engine_with_mock.classify_column(col1, min_confidence=0.0)

        # Multiple predictions
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "person": [
                    ("John Smith", 0.90),
                    ("Maria Garcia", 0.88),
                    ("Wei Zhang", 0.92),
                    ("Ahmed Hassan", 0.87),
                ],
            }
        )
        col2 = ColumnInput(
            column_name="name",
            column_id="c2",
            sample_values=["John Smith", "Maria Garcia", "Wei Zhang", "Ahmed Hassan"],
        )
        findings_multi = engine_with_mock.classify_column(col2, min_confidence=0.0)

        assert len(findings_single) == 1
        assert len(findings_multi) == 1
        assert findings_multi[0].confidence > findings_single[0].confidence


# ── Test: Deduplication ─────────────────────────────────────────────────────


class TestDeduplication:
    """Test entity specificity deduplication."""

    def test_address_suppresses_person_name(self, engine_with_mock, mock_gliner_model):
        """When both ADDRESS and PERSON_NAME found, ADDRESS should win."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "street address": [("Preston Road", 0.85)],
                "person": [("Preston", 0.70)],
            }
        )
        column = ColumnInput(column_name="col_0", column_id="c1", sample_values=["Preston Road"])

        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        entity_types = {f.entity_type for f in findings}
        assert "ADDRESS" in entity_types
        assert "PERSON_NAME" not in entity_types

    def test_same_specificity_both_kept(self, engine_with_mock, mock_gliner_model):
        """Findings at the same specificity level are both kept."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "email": [("john@test.com", 0.95)],
                "phone number": [("555-1234", 0.90)],
            }
        )
        column = ColumnInput(
            column_name="col_0",
            column_id="c1",
            sample_values=["john@test.com", "555-1234"],
        )

        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        entity_types = {f.entity_type for f in findings}
        # Both EMAIL and PHONE have specificity 3 — both kept
        assert "EMAIL" in entity_types
        assert "PHONE" in entity_types
