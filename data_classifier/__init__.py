"""data_classifier — general-purpose data classification engine.

Public API
----------

Types::

    ColumnInput, ColumnStats       — input models
    ClassificationFinding          — per-column result
    SampleAnalysis                 — sample value evidence
    ClassificationProfile          — named rule set
    ClassificationRule             — single rule
    RollupResult                   — parent-level aggregate

Functions::

    classify_columns()             — classify a list of columns
    load_profile()                 — load bundled profile by name
    load_profile_from_yaml()       — load profile from a YAML file
    load_profile_from_dict()       — load profile from a parsed dict
    compute_rollups()              — aggregate findings to parent level
    rollup_from_rollups()          — aggregate rollups to grandparent level

Constants::

    SENSITIVITY_ORDER              — maps sensitivity names to sort order
"""

from __future__ import annotations

from data_classifier.core.types import (
    SENSITIVITY_ORDER,
    ClassificationFinding,
    ClassificationProfile,
    ClassificationRule,
    ColumnInput,
    ColumnStats,
    RollupResult,
    SampleAnalysis,
)
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.events.emitter import EventEmitter
from data_classifier.orchestrator.orchestrator import Orchestrator
from data_classifier.profiles import (
    load_profile,
    load_profile_from_dict,
    load_profile_from_yaml,
)

__all__ = [
    # Types
    "ColumnInput",
    "ColumnStats",
    "ClassificationFinding",
    "SampleAnalysis",
    "ClassificationProfile",
    "ClassificationRule",
    "RollupResult",
    # Functions
    "classify_columns",
    "load_profile",
    "load_profile_from_yaml",
    "load_profile_from_dict",
    "compute_rollups",
    "rollup_from_rollups",
    # Constants
    "SENSITIVITY_ORDER",
]


# ── Module-level engine registry ─────────────────────────────────────────────

_DEFAULT_ENGINES = [RegexEngine()]


def classify_columns(
    columns: list[ColumnInput],
    profile: ClassificationProfile,
    *,
    min_confidence: float = 0.5,
    budget_ms: float | None = None,
    run_id: str | None = None,
    config: dict | None = None,
    mask_samples: bool = False,
    max_evidence_samples: int = 5,
    event_emitter: EventEmitter | None = None,
) -> list[ClassificationFinding]:
    """Classify columns using the engine cascade.

    Returns one or more :class:`ClassificationFinding` per column that has
    detectable sensitive data.  Columns with no matches are omitted.
    A single column may have multiple findings (e.g. a notes column with
    both emails and phone numbers in its sample values).

    Args:
        columns: Columns to classify.
        profile: Classification profile (rules + patterns).
        min_confidence: Findings below this threshold are not returned.
            Default ``0.5``.
        budget_ms: Latency budget in ms.  ``None`` = no budget, full cascade.
        run_id: Associates findings with a run for telemetry event tagging.
        config: Per-request overrides (custom patterns, dictionaries).
            Iteration 1: accepted but not used.
        mask_samples: When ``True``, sample_matches in SampleAnalysis are
            partially redacted.
        max_evidence_samples: Max matching sample values to include in
            SampleAnalysis.sample_matches.
        event_emitter: Optional event emitter for telemetry.  If ``None``,
            events are discarded.

    Returns:
        List of findings across all columns.
    """
    orchestrator = Orchestrator(
        engines=_DEFAULT_ENGINES,
        mode="structured",
        emitter=event_emitter,
    )

    findings: list[ClassificationFinding] = []
    for column in columns:
        column_findings = orchestrator.classify_column(
            column,
            profile,
            min_confidence=min_confidence,
            budget_ms=budget_ms,
            run_id=run_id,
            mask_samples=mask_samples,
            max_evidence_samples=max_evidence_samples,
        )
        findings.extend(column_findings)

    return findings


# ── Rollup computation ───────────────────────────────────────────────────────


def compute_rollups(
    findings: list[ClassificationFinding],
    parent_map: dict[str, str],
) -> dict[str, RollupResult]:
    """Aggregate findings into parent-level rollups.

    Call once with column→table map, then again (via :func:`rollup_from_rollups`)
    with table→dataset map.

    Args:
        findings: Classification findings to aggregate.
        parent_map: Maps child ID → parent ID (e.g. column_id → table_id).

    Returns:
        Dict keyed by parent ID with aggregated :class:`RollupResult`.
    """
    if not findings:
        return {}

    parent_groups: dict[str, list[ClassificationFinding]] = {}
    for f in findings:
        parent_id = parent_map.get(f.column_id)
        if parent_id is not None:
            parent_groups.setdefault(parent_id, []).append(f)

    rollups: dict[str, RollupResult] = {}
    for parent_id, group in parent_groups.items():
        sensitivity = max(
            (f.sensitivity for f in group),
            key=lambda s: SENSITIVITY_ORDER.get(s, 0),
        )
        classifications = sorted({f.entity_type for f in group})
        frameworks = sorted({fw for f in group for fw in f.regulatory})
        rollups[parent_id] = RollupResult(
            sensitivity=sensitivity,
            classifications=classifications,
            frameworks=frameworks,
            findings_count=len(group),
        )

    return rollups


def rollup_from_rollups(
    child_rollups: dict[str, RollupResult],
    parent_map: dict[str, str],
) -> dict[str, RollupResult]:
    """Aggregate child rollups into grandparent rollups (e.g. table → dataset).

    Args:
        child_rollups: Output of :func:`compute_rollups` at the child level.
        parent_map: Maps child ID → grandparent ID.

    Returns:
        Dict keyed by grandparent ID with aggregated :class:`RollupResult`.
    """
    if not child_rollups:
        return {}

    parent_groups: dict[str, list[RollupResult]] = {}
    for child_id, rollup in child_rollups.items():
        parent_id = parent_map.get(child_id)
        if parent_id is not None:
            parent_groups.setdefault(parent_id, []).append(rollup)

    result: dict[str, RollupResult] = {}
    for parent_id, group in parent_groups.items():
        sensitivity = max(
            (r.sensitivity for r in group),
            key=lambda s: SENSITIVITY_ORDER.get(s, 0),
        )
        classifications = sorted({c for r in group for c in r.classifications})
        frameworks = sorted({fw for r in group for fw in r.frameworks})
        findings_count = sum(r.findings_count for r in group)
        result[parent_id] = RollupResult(
            sensitivity=sensitivity,
            classifications=classifications,
            frameworks=frameworks,
            findings_count=findings_count,
        )

    return result
