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
    Groups entity types by the kind of sensitive data."""

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

    # ── Sample detail ─────────────────────────────────────
    sample_analysis: SampleAnalysis | None = None
    """Populated when finding was derived from sample value analysis."""


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
