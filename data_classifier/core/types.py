"""Core data models for the data_classifier library.

All public types are defined here and re-exported from data_classifier.__init__.
These are dataclasses — lightweight, no validation overhead. Pydantic is used
only in the HTTP API layer (data_classifier.api.models).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Constants ────────────────────────────────────────────────────────────────

SENSITIVITY_ORDER: dict[str, int] = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


# ── Input Models ─────────────────────────────────────────────────────────────


@dataclass
class ColumnStats:
    """Column-level statistics computed by the connector.

    The connector queries its source database for these values and passes
    them to the library. The library never connects to any database.
    """

    null_pct: float = 0.0
    """Null ratio 0.0-1.0."""

    distinct_count: int = 0
    """Number of distinct non-null values."""

    total_count: int = 0
    """Total row count."""

    min_length: int = 0
    """Minimum string length (non-null values)."""

    max_length: int = 0
    """Maximum string length."""

    avg_length: float = 0.0
    """Average string length."""


@dataclass
class ColumnInput:
    """Everything the library needs to classify a single column.

    Only ``column_name`` is required.  All other fields are optional and
    improve accuracy when provided.  Engines use what they can, ignore
    what they don't need.
    """

    # ── Required ──────────────────────────────────────────
    column_name: str
    """The column name — highest-signal input for classification."""

    # ── Identity (optional) ───────────────────────────────
    column_id: str = ""
    """Caller-defined unique identifier.  Opaque to the library — echoed
    back in ClassificationFinding.column_id."""

    # ── Context (optional metadata) ───────────────────────
    table_name: str = ""
    """Parent table name for context."""

    dataset: str = ""
    """Dataset, schema, or database name."""

    schema_name: str = ""
    """Schema name within a dataset or database (e.g. ``public``, ``dbo``)."""

    data_type: str = ""
    """SQL data type as string (e.g. ``STRING``, ``INTEGER``)."""

    description: str = ""
    """Column description/comment from the catalog."""

    # ── Content (optional sample data) ────────────────────
    sample_values: list[str] = field(default_factory=list)
    """10-100 sampled non-null values, coerced to strings by the connector.
    The library scans ALL provided values.  Connector controls volume."""

    # ── Statistics (optional) ─────────────────────────────
    stats: ColumnStats | None = None
    """Pre-computed column statistics from the source database."""


# ── Classification Rule & Profile ────────────────────────────────────────────


@dataclass
class ClassificationRule:
    """A single classification rule: entity type + regex patterns."""

    entity_type: str
    category: str
    """Data category grouping: ``PII``, ``Financial``, ``Credential``, ``Health``."""

    sensitivity: str
    regulatory: list[str]
    confidence: float
    patterns: list[str]
    compiled_patterns: list[re.Pattern] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.patterns]


@dataclass
class ClassificationProfile:
    """A named set of classification rules."""

    name: str
    description: str
    rules: list[ClassificationRule]


# ── Output Models ────────────────────────────────────────────────────────────


@dataclass
class SampleAnalysis:
    """How sample values contributed to a finding.

    ``match_ratio`` is *prevalence* — what fraction of the column contains
    this entity type.  This is NOT the same as confidence.
    """

    samples_scanned: int
    """Total values scanned for this column."""

    samples_matched: int
    """How many matched this entity_type's pattern."""

    samples_validated: int
    """How many passed secondary validation (Luhn, format checks)."""

    match_ratio: float
    """matched / scanned — prevalence, not confidence."""

    sample_matches: list[str] = field(default_factory=list)
    """First N matching values as evidence.  Masked when ``mask_samples=True``."""


@dataclass(frozen=True)
class SpanDetection:
    """One entity span detected by a per-value NER call."""

    text: str
    """The detected entity text."""

    entity_type: str
    """The entity type (e.g., EMAIL, SSN, CREDENTIAL)."""

    confidence: float
    """Detection confidence 0.0-1.0."""

    start: int
    """Start position in the source text."""

    end: int
    """End position in the source text."""


@dataclass
class ClassificationFinding:
    """Result of classifying a single column."""

    # ── Identity ──────────────────────────────────────────
    column_id: str
    """Echoed from ColumnInput.column_id."""

    # ── Classification ────────────────────────────────────
    entity_type: str
    """Detected entity type: ``SSN``, ``EMAIL``, ``CREDENTIAL``, etc."""

    category: str
    """Data category: ``PII``, ``Financial``, ``Credential``, ``Health``.
    Groups entity types by regulatory framework (GDPR scope, HIPAA
    scope, etc.)."""

    sensitivity: str
    """Sensitivity level: ``CRITICAL``, ``HIGH``, ``MEDIUM``, ``LOW``."""

    confidence: float
    """0.0-1.0.  How sure we are this entity type EXISTS in this column."""

    regulatory: list[str]
    """Applicable regulatory frameworks."""

    # ── Provenance ────────────────────────────────────────
    engine: str
    """Which engine produced this finding."""

    evidence: str = ""
    """Human-readable explanation of the classification."""

    # ── Detection detail ─────────────────────────────────
    detection_type: str = ""
    """Specific detection pattern identifier (e.g. ``aws_access_key``,
    ``github_token``).  More granular than ``entity_type`` — multiple
    detection_types may share the same entity_type (e.g. both
    ``aws_access_key`` and ``github_token`` are ``API_KEY``).
    Set by the regex engine from the pattern name; other engines may
    leave it empty."""

    display_name: str = ""
    """Human-friendly label (e.g. ``AWS Access Key``, ``GitHub Token``).
    Intended for end-user display.  Auto-populated from the pattern's
    ``display_name`` field when available."""

    # ── Sample detail ─────────────────────────────────────
    sample_analysis: SampleAnalysis | None = None
    """Populated when finding was derived from sample value analysis."""

    # ── Family (Sprint 11) ────────────────────────────────
    family: str = ""
    """Structural handling family: ``CONTACT``, ``CREDENTIAL``,
    ``FINANCIAL``, ``PAYMENT_CARD``, etc. Distinct from
    :attr:`category` — ``category`` is the regulatory grouping,
    ``family`` is the downstream DLP-policy grouping. See
    ``data_classifier.core.taxonomy.ENTITY_TYPE_TO_FAMILY`` for the
    full mapping. Auto-populated from ``entity_type`` in
    ``__post_init__`` when left empty."""

    def __post_init__(self) -> None:
        # Auto-populate family from entity_type so every finding
        # carries its family tag without the caller having to know
        # the taxonomy. Callers that want to override can still pass
        # family explicitly.
        if not self.family and self.entity_type:
            from data_classifier.core.taxonomy import family_for

            self.family = family_for(self.entity_type)


@dataclass
class RollupResult:
    """Aggregated classification summary for a parent node (table or dataset)."""

    sensitivity: str
    """Highest sensitivity from child findings."""

    classifications: list[str]
    """Sorted unique entity types."""

    frameworks: list[str]
    """Sorted unique regulatory frameworks."""

    findings_count: int
    """Total findings count."""
