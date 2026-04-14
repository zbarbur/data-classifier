"""GLiNER2 NER classification engine — ML-based entity detection from sample values.

Uses GLiNER2 (a unified schema-based information extraction model) to detect
entity types in column sample values.  Entity descriptions provide semantic
context that significantly improves detection accuracy.

Order 5 in the engine cascade (after secret_scanner).  Only runs when the
``gliner2`` package is installed; raises ``ModelDependencyError`` otherwise.

The engine processes sample values in chunks, runs GLiNER2's
``extract_entities`` method with descriptions and confidence scores,
then maps results back to our entity taxonomy.
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
_MODEL_ID = "urchade/gliner_multi_pii-v1"
_REQUIRED_PACKAGES = ["gliner"]

# ── Entity type mapping with descriptions ─────────────────────────────────
#
# GLiNER2 uses descriptions as semantic context for better accuracy.
# Labels and descriptions were tested against real corpus samples.
# Format: entity_type -> (gliner_label, description)

ENTITY_LABEL_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "PERSON_NAME": (
        "person",
        "Names of people or individuals, including first and last names",
    ),
    "ADDRESS": (
        "street address",
        "Street names, roads, avenues, physical locations with or without house numbers",
    ),
    "ORGANIZATION": (
        "organization",
        "Company names, institutions, agencies, or other organizational entities",
    ),
    "DATE_OF_BIRTH": (
        "date of birth",
        "Dates representing when a person was born, in any format",
    ),
    "PHONE": (
        "phone number",
        "Telephone numbers in any international format with country codes, dashes, dots, or spaces",
    ),
    "SSN": (
        "national identification number",
        "Government-issued personal identification numbers such as SSN, national insurance, or tax ID",
    ),
    "EMAIL": (
        "email",
        "Email addresses including international domains and subdomains",
    ),
    "IP_ADDRESS": (
        "ip address",
        "IPv4 or IPv6 network addresses",
    ),
}

# Reverse mapping: GLiNER2 label -> our entity type
GLINER_LABEL_TO_ENTITY: dict[str, str] = {
    label: entity_type for entity_type, (label, _) in ENTITY_LABEL_DESCRIPTIONS.items()
}

# Entity metadata for findings
_ENTITY_METADATA: dict[str, dict[str, Any]] = {
    "PERSON_NAME": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA"]},
    "ADDRESS": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA"]},
    "ORGANIZATION": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": []},
    "DATE_OF_BIRTH": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA", "HIPAA"]},
    "DATE_OF_BIRTH_EU": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "HIPAA"]},
    "PHONE": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": ["GDPR", "CCPA"]},
    "SSN": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA", "HIPAA"]},
    "EMAIL": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": ["GDPR", "CCPA"]},
    "IP_ADDRESS": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": ["GDPR"]},
}

# Default confidence threshold for GLiNER2 predictions
_DEFAULT_GLINER_THRESHOLD = 0.5

# Separator used when concatenating sample values
_SAMPLE_SEPARATOR = " ; "

# Separator used inside the "Sample values: ..." clause of the NL-wrapped prompt.
# Sprint 10 S1 wrapping joins values with a comma + space, which is how GLiNER
# sees lists in its training distribution.
_NL_SAMPLE_SEPARATOR = ", "

# Max samples per NER chunk — keeps text within model's context window
_SAMPLE_CHUNK_SIZE = 50

# GLiNER urchade v1 encoder max_len (transformer max sequence length in tokens).
# The NL-wrapped prompt should stay comfortably inside this bound after
# tokenization.  We enforce a character budget that is empirically safe:
# at ~4 chars/token the 384-token transformer window fits ~1500 chars of input,
# plus we want headroom for the NL prefix.  The Sprint 10 research memo
# measured the baseline text at ~1500 chars at chunk_size=50 with 30-char
# mean values; the NL prefix adds ~150-300 chars, putting the worst case
# around 1800 chars.  We cap the assembled prompt at 2000 chars and
# truncate the description field first if we exceed it.
_MAX_PROMPT_CHARS = 2000

# When the description field alone pushes the prompt past the budget,
# truncate it down to this many characters with an ellipsis.  This
# preserves the column/table metadata (highest-signal context fields)
# and only sheds long catalog comments.
_DESCRIPTION_TRUNCATE_CHARS = 200

# Sprint 10: data_type pre-filter — skip GLiNER inference entirely when
# ``ColumnInput.data_type`` is a non-text SQL type on which NER cannot
# produce meaningful results.  Values are upper-cased before comparison;
# an empty ``data_type`` (legacy connectors / fall-through safety) always
# falls through to the model.  BQ connector populates this field in
# BigQuery UPPERCASE convention as of Sprint 10 (see
# docs/process/BQ_INTEGRATION_STATUS.md).
_NON_TEXT_DATA_TYPES: frozenset[str] = frozenset(
    {
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
    }
)


def _build_ner_prompt(column: ColumnInput, chunk: list[str]) -> str:
    """Build a natural-language NER prompt for GLiNER from column metadata + sample values.

    This is the Sprint 10 "S1" prompt-wrapping strategy from research/gliner-context
    Pass 1.  GLiNER is a context-attention NER model trained on natural-language
    sentences — feeding it raw "value ; value ; value" strings is out-of-distribution
    and causes ORGANIZATION/PERSON_NAME/PHONE false-fires on numeric-looking values.
    Wrapping the values in a sentence that mentions column/table/description metadata
    puts the input back in the model's training distribution and recovers +0.0887
    macro F1 on Ai4Privacy (BCa 95% CI [+0.050, +0.131], n=315).

    The helper is pure: no side effects, no logging, no model calls — safe to
    exercise in isolation under unit test.

    Shape rules:

    * If ``column.column_name`` is set: prepend ``Column '<column_name>'``.
    * If ``column.table_name`` is set: continue ``... from table '<table_name>'``
      (or start with it if column_name is empty).
    * If ``column.description`` is set: append ``. Description: <description>``
      (truncated to ``_DESCRIPTION_TRUNCATE_CHARS`` if the assembled prompt
      would exceed ``_MAX_PROMPT_CHARS``).
    * Always append ``. Sample values: <comma-joined chunk>`` or — when the
      column carries no metadata at all — fall back to the legacy
      ``_SAMPLE_SEPARATOR.join(chunk)`` shape so that metadata-free inputs
      get the exact same prompt the engine shipped before S1 wrapping
      (strictly additive change).

    Args:
        column: The ColumnInput whose metadata we're wrapping around the samples.
        chunk: A slice of ``column.sample_values`` to put in this prompt.

    Returns:
        The fully-assembled prompt string ready to hand to GLiNER.
    """
    column_name = (column.column_name or "").strip()
    table_name = (column.table_name or "").strip()
    description = (column.description or "").strip()

    # Metadata-free fallback: preserve pre-S1 production behavior so that
    # connectors which don't populate context fields see no behavior change.
    if not column_name and not table_name and not description:
        return _SAMPLE_SEPARATOR.join(chunk)

    # Build the NL prefix piece by piece, skipping empty parts.
    parts: list[str] = []
    if column_name and table_name:
        parts.append(f"Column '{column_name}' from table '{table_name}'")
    elif column_name:
        parts.append(f"Column '{column_name}'")
    elif table_name:
        parts.append(f"Table '{table_name}'")

    if description:
        parts.append(f"Description: {description}")

    sample_clause = f"Sample values: {_NL_SAMPLE_SEPARATOR.join(chunk)}"
    parts.append(sample_clause)

    prompt = ". ".join(parts)

    # Guard against overflow: if the description pushes the total past the
    # per-prompt character budget, truncate the description rather than
    # silently dropping sample values (samples are the actual signal GLiNER
    # needs; the description is secondary context).
    if len(prompt) > _MAX_PROMPT_CHARS and description:
        truncated_description = description[:_DESCRIPTION_TRUNCATE_CHARS].rstrip()
        if len(truncated_description) < len(description):
            truncated_description = f"{truncated_description}..."
        # Rebuild the prompt with the truncated description.
        parts = []
        if column_name and table_name:
            parts.append(f"Column '{column_name}' from table '{table_name}'")
        elif column_name:
            parts.append(f"Column '{column_name}'")
        elif table_name:
            parts.append(f"Table '{table_name}'")
        parts.append(f"Description: {truncated_description}")
        parts.append(sample_clause)
        prompt = ". ".join(parts)

    return prompt


def _find_bundled_onnx_model() -> str | None:
    """Search standard locations for a pre-exported ONNX model.

    Returns the first directory containing a GLiNER ONNX model, or None.

    Search order:
      1. ``{package_dir}/models/gliner_onnx/`` — bundled with the library
      2. ``~/.cache/data_classifier/models/gliner_onnx/`` — user cache
      3. ``/var/cache/data_classifier/models/gliner_onnx/`` — system cache
    """
    from pathlib import Path

    import data_classifier

    package_dir = Path(data_classifier.__file__).parent
    candidates = [
        package_dir / "models" / "gliner_onnx",
        Path.home() / ".cache" / "data_classifier" / "models" / "gliner_onnx",
        Path("/var/cache/data_classifier/models/gliner_onnx"),
    ]

    for path in candidates:
        if (path / "gliner_config.json").exists():
            logger.info("Auto-discovered ONNX model at %s", path)
            return str(path)
    return None


class GLiNER2Engine(ClassificationEngine):
    """GLiNER2-based NER classification engine.

    Uses GLiNER2 for zero-shot named entity recognition on column sample
    values with description-enhanced labels for higher accuracy.

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
        model_id: str = _MODEL_ID,
        onnx_path: str | None = None,
        api_key: str | None = None,
        descriptions_enabled: bool | None = None,
    ) -> None:
        """Initialize the GLiNER2 engine.

        Inference modes (tried in order):

        1. **ONNX local** — if ``onnx_path`` points to an exported model dir.
           Fastest load (3s vs 14s), no HuggingFace download, production-ready.
        2. **Local model** — downloads from HuggingFace or loads from cache.
        3. **API fallback** — if ``api_key`` set and local loading fails,
           calls the GLiNER hosted API (gliner.pioneer.ai).

        Args:
            registry: Model registry for lazy loading.
            gliner_threshold: Minimum prediction score to accept.
            entity_types: Entity types to detect.  Defaults to all mapped types.
            model_id: HuggingFace model ID.  Defaults to the PII-tuned model.
            onnx_path: Path to pre-exported ONNX model directory.  If set,
                loads from local ONNX files (faster, no HF download needed).
                If None, auto-discovers from standard locations (package
                ``models/`` dir, user cache, system cache).
                Export with: ``model.export_to_onnx(path, quantize=True)``
            api_key: GLiNER API key for hosted inference fallback.  If set
                and local model loading fails, falls back to API mode.
            descriptions_enabled: Controls whether entity descriptions are
                passed to the underlying model's v2 ``extract_entities``
                schema.  ``None`` (the default) auto-selects: ``False``
                for ``fastino/*`` (v2) models, ``True`` for all other
                models.  The Sprint 9 GLiNER eval memo showed fastino
                regresses by -0.062 to -0.093 macro F1 when descriptions
                are enabled, so the infrastructure supports running
                fastino without them.  v1 (``gliner``) models ignore this
                flag because they only accept a label list.  Infrastructure
                shipped Sprint 9 ahead of the fastino model swap (blocked
                on blind-corpus regression pending the research/gliner-context
                work).
        """
        self._registry = registry or ModelRegistry()
        self._gliner_threshold = gliner_threshold
        self._model_id = model_id
        self._api_key = api_key
        self._is_v2 = model_id.startswith("fastino/")
        # Auto-discover ONNX model if not explicitly configured.
        # Sprint 9: skip auto-discovery for v2 (fastino) models — the
        # bundled/cached ONNX bundles in the standard search paths are
        # v1 exports (``urchade/gliner_multi_pii-v1``) and would be
        # loaded by the v1 ``gliner`` package, silently serving the
        # wrong model.  An explicitly-provided ``onnx_path`` still wins
        # (escape hatch for a hand-exported fastino bundle).
        if onnx_path:
            self._onnx_path: str | None = onnx_path
        elif self._is_v2:
            self._onnx_path = None
        else:
            self._onnx_path = _find_bundled_onnx_model()
        self._inference_mode: str | None = None  # set during startup
        self._registered = False

        # Sprint 9: descriptions-off default for fastino per the eval memo.
        # v1 models ignore this flag at inference time (they only accept a
        # label list via ``predict_entities``), but it's still set for
        # consistency and testability.
        if descriptions_enabled is None:
            descriptions_enabled = not self._is_v2
        self._descriptions_enabled = descriptions_enabled

        # Filter to requested entity types (must be in our mapping)
        if entity_types is not None:
            self._entity_types = [et for et in entity_types if et in ENTITY_LABEL_DESCRIPTIONS]
        else:
            self._entity_types = list(ENTITY_LABEL_DESCRIPTIONS.keys())

        # Build labels.
        #
        # v1 (gliner) uses a plain label list via ``predict_entities``.
        #
        # v2 (gliner2) ``extract_entities`` accepts either a list[str]
        # (no descriptions) or dict[str, str] (label -> description).
        # Prepare BOTH forms and pick at inference time based on
        # ``self._descriptions_enabled``.
        self._gliner_labels: list[str] = [ENTITY_LABEL_DESCRIPTIONS[et][0] for et in self._entity_types]
        if self._is_v2:
            self._gliner_labels_v2: dict[str, str] = {
                ENTITY_LABEL_DESCRIPTIONS[et][0]: ENTITY_LABEL_DESCRIPTIONS[et][1] for et in self._entity_types
            }

    def startup(self) -> None:
        """Register the model in the registry for lazy loading.

        Tries modes in order: ONNX local → HuggingFace model → API fallback.
        """
        if not self._registered:
            model_id = self._model_id
            is_v2 = self._is_v2
            onnx_path = self._onnx_path
            api_key = self._api_key

            def _loader() -> Any:
                # Mode 1: ONNX local
                if onnx_path:
                    from gliner import GLiNER  # type: ignore[import-not-found]

                    logger.info("Loading GLiNER from ONNX: %s", onnx_path)
                    return GLiNER.from_pretrained(onnx_path, load_onnx_model=True, load_tokenizer=True)

                # Mode 2: Local model (HuggingFace download/cache)
                try:
                    if is_v2:
                        from gliner2 import GLiNER2  # type: ignore[import-not-found]

                        return GLiNER2.from_pretrained(model_id)
                    else:
                        from gliner import GLiNER  # type: ignore[import-not-found]

                        return GLiNER.from_pretrained(model_id)
                except Exception:
                    if not api_key:
                        raise
                    logger.warning("Local model load failed, falling back to API mode")

                # Mode 3: API fallback
                from gliner2 import GLiNER2  # type: ignore[import-not-found]

                logger.info("Using GLiNER API mode")
                return GLiNER2.from_api(api_key=api_key)

            pkg = "gliner2" if is_v2 else "gliner"
            cls = "gliner2.GLiNER2" if is_v2 else "gliner.GLiNER"
            try:
                self._registry.register(
                    _MODEL_NAME,
                    loader=_loader,
                    model_class=cls,
                    requires=[pkg],
                )
            except ValueError:
                pass  # Already registered
            self._registered = True

        mode = "onnx" if self._onnx_path else "local"
        logger.info("GLiNER2Engine: registered '%s' (%s, mode=%s)", _MODEL_NAME, self._model_id, mode)

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
            ModelDependencyError: If gliner2 package is not installed.
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

        Processes sample values in chunks, runs NER with descriptions,
        and maps predictions back to our entity taxonomy.
        """
        # Sprint 10: skip numeric/temporal/boolean/bytes columns entirely
        # before any model load.  NER cannot produce meaningful results on
        # these types and running inference burns latency + generates false
        # positives.  Empty ``data_type`` falls through (legacy connectors).
        if column.data_type and column.data_type.upper() in _NON_TEXT_DATA_TYPES:
            return []

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
        """Classify multiple columns, delegating to classify_column per column."""
        if not columns:
            return []

        model = self._get_model()
        return [
            self._run_ner_on_samples(
                model=model,
                column=col,
                min_confidence=min_confidence,
                mask_samples=mask_samples,
                max_evidence_samples=max_evidence_samples,
            )
            # Sprint 10: per-column data_type pre-filter — skip non-text types
            # (numeric/temporal/boolean/bytes) entirely and emit an empty
            # finding list in the corresponding output slot, matching
            # classify_column's early-return contract.
            if col.sample_values and not (col.data_type and col.data_type.upper() in _NON_TEXT_DATA_TYPES)
            else []
            for col in columns
        ]

    def _run_ner_on_samples(
        self,
        *,
        model: Any,
        column: ColumnInput,
        min_confidence: float,
        mask_samples: bool,
        max_evidence_samples: int,
    ) -> list[ClassificationFinding]:
        """Run GLiNER2 NER on a column's sample values in chunks.

        Processes samples in small chunks to stay within the model's
        context window.  Aggregates predictions across all chunks.
        """
        # Collect predictions from all chunks: {entity_type: [(text, confidence), ...]}
        entity_hits: dict[str, list[tuple[str, float]]] = {}

        for i in range(0, len(column.sample_values), _SAMPLE_CHUNK_SIZE):
            chunk = column.sample_values[i : i + _SAMPLE_CHUNK_SIZE]
            # Sprint 10 S1: wrap sample values in a natural-language sentence
            # mentioning column/table/description metadata so that GLiNER
            # sees training-distribution input instead of a raw bag-of-tokens
            # ``value ; value ; value`` string.  See _build_ner_prompt for the
            # metadata-graceful-degradation rules.
            text = _build_ner_prompt(column, chunk)

            try:
                if self._is_v2:
                    # Sprint 9: pick label spec form based on descriptions_enabled.
                    # - descriptions_enabled=True  -> dict[label, description]
                    # - descriptions_enabled=False -> list[label] (fastino default)
                    # Also plumb threshold through — the v2 path previously
                    # silently ignored self._gliner_threshold and used
                    # extract_entities' internal default, which was a latent
                    # correctness bug affecting any v2 deployment.
                    v2_entity_spec: list[str] | dict[str, str] = (
                        self._gliner_labels_v2 if self._descriptions_enabled else self._gliner_labels
                    )
                    result = model.extract_entities(
                        text,
                        v2_entity_spec,
                        threshold=self._gliner_threshold,
                        include_confidence=True,
                    )
                    for gliner_label, matches in result.get("entities", {}).items():
                        entity_type = GLINER_LABEL_TO_ENTITY.get(gliner_label)
                        if entity_type is None:
                            continue
                        for match in matches:
                            if isinstance(match, dict):
                                entity_hits.setdefault(entity_type, []).append(
                                    (match.get("text", ""), match.get("confidence", 0.5))
                                )
                            else:
                                entity_hits.setdefault(entity_type, []).append((str(match), 0.5))
                else:
                    preds = model.predict_entities(text, self._gliner_labels, threshold=self._gliner_threshold)
                    for pred in preds:
                        entity_type = GLINER_LABEL_TO_ENTITY.get(pred.get("label", ""))
                        if entity_type is None:
                            continue
                        entity_hits.setdefault(entity_type, []).append((pred.get("text", ""), pred.get("score", 0.0)))
            except Exception:
                logger.exception("GLiNER inference failed on chunk %d for column %s", i, column.column_id)
                continue

        return self._hits_to_findings(
            entity_hits=entity_hits,
            column=column,
            min_confidence=min_confidence,
            mask_samples=mask_samples,
            max_evidence_samples=max_evidence_samples,
        )

    def _hits_to_findings(
        self,
        *,
        entity_hits: dict[str, list[tuple[str, float]]],
        column: ColumnInput,
        min_confidence: float,
        mask_samples: bool,
        max_evidence_samples: int,
    ) -> list[ClassificationFinding]:
        """Convert aggregated GLiNER2 hits into ClassificationFindings."""
        findings: list[ClassificationFinding] = []
        total_samples = len(column.sample_values)

        for entity_type, hits in entity_hits.items():
            count = len(hits)
            scores = [conf for _, conf in hits]
            avg_score = sum(scores) / len(scores) if scores else 0.0
            max_score = max(scores) if scores else 0.0

            # Confidence: use average, scaled by hit density
            if count == 1:
                confidence = avg_score * 0.85
            elif count <= 3:
                confidence = avg_score * 0.95
            else:
                confidence = min(avg_score * 1.05, 1.0)

            if confidence < min_confidence:
                continue

            # Build evidence
            matched_texts = [text for text, _ in hits[:max_evidence_samples]]
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

        return _deduplicate_gliner_findings(findings)


# More specific entity types suppress more general ones when both are found
_SPECIFICITY_ORDER: dict[str, int] = {
    "ADDRESS": 3,
    "DATE_OF_BIRTH": 3,
    "SSN": 3,
    "EMAIL": 3,
    "IP_ADDRESS": 3,
    "PHONE": 3,
    "ORGANIZATION": 2,
    "PERSON_NAME": 1,
}


def _deduplicate_gliner_findings(findings: list[ClassificationFinding]) -> list[ClassificationFinding]:
    """When GLiNER2 finds overlapping entity types, keep the more specific one.

    Example: ADDRESS and PERSON_NAME both found → keep ADDRESS (street names
    contain words that look like names).
    """
    if len(findings) <= 1:
        return findings

    # Sort by specificity (highest first), then confidence
    findings.sort(key=lambda f: (_SPECIFICITY_ORDER.get(f.entity_type, 0), f.confidence), reverse=True)
    top = findings[0]
    top_spec = _SPECIFICITY_ORDER.get(top.entity_type, 0)

    # Suppress less-specific types when confidence gap is small
    kept = [top]
    for f in findings[1:]:
        f_spec = _SPECIFICITY_ORDER.get(f.entity_type, 0)
        if f_spec < top_spec and top.confidence - f.confidence < 0.3:
            continue  # Suppress less-specific type
        kept.append(f)
    return kept


def _mask_ner_value(value: str) -> str:
    """Mask a detected NER value for evidence display."""
    if len(value) <= 3:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]
