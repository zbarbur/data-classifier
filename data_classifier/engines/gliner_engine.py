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

import hashlib
import logging
import re
from typing import Any

from data_classifier.config import load_engine_config
from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
    SampleAnalysis,
    SpanDetection,
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
    # ── Promoted from experimental (Sprint 14) ──────────────────────────
    # These three labels were added as experimental in Sprint 13 and
    # manually validated: AGE fires cleanly on HR data, HEALTH fires on
    # medical notes, FINANCIAL fires on salary data.  DEMOGRAPHIC was
    # removed — the GLiNER model is silent on all tested descriptions.
    "AGE": (
        "age",
        "A person's age in years, including phrases like '72 years old', 'age 45', or 'born in 1952'",
    ),
    "HEALTH": (
        "medical condition",
        "Medical diagnoses, conditions, treatments, or medications such as diabetes, hypertension, or metformin",
    ),
    "FINANCIAL": (
        "financial information",
        "Salary, income, net worth, loan amounts, or account balances expressed in text",
    ),
}

# No experimental labels remain — all viable Sprint 13 candidates have
# been promoted.  DEMOGRAPHIC was removed after testing 5 alternative
# descriptions ("demographic information", "race ethnicity gender",
# "demographic category", "population demographic data",
# "census demographic classification") — the GLiNER model is silent on
# all of them.  The entity type remains in standard.yaml for
# column-name-only detection.
EXPERIMENTAL_LABEL_DESCRIPTIONS: dict[str, tuple[str, str]] = {}

# Merge experimental into the active label set.
_ALL_LABEL_DESCRIPTIONS: dict[str, tuple[str, str]] = {**ENTITY_LABEL_DESCRIPTIONS, **EXPERIMENTAL_LABEL_DESCRIPTIONS}

# Reverse mapping: GLiNER2 label -> our entity type
GLINER_LABEL_TO_ENTITY: dict[str, str] = {
    label: entity_type for entity_type, (label, _) in _ALL_LABEL_DESCRIPTIONS.items()
}

# Entity metadata for findings
_ENTITY_METADATA: dict[str, dict[str, Any]] = {
    "PERSON_NAME": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA"]},
    "ADDRESS": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA"]},
    "ORGANIZATION": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": []},
    "DATE_OF_BIRTH": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA", "HIPAA"]},
    "PHONE": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": ["GDPR", "CCPA"]},
    "SSN": {"category": "PII", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA", "HIPAA"]},
    "EMAIL": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": ["GDPR", "CCPA"]},
    "IP_ADDRESS": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": ["GDPR"]},
    # Promoted from experimental (Sprint 14)
    "AGE": {"category": "PII", "sensitivity": "MEDIUM", "regulatory": ["HIPAA"]},
    "HEALTH": {"category": "Health", "sensitivity": "HIGH", "regulatory": ["HIPAA", "GDPR"]},
    "FINANCIAL": {"category": "Financial", "sensitivity": "HIGH", "regulatory": ["GDPR", "CCPA"]},
}

# Default confidence threshold for GLiNER2 predictions
_DEFAULT_GLINER_THRESHOLD = 0.50

# ── Sprint 18 stop-gap: count==1 ORGANIZATION FP guard ──────────────
# GLiNER fires high-confidence ORGANIZATION on Faker catch_phrase
# buzzwords like "Quality-focused secondary alliance" (raw scores up to
# 0.98) when a column has no contextual signal. Multi-row columns are
# saved by avg-confidence aggregation in _hits_to_findings, but
# count==1 columns bypass that safeguard. This rule requires either
# a column-name signal OR a value-side structural suffix before
# accepting count==1 ORG findings.
#
# This is a STOP-GAP, not the endgame: the proper fix is the LLM
# escalation layer tracked as backlog item
# `research-slm-llm-escalation-architecture-for-low-precision-ner-labels`
# (P3, no sprint target). When that ships, this guard should be
# removed cleanly. See MEMORY:project_future_slm_to_llm_escalation
# for the architectural rationale.
#
# Deliberately narrow per memory guidance "don't over-tune SLM
# suppression breadth": leaks to legitimate single-token org names
# in unnamed columns (e.g., "Microsoft" alone in column "value")
# are tolerated as future-LLM-escalation territory.
_ORG_CONTEXT_NAMES_RE = re.compile(
    r"\b(company|org|organization|organisation|vendor|client|"
    r"customer|account|institution|agency|firm|corporation|"
    r"provider|publisher|employer)\b|_name$",
    re.IGNORECASE,
)
_ORG_SUFFIX_RE = re.compile(
    r"\b(inc\.?|llc|corp\.?|corporation|ltd\.?|co\.?|gmbh|ag|sa|nv|bv|s\.r\.l|"
    r"plc|company|incorporated|university|institute|academy)\b",
    re.IGNORECASE,
)

# ── Sprint 18 stop-gap: count==1 PERSON_NAME common-noun FP filter ──
# Sister item to the ORG guard. GLiNER fires PERSON_NAME on lowercase
# common nouns embedded in template prose like "A worker transforms..."
# — the matched span is just "worker" (lowercase, single token).
# Real person names ("John Smith", "Maria García", "李明") are
# capitalized or use non-cased scripts. An all-lowercase matched span
# on PERSON_NAME is a near-perfect signal of common-noun confusion.
#
# Same removable-stop-gap rationale as _ORG_CONTEXT_NAMES_RE: replaced
# by LLM escalation layer (see backlog item
# research-slm-llm-escalation-architecture-for-low-precision-ner-labels).
#
# Documented collateral: casual lowercase real names in chat ("my
# friend bob said...") would be dropped. Rare in production data,
# acceptable per memory project_future_slm_to_llm_escalation.
# Determiners that precede common nouns in English template prose.
# A PERSON_NAME span starting with one of these followed by a
# lowercase word ('A worker', 'The handler') is almost certainly a
# common-noun FP, not a real name.
_PERSON_NAME_DETERMINERS: tuple[str, ...] = (
    "A ",
    "An ",
    "The ",
    "Each ",
    "Every ",
    "Some ",
    "No ",
    "Any ",
    "All ",
    "This ",
    "That ",
)


def _is_lowercase_common_noun_person_span(span: str) -> bool:
    """True if the matched span is a common-noun FP candidate.

    Catches two forms GLiNER returns on template prose:
      - ``'worker'`` — entirely lowercase single token
      - ``'A worker'`` — determiner-led with lowercase head noun

    str.islower() returns True iff there's at least one cased
    character and all cased characters are lowercase. Spans in
    non-cased scripts (Arabic, Chinese, Hebrew) therefore return
    False and pass through, as do capitalized names like
    ``'John Smith'`` or ``'Maria García'``.
    """
    if not span:
        return False
    if span.islower():
        return True
    for det in _PERSON_NAME_DETERMINERS:
        if span.startswith(det):
            rest = span[len(det) :]
            if rest and rest[0].islower():
                return True
    return False


# Separator used when concatenating sample values
_SAMPLE_SEPARATOR = " ; "

# Separator used inside the "Sample values: ..." clause of the NL-wrapped prompt.
# Sprint 10 S1 wrapping joins values with a comma + space, which is how GLiNER
# sees lists in its training distribution.
_NL_SAMPLE_SEPARATOR = ", "

# Max samples per NER chunk — keeps text within model's context window
_SAMPLE_CHUNK_SIZE = 50

# GLiNER encoder max_len (transformer max sequence length in tokens).
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


_DEFAULT_PER_VALUE_SAMPLE_SIZE: int = 60


def _load_per_value_sample_size() -> int:
    """Read the per-value sample-size cap from engine_defaults.yaml."""
    try:
        cfg = load_engine_config().get("gliner_engine", {}) or {}
        value = cfg.get("per_value_sample_size", _DEFAULT_PER_VALUE_SAMPLE_SIZE)
        if isinstance(value, int) and value > 0:
            return value
    except Exception:
        logger.exception("Failed to load per_value_sample_size; falling back to default")
    return _DEFAULT_PER_VALUE_SAMPLE_SIZE


def _stable_subsample(values: list[str], *, n: int) -> list[str]:
    """Deterministically pick up to n values by stable hash.

    SHA-1 of the UTF-8-encoded value as the sort key. Output is
    insertion-order-independent: two orchestrators that receive the same
    set of values in different orders produce the same sampled set.
    """
    if n <= 0 or not values:
        return []
    if len(values) <= n:
        return list(values)

    def _key(v: str) -> bytes:
        return hashlib.sha1(v.encode("utf-8", errors="replace")).digest()

    return sorted(values, key=_key)[:n]


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

        # Filter to requested entity types (must be in our mapping).
        # Uses _ALL_LABEL_DESCRIPTIONS (core + experimental) so the model
        # sees the experimental labels during inference.
        if entity_types is not None:
            self._entity_types = [et for et in entity_types if et in _ALL_LABEL_DESCRIPTIONS]
        else:
            self._entity_types = list(_ALL_LABEL_DESCRIPTIONS.keys())

        # Build labels.
        #
        # v1 (gliner) uses a plain label list via ``predict_entities``.
        #
        # v2 (gliner2) ``extract_entities`` accepts either a list[str]
        # (no descriptions) or dict[str, str] (label -> description).
        # Prepare BOTH forms and pick at inference time based on
        # ``self._descriptions_enabled``.
        self._gliner_labels: list[str] = [_ALL_LABEL_DESCRIPTIONS[et][0] for et in self._entity_types]
        if self._is_v2:
            self._gliner_labels_v2: dict[str, str] = {
                _ALL_LABEL_DESCRIPTIONS[et][0]: _ALL_LABEL_DESCRIPTIONS[et][1] for et in self._entity_types
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

    def classify_per_value(
        self,
        column: ColumnInput,
        *,
        sample_size: int | None = None,
    ) -> tuple[list[list[SpanDetection]], int]:
        """Run GLiNER per-value on a deterministic subsample of the column.

        Returns (per_value_spans, sampled_row_count). Per-value failures
        are isolated to the affected row. Total model-load failure propagates.
        """
        if column.data_type and column.data_type.upper() in _NON_TEXT_DATA_TYPES:
            return [], 0
        if not column.sample_values:
            return [], 0

        if sample_size is None:
            sample_size = _load_per_value_sample_size()

        sampled = _stable_subsample(column.sample_values, n=sample_size)
        if not sampled:
            return [], 0

        model = self._get_model()

        per_value_spans: list[list[SpanDetection]] = []
        for value in sampled:
            text = _build_ner_prompt(column, [value])
            row_spans: list[SpanDetection] = []
            try:
                if self._is_v2:
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
                                row_spans.append(
                                    SpanDetection(
                                        text=str(match.get("text", "")),
                                        entity_type=entity_type,
                                        confidence=float(match.get("confidence", 0.5)),
                                        start=int(match.get("start", 0)),
                                        end=int(match.get("end", 0)),
                                    )
                                )
                else:
                    preds = model.predict_entities(text, self._gliner_labels, threshold=self._gliner_threshold)
                    for pred in preds:
                        entity_type = GLINER_LABEL_TO_ENTITY.get(pred.get("label", ""))
                        if entity_type is None:
                            continue
                        row_spans.append(
                            SpanDetection(
                                text=str(pred.get("text", "")),
                                entity_type=entity_type,
                                confidence=float(pred.get("score", 0.0)),
                                start=int(pred.get("start", 0)),
                                end=int(pred.get("end", 0)),
                            )
                        )
            except Exception:
                logger.exception(
                    "GLiNER per-value inference failed on one value for column %s",
                    column.column_id,
                )
            per_value_spans.append(row_spans)

        return per_value_spans, len(sampled)

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

            # Sprint 18 stop-gap: count==1 ORG guard. See module-level
            # _ORG_CONTEXT_NAMES_RE / _ORG_SUFFIX_RE for full rationale.
            # Multi-row Faker FPs are already suppressed by the
            # avg-confidence aggregation above; this rule only kicks in
            # when count == 1 (the test case + low-context production
            # shape). Removable when the LLM escalation layer ships.
            if entity_type == "ORGANIZATION" and count == 1:
                matched_text = hits[0][0] if hits else ""
                column_name = column.column_name or ""
                if not _ORG_CONTEXT_NAMES_RE.search(column_name) and not _ORG_SUFFIX_RE.search(matched_text):
                    continue

            # Sprint 18 stop-gap: PERSON_NAME common-noun guard.
            # See _is_lowercase_common_noun_person_span for rationale.
            # Drops findings where ALL matched spans are common-noun FPs
            # (lowercase single words like 'worker', 'caller'; or
            # determiner-led like 'A worker', 'The handler'). Mixed
            # findings (some real names + some FPs) pass through and
            # defer to LLM escalation. Removable when the LLM
            # escalation layer ships.
            if entity_type == "PERSON_NAME":
                span_texts = [text for text, _ in hits]
                if span_texts and all(_is_lowercase_common_noun_person_span(s) for s in span_texts):
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


def _evidence_overlap(a: ClassificationFinding, b: ClassificationFinding) -> float:
    """Jaccard similarity between two findings' sample_matches.

    Returns 1.0 when evidence is identical, 0.0 when disjoint.
    When either finding has no sample_matches, returns 1.0 (assume overlap
    since we can't disprove it).
    """
    a_matches = set(a.sample_analysis.sample_matches) if a.sample_analysis else set()
    b_matches = set(b.sample_analysis.sample_matches) if b.sample_analysis else set()
    if not a_matches or not b_matches:
        return 1.0
    union = a_matches | b_matches
    if not union:
        return 1.0
    return len(a_matches & b_matches) / len(union)


# Minimum evidence overlap to trigger specificity suppression.
# Below this, findings are treated as detecting independent signals.
_EVIDENCE_OVERLAP_THRESHOLD = 0.5


def _deduplicate_gliner_findings(findings: list[ClassificationFinding]) -> list[ClassificationFinding]:
    """When GLiNER2 finds overlapping entity types on the same evidence, keep the more specific one.

    Suppression only fires when the two findings share substantial evidence
    overlap (Jaccard >= 0.5 on sample_matches).  When they detect different
    values — e.g. ADDRESS on street strings and PERSON_NAME on name strings
    in the same column — both survive.
    """
    if len(findings) <= 1:
        return findings

    # Sort by specificity (highest first), then confidence
    findings.sort(key=lambda f: (_SPECIFICITY_ORDER.get(f.entity_type, 0), f.confidence), reverse=True)

    kept: list[ClassificationFinding] = []
    for f in findings:
        f_spec = _SPECIFICITY_ORDER.get(f.entity_type, 0)
        suppressed = False
        for k in kept:
            k_spec = _SPECIFICITY_ORDER.get(k.entity_type, 0)
            if k_spec > f_spec and k.confidence - f.confidence < 0.3:
                if _evidence_overlap(k, f) >= _EVIDENCE_OVERLAP_THRESHOLD:
                    suppressed = True
                    break
        if not suppressed:
            kept.append(f)
    return kept


def _mask_ner_value(value: str) -> str:
    """Mask a detected NER value for evidence display."""
    if len(value) <= 3:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]
