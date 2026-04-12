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
