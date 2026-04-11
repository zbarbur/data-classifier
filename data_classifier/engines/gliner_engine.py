"""GLiNER2 NER classification engine — ML-based entity detection from sample values.

Uses the GLiNER2 model (a zero-shot NER model that accepts entity labels at
inference time) to detect entity types in column sample values.  Targets
entity types where sample value analysis adds value beyond regex:
PERSON_NAME, ADDRESS, ORGANIZATION, DATE_OF_BIRTH.

Order 5 in the engine cascade (after secret_scanner).  Only runs when the
``gliner`` package is installed; raises ``ModelDependencyError`` otherwise.

The engine concatenates sample values into text blocks and runs GLiNER2's
``predict_entities`` method.  Predictions are mapped back to our entity
taxonomy and filtered by confidence threshold.
"""

from __future__ import annotations

import logging
from typing import Any

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
    SampleAnalysis,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.registry import ModelRegistry

logger = logging.getLogger(__name__)

# ── GLiNER2 model configuration ────────────────────────────────────────────

_MODEL_NAME = "gliner2-ner"
_MODEL_ID = "urchade/gliner_medium-v2.1"
_REQUIRED_PACKAGES = ["gliner"]

# ── Entity type mapping ────────────────────────────────────────────────────
#
# Maps our internal entity types to natural language labels that GLiNER2
# understands.  We only target entity types where NER on sample values
# adds value over regex pattern matching.

ENTITY_TO_GLINER_LABEL: dict[str, str] = {
    "PERSON_NAME": "person name",
    "ADDRESS": "physical address",
    "ORGANIZATION": "organization",
    "DATE_OF_BIRTH": "date of birth",
}

# Reverse mapping: GLiNER2 label -> our entity type
GLINER_LABEL_TO_ENTITY: dict[str, str] = {v: k for k, v in ENTITY_TO_GLINER_LABEL.items()}

# Entity metadata for findings
_ENTITY_METADATA: dict[str, dict[str, Any]] = {
    "PERSON_NAME": {
        "category": "PII",
        "sensitivity": "HIGH",
        "regulatory": ["GDPR", "CCPA"],
    },
    "ADDRESS": {
        "category": "PII",
        "sensitivity": "HIGH",
        "regulatory": ["GDPR", "CCPA"],
    },
    "ORGANIZATION": {
        "category": "PII",
        "sensitivity": "MEDIUM",
        "regulatory": [],
    },
    "DATE_OF_BIRTH": {
        "category": "PII",
        "sensitivity": "HIGH",
        "regulatory": ["GDPR", "CCPA", "HIPAA"],
    },
}

# Default confidence threshold for GLiNER2 predictions
_DEFAULT_GLINER_THRESHOLD = 0.5

# Separator used when concatenating sample values
_SAMPLE_SEPARATOR = " ; "


def _load_gliner_model() -> Any:
    """Load the GLiNER2 model.  Called lazily by the ModelRegistry."""
    from gliner import GLiNER  # type: ignore[import-not-found]

    model = GLiNER.from_pretrained(_MODEL_ID)
    return model


class GLiNER2Engine(ClassificationEngine):
    """GLiNER2-based NER classification engine.

    Uses GLiNER2 for zero-shot named entity recognition on column sample
    values.  Targets entity types where regex is insufficient: PERSON_NAME,
    ADDRESS, ORGANIZATION, DATE_OF_BIRTH.

    Order 5 in the cascade (after secret_scanner).  Only participates
    in ``structured`` mode.
    """

    name = "gliner2"
    order = 5
    min_confidence = 0.0
    supported_modes = frozenset({"structured"})

    def __init__(
        self,
        *,
        registry: ModelRegistry | None = None,
        gliner_threshold: float = _DEFAULT_GLINER_THRESHOLD,
        entity_types: list[str] | None = None,
    ) -> None:
        """Initialize the GLiNER2 engine.

        Args:
            registry: Model registry for lazy loading.  Uses a private
                registry if not provided.
            gliner_threshold: Minimum GLiNER2 prediction score to accept.
            entity_types: Entity types to detect.  Defaults to all mapped types.
        """
        self._registry = registry or ModelRegistry()
        self._gliner_threshold = gliner_threshold
        self._registered = False

        # Filter to requested entity types (must be in our mapping)
        if entity_types is not None:
            self._entity_types = [et for et in entity_types if et in ENTITY_TO_GLINER_LABEL]
        else:
            self._entity_types = list(ENTITY_TO_GLINER_LABEL.keys())

        # Build the labels list for GLiNER2 inference
        self._gliner_labels = [ENTITY_TO_GLINER_LABEL[et] for et in self._entity_types]

    def startup(self) -> None:
        """Register the GLiNER2 model in the registry for lazy loading."""
        if not self._registered:
            try:
                self._registry.register(
                    _MODEL_NAME,
                    loader=_load_gliner_model,
                    model_class="gliner.GLiNER",
                    requires=_REQUIRED_PACKAGES,
                )
            except ValueError:
                # Already registered (e.g. by another engine instance)
                pass
            self._registered = True
        logger.info("GLiNER2Engine: registered model '%s' for lazy loading", _MODEL_NAME)

    def shutdown(self) -> None:
        """Unload the GLiNER2 model to free memory."""
        try:
            if self._registry.is_loaded(_MODEL_NAME):
                self._registry.unload(_MODEL_NAME)
        except KeyError:
            pass

    def _ensure_started(self) -> None:
        """Lazy startup if not explicitly called."""
        if not self._registered:
            self.startup()

    def _get_model(self) -> Any:
        """Get the GLiNER2 model, loading lazily.

        Raises:
            ModelDependencyError: If gliner package is not installed.
        """
        self._ensure_started()
        return self._registry.get(_MODEL_NAME)

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Classify a column by running GLiNER2 NER on sample values.

        Concatenates sample values into a text block, runs NER, and maps
        predictions back to our entity taxonomy.

        Args:
            column: Column to classify.
            profile: Classification profile (not used by this engine).
            min_confidence: Minimum confidence for returned findings.
            mask_samples: Whether to redact evidence samples.
            max_evidence_samples: Max evidence samples per finding.

        Returns:
            List of classification findings from NER predictions.

        Raises:
            ModelDependencyError: If gliner package is not installed.
        """
        if not column.sample_values:
            return []

        model = self._get_model()
        return self._run_ner_on_samples(
            model=model,
            column=column,
            min_confidence=min_confidence,
            mask_samples=mask_samples,
            max_evidence_samples=max_evidence_samples,
        )

    def classify_batch(
        self,
        columns: list[ColumnInput],
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[list[ClassificationFinding]]:
        """Classify multiple columns with batched GLiNER2 inference.

        Prepares all text blocks and runs ``batch_predict_entities`` once
        for efficient GPU utilization, then maps results back per-column.

        Args:
            columns: Columns to classify.
            profile: Classification profile (not used by this engine).
            min_confidence: Minimum confidence for returned findings.
            mask_samples: Whether to redact evidence samples.
            max_evidence_samples: Max evidence samples per finding.

        Returns:
            List of finding-lists, one per input column.

        Raises:
            ModelDependencyError: If gliner package is not installed.
        """
        if not columns:
            return []

        model = self._get_model()

        # Build text blocks for all columns that have samples
        texts: list[str] = []
        column_indices: list[int] = []  # maps text index -> column index
        for i, col in enumerate(columns):
            if col.sample_values:
                texts.append(_SAMPLE_SEPARATOR.join(col.sample_values))
                column_indices.append(i)

        # Initialize results
        all_results: list[list[ClassificationFinding]] = [[] for _ in columns]

        if not texts:
            return all_results

        # Batch predict
        try:
            batch_predictions = model.batch_predict_entities(
                texts,
                self._gliner_labels,
                threshold=self._gliner_threshold,
            )
        except AttributeError:
            # Fallback if batch_predict_entities is not available
            batch_predictions = [
                model.predict_entities(text, self._gliner_labels, threshold=self._gliner_threshold) for text in texts
            ]

        # Map predictions back to columns
        for text_idx, predictions in enumerate(batch_predictions):
            col_idx = column_indices[text_idx]
            column = columns[col_idx]
            findings = self._predictions_to_findings(
                predictions=predictions,
                column=column,
                min_confidence=min_confidence,
                mask_samples=mask_samples,
                max_evidence_samples=max_evidence_samples,
            )
            all_results[col_idx] = findings

        return all_results

    def _run_ner_on_samples(
        self,
        *,
        model: Any,
        column: ColumnInput,
        min_confidence: float,
        mask_samples: bool,
        max_evidence_samples: int,
    ) -> list[ClassificationFinding]:
        """Run GLiNER2 NER on a single column's sample values."""
        text = _SAMPLE_SEPARATOR.join(column.sample_values)
        predictions = model.predict_entities(text, self._gliner_labels, threshold=self._gliner_threshold)
        return self._predictions_to_findings(
            predictions=predictions,
            column=column,
            min_confidence=min_confidence,
            mask_samples=mask_samples,
            max_evidence_samples=max_evidence_samples,
        )

    def _predictions_to_findings(
        self,
        *,
        predictions: list[dict],
        column: ColumnInput,
        min_confidence: float,
        mask_samples: bool,
        max_evidence_samples: int,
    ) -> list[ClassificationFinding]:
        """Convert GLiNER2 predictions into ClassificationFindings.

        Groups predictions by entity type, computes aggregate confidence,
        and builds evidence strings.
        """
        # Group predictions by entity type
        entity_groups: dict[str, list[dict]] = {}
        for pred in predictions:
            label = pred.get("label", "")
            entity_type = GLINER_LABEL_TO_ENTITY.get(label)
            if entity_type is None:
                continue
            entity_groups.setdefault(entity_type, []).append(pred)

        findings: list[ClassificationFinding] = []
        total_samples = len(column.sample_values)

        for entity_type, preds in entity_groups.items():
            # Compute aggregate confidence from individual prediction scores
            scores = [p.get("score", 0.0) for p in preds]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            max_score = max(scores) if scores else 0.0

            # Use max score as confidence, boosted by count
            count = len(preds)
            if count == 1:
                confidence = avg_score * 0.85
            elif count <= 3:
                confidence = avg_score * 0.95
            else:
                confidence = min(avg_score * 1.05, 1.0)

            if confidence < min_confidence:
                continue

            # Build evidence
            matched_texts = [p.get("text", "") for p in preds[:max_evidence_samples]]
            if mask_samples:
                matched_texts = [_mask_ner_value(t) for t in matched_texts]

            metadata = _ENTITY_METADATA.get(entity_type, {})

            match_ratio = count / total_samples if total_samples > 0 else 0.0

            findings.append(
                ClassificationFinding(
                    column_id=column.column_id,
                    entity_type=entity_type,
                    category=metadata.get("category", "PII"),
                    sensitivity=metadata.get("sensitivity", "HIGH"),
                    confidence=round(confidence, 4),
                    regulatory=metadata.get("regulatory", []),
                    engine=self.name,
                    evidence=(
                        f"GLiNER2 NER: {entity_type} detected in "
                        f"{count}/{total_samples} sample regions "
                        f"(avg_score={avg_score:.2f}, max_score={max_score:.2f})"
                    ),
                    sample_analysis=SampleAnalysis(
                        samples_scanned=total_samples,
                        samples_matched=count,
                        samples_validated=count,
                        match_ratio=match_ratio,
                        sample_matches=matched_texts,
                    ),
                )
            )

        return findings


def _mask_ner_value(value: str) -> str:
    """Mask a detected NER value for evidence display."""
    if len(value) <= 3:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]
