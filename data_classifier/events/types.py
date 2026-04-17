"""Event types for classification telemetry.

Every engine invocation emits a TierEvent.  The EventEmitter dispatches
events to pluggable handlers (null, stdout, callback, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class TierEvent:
    """Emitted after each engine runs on a single column."""

    tier: str
    """Engine name (e.g. ``regex``, ``column_name``)."""

    latency_ms: float
    """Wall-clock time for this engine invocation."""

    outcome: str
    """``hit`` if findings were produced, ``miss`` otherwise."""

    column_id: str = ""
    """Which column was classified."""

    findings_count: int = 0
    """Number of findings this engine produced."""

    run_id: str = ""
    """Associated run ID for grouping."""

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ClassificationEvent:
    """Emitted after a full column classification (all engines)."""

    column_id: str
    total_findings: int
    total_ms: float
    engines_executed: list[str] = field(default_factory=list)
    engines_skipped: list[str] = field(default_factory=list)
    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class MetaClassifierEvent:
    """Emitted after the meta-classifier produces a shadow prediction.

    Shadow events are observability-only — the prediction is NOT used to
    modify ``classify_columns()`` return values in Phase 3. Consumers can
    compare the shadow prediction against the live pipeline's top vote
    via the :attr:`agreement` field.
    """

    column_id: str
    predicted_entity: str
    confidence: float
    live_entity: str
    agreement: bool
    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class GateRoutingEvent:
    """Emitted by the Sprint 11 tier-1 credential pattern-hit gate.

    The gate is evaluated whenever a column has credential-category
    signal (primary finding is a credential, OR the secret-scanner
    fired with confidence ≥ 0.50). It reports whether a "strong
    pattern hit" threshold was crossed so downstream consumers can
    measure tier-1 coverage against the meta-classifier's shadow
    stream.

    Landing semantics: **observability-only** in Sprint 11. The gate
    decision does NOT mutate ``classify_columns()`` return values —
    the event exists to measure how often the gate would fire in
    production before promoting it to a directive routing rule.
    """

    column_id: str
    gate_fired: bool
    gate_reason: str
    """Short human-readable tag for why the gate did/didn't fire
    (e.g. ``"regex+ratio"``, ``"secret_scanner"``, ``"regex_confidence_low"``).
    """

    primary_entity: str
    primary_confidence: float
    primary_is_credential: bool
    regex_confidence: float
    regex_match_ratio: float
    secret_scanner_confidence: float
    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ColumnShapeEvent:
    """Emitted by the Sprint 13 column-shape router for every classification.

    The router inspects the engine-cascade output and column-level
    statistics to decide which downstream handler a column should route
    to (``structured_single`` → current v5 shadow + 7-pass merge;
    ``free_text_heterogeneous`` → per-value GLiNER aggregation landing in
    Sprint 13 Item B; ``opaque_tokens`` → tuned secret_scanner landing
    in Sprint 13 Item C). The event carries the detection signals so
    BQ telemetry can measure the real shape distribution in production
    and so Item B's per-value latency shows up in the same stream.

    ``per_value_inference_ms`` and ``sampled_row_count`` are ``None`` on
    the ``structured_single`` and ``opaque_tokens`` branches. They are
    populated by Item B's per-value handler on the
    ``free_text_heterogeneous`` branch once that item lands.
    """

    column_id: str
    shape: str
    """One of ``structured_single``, ``free_text_heterogeneous``, ``opaque_tokens``."""

    avg_len_normalized: float
    dict_word_ratio: float
    cardinality_ratio: float
    n_cascade_entities: int
    column_name_hint_applied: bool
    """True iff the column-name tiebreaker fired to resolve an ambiguous
    middle-band content signal. Always False on unambiguous decisions.
    """

    per_value_inference_ms: int | None = None
    """Populated only on the ``free_text_heterogeneous`` branch (Item B)."""

    sampled_row_count: int | None = None
    """Populated only on the ``free_text_heterogeneous`` branch (Item B)."""

    run_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
