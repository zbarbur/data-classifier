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

Introspection::

    get_supported_categories()     — list data categories
    get_supported_entity_types()   — list entity types with metadata
    get_supported_sensitivity_levels() — list sensitivity levels in order
    get_pattern_library()          — list content patterns with metadata
    get_active_engines()           — list engines loaded into the cascade
    health_check()                 — run a canned classification probe

Constants::

    SENSITIVITY_ORDER              — maps sensitivity names to sort order
"""

from __future__ import annotations

import logging

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
from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.heuristic_engine import HeuristicEngine
from data_classifier.engines.regex_engine import RegexEngine
from data_classifier.engines.secret_scanner import SecretScannerEngine
from data_classifier.events.emitter import EventEmitter
from data_classifier.orchestrator.orchestrator import Orchestrator
from data_classifier.profiles import (
    load_profile,
    load_profile_from_dict,
    load_profile_from_yaml,
)

logger = logging.getLogger(__name__)

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
    "download_models",
    # Introspection
    "get_supported_categories",
    "get_supported_entity_types",
    "get_supported_sensitivity_levels",
    "get_pattern_library",
    "get_active_engines",
    "health_check",
    # Constants
    "SENSITIVITY_ORDER",
]


def download_models(argv: list[str] | None = None) -> int:
    """Download the pre-exported GLiNER ONNX model tarball (lazy wrapper).

    This is a thin wrapper around
    :func:`data_classifier.download_models.main` that imports the module
    lazily so ``import data_classifier`` never pulls in ``urllib``,
    ``tarfile``, ``hashlib``, etc. until a caller actually needs the
    downloader. Returns the CLI exit code.

    Note: importing ``data_classifier.download_models`` as a submodule
    rebinds ``data_classifier.download_models`` to the module object,
    shadowing this function. We immediately restore the function binding
    so repeated calls via ``data_classifier.download_models(...)`` keep
    working. Callers that do ``from data_classifier import download_models``
    are unaffected because they captured the function reference at
    import time.
    """
    import sys as _sys

    import data_classifier.download_models as _dm_module

    exit_code = _dm_module.main(argv)
    # Restore the function binding so the symbol stays callable.
    _sys.modules[__name__].download_models = download_models
    return exit_code


# ── Module-level engine registry ─────────────────────────────────────────────


def _build_default_engines() -> list:
    """Build default engine list, including GLiNER2 if available.

    Environment variables (for production deployment):
        DATA_CLASSIFIER_DISABLE_ML=1 — skip GLiNER2 engine entirely
        GLINER_ONNX_PATH=<path>      — load GLiNER2 from pre-exported ONNX dir
                                       (avoids HuggingFace download at runtime)
        GLINER_API_KEY=<key>         — use GLiNER hosted API as fallback
    """
    import os

    engines: list = [ColumnNameEngine(), RegexEngine(), HeuristicEngine(), SecretScannerEngine()]

    if os.environ.get("DATA_CLASSIFIER_DISABLE_ML"):
        return engines

    try:
        from data_classifier.engines.gliner_engine import GLiNER2Engine

        onnx_path = os.environ.get("GLINER_ONNX_PATH")
        api_key = os.environ.get("GLINER_API_KEY")
        engines.append(GLiNER2Engine(onnx_path=onnx_path, api_key=api_key))
    except ImportError as e:
        logger.warning(
            "GLiNER2 engine disabled — install [ml] extras to enable: %s",
            e,
        )
    return engines


_DEFAULT_ENGINES = _build_default_engines()


#: When aggressive_secondary_suppression is enabled, the "primary-dominant"
#: regime triggers at this confidence — findings above this are treated as
#: strong enough to crowd out low-confidence secondaries with a tighter gap.
_AGGRESSIVE_PRIMARY_THRESHOLD = 0.80
#: Tightened confidence-gap threshold used when the primary finding exceeds
#: ``_AGGRESSIVE_PRIMARY_THRESHOLD``. Secondaries more than this many points
#: below the primary are suppressed — stricter than the default 0.30.
_AGGRESSIVE_GAP_THRESHOLD = 0.15


def classify_columns(
    columns: list[ColumnInput],
    profile: ClassificationProfile,
    *,
    min_confidence: float = 0.5,
    categories: list[str] | None = None,
    max_findings: int | None = None,
    confidence_gap_threshold: float = 0.30,
    aggressive_secondary_suppression: bool = False,
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
        categories: Filter findings to only these categories.
            ``None`` = all categories.  Example: ``["PII", "Credential"]``
            to skip Financial and Health findings.
            Valid values: ``PII``, ``Financial``, ``Credential``, ``Health``.
        max_findings: Maximum number of findings to return per column.
            ``None`` = no limit (all findings returned).
            ``1`` = primary label mode (only the highest-confidence finding).
        confidence_gap_threshold: When ``max_findings`` is ``None``,
            secondary findings whose confidence is more than this gap below
            the top finding are suppressed.  Default ``0.30``.
            Set to ``1.0`` to disable gap suppression.
        aggressive_secondary_suppression: When ``True`` and the top finding
            has confidence greater than ``0.80``, the effective gap
            threshold tightens to ``0.15`` — dropping more low-confidence
            secondaries in the "primary-dominant" regime. Useful for
            precision-sensitive deployments where a strong primary signal
            should crowd out ambiguous alternates. Default ``False``
            preserves Sprint 5 behavior exactly.
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

    # Normalize category filter to a set for O(1) lookup
    category_filter: set[str] | None = None
    if categories is not None:
        category_filter = {c for c in categories}

    # Two-pass classification with sibling context (for multiple columns)
    all_findings = orchestrator.classify_columns(
        columns,
        profile,
        min_confidence=min_confidence,
        budget_ms=budget_ms,
        run_id=run_id,
        mask_samples=mask_samples,
        max_evidence_samples=max_evidence_samples,
    )

    # Group findings by column for per-column filtering
    column_findings_map: dict[str, list[ClassificationFinding]] = {}
    for f in all_findings:
        column_findings_map.setdefault(f.column_id, []).append(f)

    findings: list[ClassificationFinding] = []
    for column in columns:
        column_findings = column_findings_map.get(column.column_id, [])

        if category_filter is not None:
            column_findings = [f for f in column_findings if f.category in category_filter]

        # Apply max_findings and confidence-gap suppression per column
        if column_findings:
            column_findings = _apply_findings_limit(
                column_findings,
                max_findings,
                confidence_gap_threshold,
                aggressive_secondary_suppression=aggressive_secondary_suppression,
            )

        findings.extend(column_findings)

    return findings


def _apply_findings_limit(
    findings: list[ClassificationFinding],
    max_findings: int | None,
    confidence_gap_threshold: float,
    *,
    aggressive_secondary_suppression: bool = False,
) -> list[ClassificationFinding]:
    """Limit and filter findings per column.

    1. Sort by confidence descending.
    2. If max_findings is set, truncate to that count.
    3. Otherwise, apply confidence-gap suppression: drop findings whose
       confidence is more than ``confidence_gap_threshold`` below the top finding.
    4. When ``aggressive_secondary_suppression`` is True AND the top finding
       has confidence greater than ``_AGGRESSIVE_PRIMARY_THRESHOLD`` (0.80),
       the effective gap tightens to ``_AGGRESSIVE_GAP_THRESHOLD`` (0.15).
    """
    if not findings:
        return findings

    # Sort by confidence descending
    sorted_findings = sorted(findings, key=lambda f: f.confidence, reverse=True)

    if max_findings is not None:
        return sorted_findings[:max_findings]

    top_confidence = sorted_findings[0].confidence

    # Aggressive suppression: when primary dominates, tighten the gap
    effective_gap = confidence_gap_threshold
    if aggressive_secondary_suppression and top_confidence > _AGGRESSIVE_PRIMARY_THRESHOLD:
        effective_gap = min(effective_gap, _AGGRESSIVE_GAP_THRESHOLD)

    return [f for f in sorted_findings if (top_confidence - f.confidence) <= effective_gap]


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


# ── Introspection ────────────────────────────────────────────────────────────


def get_supported_categories() -> list[str]:
    """Return all data categories the library can detect.

    Categories group entity types by the kind of sensitive data::

        PII        — Personal identity data (SSN, email, phone, name, address, ...)
        Financial  — Financial/payment data (credit card, bank account, salary, ...)
        Credential — Authentication secrets (passwords, API keys, tokens, ...)
        Health     — Protected health information (diagnosis, MRN, medication, ...)

    Returns:
        Sorted list of category names.
    """
    profile = load_profile("standard")
    return sorted({r.category for r in profile.rules if r.category})


def get_supported_entity_types() -> list[dict]:
    """Return all entity types the library can detect, with metadata.

    Each entry contains:
    - ``entity_type``: type name (e.g. ``SSN``, ``EMAIL``)
    - ``category``: data category (e.g. ``PII``, ``Financial``)
    - ``sensitivity``: default sensitivity level
    - ``regulatory``: applicable compliance frameworks
    - ``source``: ``profile`` (column name rules) or ``pattern`` (content regex)

    Combines entity types from both the profile rules (column name matching)
    and the content pattern library (sample value matching).
    """
    from data_classifier.patterns import load_default_patterns

    seen: dict[str, dict] = {}

    # From profile rules (column name matching)
    profile = load_profile("standard")
    for r in profile.rules:
        if r.entity_type not in seen:
            seen[r.entity_type] = {
                "entity_type": r.entity_type,
                "category": r.category,
                "sensitivity": r.sensitivity,
                "regulatory": list(r.regulatory),
                "source": "profile",
            }

    # From content patterns (sample value matching)
    for p in load_default_patterns():
        if p.entity_type not in seen:
            seen[p.entity_type] = {
                "entity_type": p.entity_type,
                "category": p.category,
                "sensitivity": p.sensitivity,
                "regulatory": [],
                "source": "pattern",
            }

    return sorted(seen.values(), key=lambda x: (x["category"], x["entity_type"]))


def get_supported_sensitivity_levels() -> list[str]:
    """Return sensitivity levels in ascending order.

    Returns:
        ``["LOW", "MEDIUM", "HIGH", "CRITICAL"]``
    """
    return sorted(SENSITIVITY_ORDER.keys(), key=lambda s: SENSITIVITY_ORDER[s])


def get_pattern_library() -> list[dict]:
    """Return all content-matching patterns with their metadata.

    Each entry contains: ``name``, ``regex``, ``entity_type``, ``category``,
    ``sensitivity``, ``confidence``, ``description``, ``validator``,
    ``examples_match``, ``examples_no_match``.

    Useful for:
    - UI display (show what the library can detect)
    - Pattern curation and review
    - Documentation generation
    """
    from dataclasses import asdict

    from data_classifier.patterns import load_default_patterns

    return [asdict(p) for p in load_default_patterns()]


def get_active_engines() -> list[dict]:
    """Return the list of engines currently loaded into the default cascade.

    Each entry contains:

    - ``name``   — stable engine identifier (e.g. ``regex``, ``column_name``)
    - ``order``  — execution order in the cascade (lower runs first)
    - ``class``  — implementing class name (e.g. ``RegexEngine``)

    Use this at service startup to verify which engines are live **before**
    taking traffic. In particular, the GLiNER2 engine is only present when
    the ``[ml]`` extras are installed and ``DATA_CLASSIFIER_DISABLE_ML`` is
    not set — calling this lets consumers assert the expected engine set
    instead of silently running regex-only.
    """
    return [
        {
            "name": engine.name,
            "order": engine.order,
            "class": type(engine).__name__,
        }
        for engine in _DEFAULT_ENGINES
    ]


def health_check(profile: ClassificationProfile | None = None) -> dict:
    """Run a canned single-column classification probe and report status.

    This is the canonical "is data_classifier alive?" check. It builds a
    trivial :class:`ColumnInput` (``column_name='email_address'``,
    ``sample_values=['alice@example.com']``), runs it through
    :func:`classify_columns` with the standard profile, and captures which
    engines executed via an internal event emitter.

    The function **never raises** — any exception during probe execution
    is caught, the error text is returned in the ``error`` field, and
    ``healthy`` is set to ``False``. This makes it safe to call from
    ``/health`` endpoints without worrying about a bad profile or a broken
    engine crashing the service.

    Args:
        profile: Optional profile to probe against. If ``None``, loads the
            bundled ``standard`` profile.

    Returns:
        Dict with keys::

            {
                "healthy": bool,
                "engines_executed": list[str],   # authoritative from ClassificationEvent
                "engines_skipped": list[str],
                "latency_ms": float,             # wall-clock probe latency
                "findings": list[dict],          # serialized ClassificationFinding subset
                "error": str | None,             # exception text if healthy=False
            }
    """
    import time

    from data_classifier.events.emitter import CallbackHandler, EventEmitter
    from data_classifier.events.types import ClassificationEvent

    engines_executed: list[str] = []
    engines_skipped: list[str] = []

    def _capture(event: object) -> None:
        if isinstance(event, ClassificationEvent):
            engines_executed.extend(event.engines_executed)
            engines_skipped.extend(event.engines_skipped)

    result: dict = {
        "healthy": False,
        "engines_executed": engines_executed,
        "engines_skipped": engines_skipped,
        "latency_ms": 0.0,
        "findings": [],
        "error": None,
    }

    start = time.perf_counter()
    try:
        emitter = EventEmitter()
        emitter.add_handler(CallbackHandler(_capture))

        probe_profile = profile if profile is not None else load_profile("standard")
        probe = ColumnInput(
            column_name="email_address",
            column_id="healthcheck:probe",
            sample_values=["alice@example.com"],
        )
        findings = classify_columns(
            [probe],
            probe_profile,
            event_emitter=emitter,
        )
        result["findings"] = [
            {
                "entity_type": f.entity_type,
                "category": f.category,
                "sensitivity": f.sensitivity,
                "confidence": f.confidence,
            }
            for f in findings
        ]
        # Healthy iff at least one engine actually ran on the probe.
        result["healthy"] = bool(engines_executed)
        if not engines_executed:
            result["error"] = "no engines executed on probe"
    except Exception as e:  # noqa: BLE001 — probe must never raise
        result["healthy"] = False
        result["error"] = f"{type(e).__name__}: {e}"
    finally:
        result["latency_ms"] = (time.perf_counter() - start) * 1000.0

    return result
