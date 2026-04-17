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
            # Promoted from experimental in Sprint 14
            "AGE",
            "HEALTH",
            "FINANCIAL",
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


# ── Test: Sprint 9 v2 infrastructure hardening ────────────────────────────
#
# These tests cover infrastructure added in Sprint 9 ahead of the fastino
# model swap (blocked on blind-corpus regression, deferred to Sprint 10
# pending research/gliner-context context-injection work).  The
# infrastructure itself ships now because:
#   1. The v2 inference path was silently ignoring the configured
#      threshold — a latent correctness bug that affected any v2
#      deployment, not just fastino.
#   2. The descriptions_enabled flag + ONNX auto-discovery guard provide
#      the seam for a future fastino promotion without further code
#      changes once the input-format work on research/gliner-context lands.


class TestDescriptionsEnabledFlag:
    """descriptions_enabled init flag — default selection and override."""

    def test_v1_model_defaults_descriptions_on(self):
        """Urchade (v1) engines default to descriptions_enabled=True.

        v1 ignores the flag at inference time (it only accepts a label
        list via ``predict_entities``), but the flag is still set for
        consistency and testability.
        """
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(model_id="urchade/gliner_multi_pii-v1")
        assert engine._is_v2 is False
        assert engine._descriptions_enabled is True

    def test_fastino_model_defaults_descriptions_off(self):
        """Fastino (v2) engines default to descriptions_enabled=False.

        Per the Sprint 9 GLiNER eval memo, fastino regresses by -0.062
        to -0.093 macro F1 when descriptions are enabled, so the auto
        selection ships with descriptions off for any ``fastino/*``
        model_id.
        """
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(model_id="fastino/gliner2-base-v1")
        assert engine._is_v2 is True
        assert engine._descriptions_enabled is False

    def test_explicit_override_wins_over_auto_selection(self):
        """Caller can force descriptions_enabled regardless of model_id."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(
            model_id="fastino/gliner2-base-v1",
            descriptions_enabled=True,
        )
        assert engine._descriptions_enabled is True

        engine = GLiNER2Engine(
            model_id="urchade/gliner_multi_pii-v1",
            descriptions_enabled=False,
        )
        assert engine._descriptions_enabled is False


class TestV2InferencePathThresholdPlumbing:
    """v2 extract_entities call shape — threshold passed, spec form correct.

    Regression guard for a latent bug discovered Sprint 9: the v2 path
    was calling ``model.extract_entities(text, spec, include_confidence=True)``
    without forwarding ``self._gliner_threshold``, so the gliner2
    internal default threshold was used regardless of how the engine
    was constructed.  Any downstream threshold tuning was silently
    ignored for v2 deployments.
    """

    def _make_v2_engine(
        self,
        mock_registry,
        mock_model,
        *,
        descriptions_enabled: bool | None = None,
        gliner_threshold: float = 0.80,
    ):
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(
            registry=mock_registry,
            model_id="fastino/gliner2-base-v1",
            gliner_threshold=gliner_threshold,
            descriptions_enabled=descriptions_enabled,
        )
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: mock_model,
            model_class="gliner2.GLiNER2",
            requires=[],
        )
        engine._registered = True
        return engine

    def test_v2_descriptions_off_passes_label_list_with_threshold(self, mock_registry):
        """When descriptions_enabled=False, engine passes a list[str] spec
        AND forwards the configured threshold to extract_entities."""
        mock_model = MagicMock()
        mock_model.extract_entities = MagicMock(
            return_value={"entities": {"person": [{"text": "Jane Doe", "confidence": 0.91}]}}
        )
        engine = self._make_v2_engine(mock_registry, mock_model, gliner_threshold=0.80)

        column = ColumnInput(column_name="name", column_id="c1", sample_values=["Jane Doe"])
        findings = engine.classify_column(column, min_confidence=0.0)

        assert len(findings) == 1
        assert findings[0].entity_type == "PERSON_NAME"

        assert mock_model.extract_entities.called
        call = mock_model.extract_entities.call_args
        entity_spec = call.args[1] if len(call.args) > 1 else call.kwargs.get("entity_types")
        assert isinstance(entity_spec, list), (
            f"Expected list[str] when descriptions_enabled=False, got {type(entity_spec).__name__}"
        )
        assert "person" in entity_spec
        # Threshold must be forwarded — this is the latent bug the fix closes.
        assert call.kwargs.get("threshold") == 0.80

    def test_v2_descriptions_on_passes_label_dict_with_threshold(self, mock_registry):
        """When descriptions_enabled=True, engine passes dict[str, str]
        AND still forwards the configured threshold."""
        mock_model = MagicMock()
        mock_model.extract_entities = MagicMock(return_value={"entities": {}})
        engine = self._make_v2_engine(
            mock_registry,
            mock_model,
            descriptions_enabled=True,
            gliner_threshold=0.65,
        )

        column = ColumnInput(column_name="x", column_id="c1", sample_values=["something"])
        engine.classify_column(column, min_confidence=0.0)

        call = mock_model.extract_entities.call_args
        entity_spec = call.args[1] if len(call.args) > 1 else call.kwargs.get("entity_types")
        assert isinstance(entity_spec, dict), (
            f"Expected dict[str, str] when descriptions_enabled=True, got {type(entity_spec).__name__}"
        )
        assert "person" in entity_spec
        # Descriptions must be non-empty in the dict form.
        assert entity_spec["person"]
        assert call.kwargs.get("threshold") == 0.65


class TestOnnxAutoDiscoveryGuardForV2:
    """ONNX auto-discovery must NOT serve a v1 export to a v2 engine.

    The standard ONNX search paths (package models/, ~/.cache/..., etc.)
    hold v1 exports from Sprint 5 onwards.  Before Sprint 9, constructing
    a GLiNER2Engine with ``model_id="fastino/gliner2-base-v1"`` would
    auto-discover the v1 bundle and load it with the v1 gliner package,
    silently serving the wrong model.  The guard ensures auto-discovery
    only runs for v1 engines.
    """

    def test_v2_engine_skips_auto_discovery_when_onnx_path_unset(self):
        """fastino engine without explicit onnx_path must NOT pick up
        a bundled v1 model from the auto-discovery paths."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        engine = GLiNER2Engine(model_id="fastino/gliner2-base-v1")
        assert engine._onnx_path is None, (
            "v2 engine auto-discovered an ONNX bundle; v2 must fall through to "
            "PyTorch loading or require an explicit onnx_path"
        )

    def test_v2_engine_honors_explicit_onnx_path(self, tmp_path):
        """If caller explicitly sets onnx_path on a v2 engine, the guard
        must NOT override it — hand-exported fastino bundles should work."""
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        explicit_path = str(tmp_path / "fake_fastino_onnx_dir")
        engine = GLiNER2Engine(
            model_id="fastino/gliner2-base-v1",
            onnx_path=explicit_path,
        )
        assert engine._onnx_path == explicit_path


# ── Sprint 10: S1 NL-prompt wrapping ───────────────────────────────────────
#
# Pass 1 on research/gliner-context @ 7b2ed91 measured that wrapping sample
# values in a natural-language sentence with column/table/description
# metadata recovers +0.0887 macro F1 on Ai4Privacy (BCa 95% CI
# [+0.050, +0.131], n=315) because GLiNER is a context-attention NER model
# trained on sentences, not bag-of-tokens input.  The improvement is
# primarily false-positive suppression — baseline over-fires ORGANIZATION,
# PERSON_NAME, and PHONE on numeric-dash strings (e.g., "123-45-6789"),
# and the NL prefix narrows the plausible interpretation space enough to
# suppress those FPs.  The tests below cover the helper's metadata
# graceful-degradation contract and the ORGANIZATION numeric-dash
# regression that the research memo identified.


class TestBuildNerPrompt:
    """Unit tests for the pure ``_build_ner_prompt`` helper."""

    def test_all_metadata_present(self):
        """All three metadata fields produce the full NL prefix."""
        from data_classifier.engines.gliner_engine import _build_ner_prompt

        column = ColumnInput(
            column_name="customer_email",
            column_id="c1",
            table_name="customers",
            description="Primary contact email for the customer",
            sample_values=["jane@example.com", "john@example.org"],
        )
        prompt = _build_ner_prompt(column, column.sample_values)

        assert "Column 'customer_email'" in prompt
        assert "from table 'customers'" in prompt
        assert "Description: Primary contact email for the customer" in prompt
        assert "Sample values: jane@example.com, john@example.org" in prompt
        # The legacy " ; " separator must not appear when metadata is present.
        assert " ; " not in prompt

    def test_only_column_name(self):
        """Only column_name populated: prefix omits table + description clauses."""
        from data_classifier.engines.gliner_engine import _build_ner_prompt

        column = ColumnInput(
            column_name="ssn",
            column_id="c1",
            sample_values=["123-45-6789", "987-65-4321"],
        )
        prompt = _build_ner_prompt(column, column.sample_values)

        assert "Column 'ssn'" in prompt
        assert "Sample values: 123-45-6789, 987-65-4321" in prompt
        assert "table" not in prompt
        assert "Description" not in prompt

    def test_only_description(self):
        """Only description populated: prefix is a bare description clause."""
        from data_classifier.engines.gliner_engine import _build_ner_prompt

        column = ColumnInput(
            column_name="",
            column_id="c1",
            description="IPv4 address of the client",
            sample_values=["192.168.1.1", "10.0.0.5"],
        )
        prompt = _build_ner_prompt(column, column.sample_values)

        assert "Description: IPv4 address of the client" in prompt
        assert "Sample values: 192.168.1.1, 10.0.0.5" in prompt
        assert "Column '" not in prompt
        assert "table" not in prompt

    def test_no_metadata_falls_back_to_legacy_separator(self):
        """With no metadata the helper emits the pre-S1 legacy shape."""
        from data_classifier.engines.gliner_engine import _SAMPLE_SEPARATOR, _build_ner_prompt

        column = ColumnInput(
            column_name="",
            column_id="c1",
            sample_values=["alpha", "beta", "gamma"],
        )
        prompt = _build_ner_prompt(column, column.sample_values)

        assert prompt == _SAMPLE_SEPARATOR.join(["alpha", "beta", "gamma"])
        assert "Column '" not in prompt
        assert "Sample values:" not in prompt

    def test_table_name_with_empty_column_name(self):
        """Only table_name populated: prefix starts with Table '...'."""
        from data_classifier.engines.gliner_engine import _build_ner_prompt

        column = ColumnInput(
            column_name="",
            column_id="c1",
            table_name="users",
            sample_values=["Alice", "Bob"],
        )
        prompt = _build_ner_prompt(column, column.sample_values)

        assert "Table 'users'" in prompt
        assert "Sample values: Alice, Bob" in prompt
        assert "Column '" not in prompt
        assert "from table" not in prompt

    def test_long_description_is_truncated_within_max_len(self):
        """A description that would overflow the prompt budget is truncated
        instead of silently dropping samples."""
        from data_classifier.engines.gliner_engine import _MAX_PROMPT_CHARS, _build_ner_prompt

        # Construct a description that is larger than the whole budget
        # on its own, and a chunk of moderately-sized sample values.  The
        # guard should shorten the description and still emit all the
        # samples and the column metadata.
        long_description = "x" * (_MAX_PROMPT_CHARS * 2)
        samples = [f"sample_value_{i}_padding" for i in range(30)]
        column = ColumnInput(
            column_name="field_x",
            column_id="c1",
            table_name="big_table",
            description=long_description,
            sample_values=samples,
        )
        prompt = _build_ner_prompt(column, samples)

        # Truncation applied: prompt fits inside the character budget.
        assert len(prompt) <= _MAX_PROMPT_CHARS
        # Metadata survives truncation.
        assert "Column 'field_x'" in prompt
        assert "from table 'big_table'" in prompt
        assert "Description: " in prompt
        assert "..." in prompt  # ellipsis marker from truncation
        # ALL sample values still present — we shed description bytes,
        # not sample bytes.
        for s in samples:
            assert s in prompt


class TestS1PromptIntegratesWithInference:
    """Integration check: ``predict_entities`` receives the NL-wrapped text."""

    def test_predict_entities_receives_nl_prefixed_text(self, engine_with_mock, mock_gliner_model):
        """When column has metadata, GLiNER sees the NL-wrapped prompt."""
        mock_gliner_model.predict_entities.return_value = []
        column = ColumnInput(
            column_name="full_name",
            column_id="c1",
            table_name="employees",
            description="Employee legal name",
            sample_values=["John Smith", "Maria Garcia"],
        )
        engine_with_mock.classify_column(column)

        assert mock_gliner_model.predict_entities.called
        call = mock_gliner_model.predict_entities.call_args
        text_arg = call.args[0]
        assert "Column 'full_name'" in text_arg
        assert "from table 'employees'" in text_arg
        assert "Description: Employee legal name" in text_arg
        assert "Sample values: John Smith, Maria Garcia" in text_arg

    def test_predict_entities_receives_legacy_text_when_no_metadata(self, engine_with_mock, mock_gliner_model):
        """With no metadata the engine still emits the pre-S1 legacy shape."""
        mock_gliner_model.predict_entities.return_value = []
        column = ColumnInput(
            column_name="",
            column_id="c1",
            sample_values=["alpha", "beta"],
        )
        engine_with_mock.classify_column(column)

        assert mock_gliner_model.predict_entities.called
        call = mock_gliner_model.predict_entities.call_args
        text_arg = call.args[0]
        assert text_arg == "alpha ; beta"
        assert "Column '" not in text_arg


class TestOrgOverfireRegression:
    """Regression test for gliner2-over-fires-organization-on-numeric-dash-inputs.

    Pass 1 measured the baseline firing ORGANIZATION on ~25 columns at
    threshold 0.8 despite ORGANIZATION having zero ground-truth support in
    the corpus; S1 reduces this to ~8 false fires.  With the mock model
    configured to behave like baseline GLiNER (return an ORGANIZATION
    prediction on the raw bag-of-tokens input) this test proves that at
    threshold 0.8 an SSN-format column no longer surfaces an ORGANIZATION
    finding when wrapped with NL context.
    """

    def test_no_org_overfire_on_numeric_dash_at_threshold_08(self, mock_registry):
        """SSN-format values in an SSN-named column must not fire ORGANIZATION.

        Mocks GLiNER to return an ORGANIZATION prediction iff the raw
        bag-of-tokens prompt is used (legacy shape) AND no prediction when
        the S1 NL-wrapped prompt is used (which is what the research memo
        measured as the FP-suppression mechanism).  A failing assertion
        on the returned findings list therefore pins the engine to the
        S1 behavior by construction.
        """
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        mock_model = MagicMock()

        def _simulate_baseline_org_overfire(text, labels, threshold):
            # Baseline: raw " ; "-joined numeric-dash string triggers ORG.
            # S1: the NL-wrapped prompt with column/table metadata does not.
            if "Column 'ssn'" in text or "from table 'users'" in text:
                return []
            return [
                {"text": "123-45-6789", "label": "organization", "score": 0.87},
                {"text": "987-65-4321", "label": "organization", "score": 0.85},
            ]

        mock_model.predict_entities = MagicMock(side_effect=_simulate_baseline_org_overfire)

        engine = GLiNER2Engine(registry=mock_registry, gliner_threshold=0.8)
        mock_registry.register(
            "gliner2-ner",
            loader=lambda: mock_model,
            model_class="gliner.GLiNER",
            requires=[],
        )
        engine._registered = True

        column = ColumnInput(
            column_name="ssn",
            column_id="col_ssn",
            table_name="users",
            description="Social security number",
            sample_values=[
                "123-45-6789",
                "987-65-4321",
                "555-12-3456",
                "111-22-3333",
                "444-55-6666",
            ],
        )

        findings = engine.classify_column(column, min_confidence=0.0)

        entity_types = {f.entity_type for f in findings}
        assert "ORGANIZATION" not in entity_types, (
            "S1 NL-wrapping must suppress ORGANIZATION over-fire on numeric-dash "
            "inputs — regression against Sprint 8 bug "
            "gliner2-over-fires-organization-on-numeric-dash-inputs"
        )


# ── Test: Sprint 10 data_type pre-filter ────────────────────────────────────


_NON_TEXT_TYPES_CANONICAL = [
    "INTEGER",
    "INT64",
    "FLOAT",
    "FLOAT64",
    "NUMERIC",
    "BIGNUMERIC",
    "BOOLEAN",
    "BOOL",
    "TIMESTAMP",
    "DATE",
    "DATETIME",
    "TIME",
    "BYTES",
]


class TestDataTypePrefilter:
    """Sprint 10: GLiNER skips non-text SQL types entirely.

    The engine must return ``[]`` immediately for columns whose
    ``data_type`` is numeric/temporal/boolean/bytes — without invoking
    the underlying model or loading it into memory.  Text types
    (``""``, ``"STRING"``, ``"TEXT"``, ``"VARCHAR"``) and unknown
    types must fall through to the normal inference path.
    """

    def test_non_text_types_constant_membership(self):
        """_NON_TEXT_DATA_TYPES must contain exactly the 13 canonical types."""
        from data_classifier.engines.gliner_engine import _NON_TEXT_DATA_TYPES

        assert isinstance(_NON_TEXT_DATA_TYPES, frozenset)
        assert _NON_TEXT_DATA_TYPES == frozenset(_NON_TEXT_TYPES_CANONICAL)
        assert len(_NON_TEXT_DATA_TYPES) == 13

    @pytest.mark.parametrize("data_type", _NON_TEXT_TYPES_CANONICAL)
    def test_non_text_types_skipped(self, engine_with_mock, mock_gliner_model, data_type):
        """classify_column returns [] and never invokes the model on non-text types."""
        column = ColumnInput(
            column_name="value",
            column_id="c1",
            data_type=data_type,
            sample_values=["1", "2", "3"],
        )

        findings = engine_with_mock.classify_column(column)

        assert findings == []
        assert not mock_gliner_model.predict_entities.called
        assert not mock_gliner_model.extract_entities.called

    @pytest.mark.parametrize("data_type", ["integer", "Integer", "INTEGER", "iNtEgEr"])
    def test_case_insensitive(self, engine_with_mock, mock_gliner_model, data_type):
        """Case variants of non-text types all skip."""
        column = ColumnInput(
            column_name="amount",
            column_id="c1",
            data_type=data_type,
            sample_values=["42"],
        )

        findings = engine_with_mock.classify_column(column)

        assert findings == []
        assert not mock_gliner_model.predict_entities.called

    @pytest.mark.parametrize("data_type", ["", "STRING", "TEXT", "VARCHAR", "UNKNOWN_TYPE"])
    def test_text_types_fall_through(self, engine_with_mock, mock_gliner_model, data_type):
        """Text types and empty string still invoke the model."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({"person": [("John Smith", 0.92)]})
        column = ColumnInput(
            column_name="full_name",
            column_id="c1",
            data_type=data_type,
            sample_values=["John Smith", "Maria Garcia"],
        )

        engine_with_mock.classify_column(column)

        assert mock_gliner_model.predict_entities.called

    @pytest.mark.parametrize("data_type", ["string", "String", "text", "Text", "varchar"])
    def test_case_insensitive_fallthrough(self, engine_with_mock, mock_gliner_model, data_type):
        """Lowercase / mixed-case STRING/TEXT/VARCHAR must fall through to the model.

        Belt-and-suspenders: any data_type not in the non-text frozenset
        (after upper-casing) goes to the model regardless of case.
        """
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({"person": [("John Smith", 0.92)]})
        column = ColumnInput(
            column_name="full_name",
            column_id="c1",
            data_type=data_type,
            sample_values=["John Smith"],
        )

        engine_with_mock.classify_column(column)

        assert mock_gliner_model.predict_entities.called

    def test_batch_skip(self, engine_with_mock, mock_gliner_model):
        """classify_batch applies the skip per-column in the correct output order."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({"person": [("John Smith", 0.92)]})

        text_col = ColumnInput(
            column_name="full_name",
            column_id="c_text",
            data_type="STRING",
            sample_values=["John Smith"],
        )
        int_col = ColumnInput(
            column_name="user_id",
            column_id="c_int",
            data_type="INTEGER",
            sample_values=["42", "7", "99"],
        )
        ts_col = ColumnInput(
            column_name="created_at",
            column_id="c_ts",
            data_type="TIMESTAMP",
            sample_values=["2026-04-14T12:00:00Z"],
        )
        another_text_col = ColumnInput(
            column_name="email",
            column_id="c_text2",
            data_type="",  # empty falls through
            sample_values=["user@example.com"],
        )

        results = engine_with_mock.classify_batch([text_col, int_col, ts_col, another_text_col])

        assert len(results) == 4
        # Text column got findings from mocked model.
        assert len(results[0]) == 1
        assert results[0][0].entity_type == "PERSON_NAME"
        # Non-text columns were skipped entirely.
        assert results[1] == []
        assert results[2] == []
        # Empty-string data_type falls through to the model.
        assert len(results[3]) == 1

        # Model was called exactly twice — once per text column, zero on
        # the non-text columns.
        assert mock_gliner_model.predict_entities.call_count == 2

    def test_batch_mixed_with_empty_samples(self, engine_with_mock, mock_gliner_model):
        """Empty-sample non-text columns still yield [] without calling the model."""
        int_col_no_samples = ColumnInput(
            column_name="user_id",
            column_id="c_int",
            data_type="INTEGER",
            sample_values=[],
        )
        text_col_no_samples = ColumnInput(
            column_name="notes",
            column_id="c_text",
            data_type="STRING",
            sample_values=[],
        )

        results = engine_with_mock.classify_batch([int_col_no_samples, text_col_no_samples])

        assert results == [[], []]
        assert not mock_gliner_model.predict_entities.called


# ── Test: Sprint 14 promoted labels (AGE, HEALTH, FINANCIAL) ──────────────


class TestAgeDetection:
    """Test AGE detection — promoted from experimental in Sprint 14."""

    def test_detects_age_values(self, engine_with_mock, mock_gliner_model):
        """Engine should detect AGE from age-containing samples."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "age": [("72 years old", 0.88), ("age 45", 0.85), ("54 years old", 0.90)],
            }
        )
        column = ColumnInput(
            column_name="patient_age",
            column_id="col_age",
            sample_values=["72 years old", "age 45", "54 years old", "born in 1952", "31"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.5)
        assert len(findings) == 1
        assert findings[0].entity_type == "AGE"
        assert findings[0].engine == "gliner2"
        assert findings[0].confidence > 0.5

    def test_age_metadata(self, engine_with_mock, mock_gliner_model):
        """AGE findings should have correct category, sensitivity, and regulatory."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "age": [("age 45", 0.85), ("72 years old", 0.88)],
            }
        )
        column = ColumnInput(
            column_name="age",
            column_id="col_age",
            sample_values=["age 45", "72 years old"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].category == "PII"
        assert findings[0].sensitivity == "MEDIUM"
        assert "HIPAA" in findings[0].regulatory

    def test_age_sample_analysis(self, engine_with_mock, mock_gliner_model):
        """AGE finding should have correct sample analysis counts."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "age": [("72 years old", 0.88), ("age 45", 0.85)],
            }
        )
        column = ColumnInput(
            column_name="employee_age",
            column_id="col_age",
            sample_values=["72 years old", "age 45", "unknown"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert len(findings) == 1
        sa = findings[0].sample_analysis
        assert sa is not None
        assert sa.samples_scanned == 3
        assert sa.samples_matched == 2

    def test_age_negative_numeric_ids(self, engine_with_mock, mock_gliner_model):
        """Purely numeric IDs should not trigger AGE detection."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({})
        column = ColumnInput(
            column_name="record_id",
            column_id="col_id",
            sample_values=["1001", "1002", "1003", "1004"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert findings == []

    def test_age_negative_dates(self, engine_with_mock, mock_gliner_model):
        """Date strings should not trigger AGE detection."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({})
        column = ColumnInput(
            column_name="created_at",
            column_id="col_date",
            sample_values=["2024-01-15", "2023-06-30", "2022-12-01"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert findings == []


class TestHealthDetection:
    """Test HEALTH detection — promoted from experimental in Sprint 14."""

    def test_detects_medical_conditions(self, engine_with_mock, mock_gliner_model):
        """Engine should detect HEALTH from medical condition samples."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "medical condition": [
                    ("Type 2 diabetes", 0.92),
                    ("hypertension", 0.88),
                    ("metformin 500mg", 0.85),
                ],
            }
        )
        column = ColumnInput(
            column_name="diagnosis",
            column_id="col_health",
            sample_values=["Type 2 diabetes", "hypertension", "metformin 500mg", "aspirin 81mg", "N/A"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.5)
        assert len(findings) == 1
        assert findings[0].entity_type == "HEALTH"
        assert findings[0].engine == "gliner2"
        assert findings[0].confidence > 0.5

    def test_health_metadata(self, engine_with_mock, mock_gliner_model):
        """HEALTH findings should have correct category, sensitivity, and regulatory."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "medical condition": [("diabetes", 0.90), ("asthma", 0.87)],
            }
        )
        column = ColumnInput(
            column_name="condition",
            column_id="col_health",
            sample_values=["diabetes", "asthma"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].category == "Health"
        assert findings[0].sensitivity == "HIGH"
        assert "HIPAA" in findings[0].regulatory
        assert "GDPR" in findings[0].regulatory

    def test_health_sample_analysis(self, engine_with_mock, mock_gliner_model):
        """HEALTH finding should include matched condition texts."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "medical condition": [("Type 2 diabetes", 0.92)],
            }
        )
        column = ColumnInput(
            column_name="medical_notes",
            column_id="col_health",
            sample_values=["Type 2 diabetes", "healthy", "no issues"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert len(findings) == 1
        assert "Type 2 diabetes" in findings[0].sample_analysis.sample_matches

    def test_health_negative_person_names(self, engine_with_mock, mock_gliner_model):
        """Person names should not trigger HEALTH detection."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({})
        column = ColumnInput(
            column_name="doctor_name",
            column_id="col_doc",
            sample_values=["Dr. Smith", "Dr. Garcia", "Dr. Chen"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert findings == []

    def test_health_negative_status_codes(self, engine_with_mock, mock_gliner_model):
        """Generic status values should not trigger HEALTH detection."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({})
        column = ColumnInput(
            column_name="status",
            column_id="col_status",
            sample_values=["active", "inactive", "pending", "closed"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert findings == []


class TestFinancialDetection:
    """Test FINANCIAL detection — promoted from experimental in Sprint 14."""

    def test_detects_financial_values(self, engine_with_mock, mock_gliner_model):
        """Engine should detect FINANCIAL from salary/income samples."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "financial information": [
                    ("$85,000 annual salary", 0.91),
                    ("net worth $250,000", 0.87),
                    ("$4,500 monthly income", 0.89),
                ],
            }
        )
        column = ColumnInput(
            column_name="compensation",
            column_id="col_fin",
            sample_values=[
                "$85,000 annual salary",
                "net worth $250,000",
                "$4,500 monthly income",
                "$12,000 bonus",
                "N/A",
            ],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.5)
        assert len(findings) == 1
        assert findings[0].entity_type == "FINANCIAL"
        assert findings[0].engine == "gliner2"
        assert findings[0].confidence > 0.5

    def test_financial_metadata(self, engine_with_mock, mock_gliner_model):
        """FINANCIAL findings should have correct category, sensitivity, and regulatory."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "financial information": [("$85,000", 0.91), ("$120,000", 0.88)],
            }
        )
        column = ColumnInput(
            column_name="salary",
            column_id="col_fin",
            sample_values=["$85,000", "$120,000"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert len(findings) == 1
        assert findings[0].category == "Financial"
        assert findings[0].sensitivity == "HIGH"
        assert "GDPR" in findings[0].regulatory
        assert "CCPA" in findings[0].regulatory

    def test_financial_sample_analysis(self, engine_with_mock, mock_gliner_model):
        """FINANCIAL finding should have correct sample analysis."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions(
            {
                "financial information": [
                    ("$85,000 annual salary", 0.91),
                    ("net worth $250,000", 0.87),
                ],
            }
        )
        column = ColumnInput(
            column_name="income",
            column_id="col_fin",
            sample_values=["$85,000 annual salary", "net worth $250,000", "undisclosed"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert len(findings) == 1
        sa = findings[0].sample_analysis
        assert sa is not None
        assert sa.samples_scanned == 3
        assert sa.samples_matched == 2

    def test_financial_negative_phone_numbers(self, engine_with_mock, mock_gliner_model):
        """Phone numbers with digits should not trigger FINANCIAL detection."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({})
        column = ColumnInput(
            column_name="phone",
            column_id="col_phone",
            sample_values=["555-123-4567", "800-555-0199", "212-555-1234"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert findings == []

    def test_financial_negative_zip_codes(self, engine_with_mock, mock_gliner_model):
        """Zip codes should not trigger FINANCIAL detection."""
        mock_gliner_model.predict_entities.return_value = _gliner_predictions({})
        column = ColumnInput(
            column_name="postal_code",
            column_id="col_zip",
            sample_values=["10001", "90210", "60601", "02134"],
        )
        findings = engine_with_mock.classify_column(column, min_confidence=0.0)
        assert findings == []


class TestDemographicRemoval:
    """Test that DEMOGRAPHIC was removed from experimental labels (Sprint 14).

    The GLiNER model was silent on all tested descriptions for DEMOGRAPHIC.
    The entity type remains in standard.yaml for column-name-only detection
    but is not part of GLiNER inference.
    """

    def test_demographic_not_in_entity_label_descriptions(self):
        """DEMOGRAPHIC should not be in the core GLiNER label set."""
        from data_classifier.engines.gliner_engine import ENTITY_LABEL_DESCRIPTIONS

        assert "DEMOGRAPHIC" not in ENTITY_LABEL_DESCRIPTIONS

    def test_demographic_not_in_experimental_labels(self):
        """DEMOGRAPHIC should not be in the experimental label set."""
        from data_classifier.engines.gliner_engine import EXPERIMENTAL_LABEL_DESCRIPTIONS

        assert "DEMOGRAPHIC" not in EXPERIMENTAL_LABEL_DESCRIPTIONS

    def test_demographic_not_in_gliner_labels(self):
        """DEMOGRAPHIC should not be discoverable via the reverse label map."""
        from data_classifier.engines.gliner_engine import GLINER_LABEL_TO_ENTITY

        assert "DEMOGRAPHIC" not in GLINER_LABEL_TO_ENTITY.values()
