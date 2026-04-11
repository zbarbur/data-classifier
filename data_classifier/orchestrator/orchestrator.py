"""Unified orchestrator — coordinates engine cascade for classification.

One orchestrator, one cascade logic, three behaviors (structured, unstructured,
prompt).  The ``mode`` flag controls which engines run.  Engines declare their
``supported_modes`` and ``order``; the orchestrator filters and sequences them.

Engine priority weighting:
  Each engine declares an ``authority`` weight (higher = more trusted).
  When two engines produce findings for the same column:
  - Same entity_type: highest-authority engine's finding is preferred; if equal
    authority, highest confidence wins.
  - Conflicting entity_types: when a high-authority engine (column_name) identifies
    an entity type, lower-authority engines' conflicting entity types are suppressed.
  - Agreement: when high-authority and lower-authority engines agree on entity_type,
    confidence is boosted.
"""

from __future__ import annotations

import logging
import time

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.events.emitter import EventEmitter
from data_classifier.events.types import ClassificationEvent, TierEvent
from data_classifier.orchestrator.calibration import calibrate_finding
from data_classifier.orchestrator.table_profile import (
    TableProfile,
    build_table_profile,
    get_sibling_adjustment,
)

logger = logging.getLogger(__name__)

# Known collision pairs: entity types whose regex patterns structurally overlap.
# Ordered so that type_a and type_b are interchangeable — only confidence decides.
_COLLISION_PAIRS: list[tuple[str, str]] = [
    ("SSN", "ABA_ROUTING"),
    ("SSN", "CANADIAN_SIN"),
    ("ABA_ROUTING", "CANADIAN_SIN"),
    ("NPI", "PHONE"),
    ("DEA_NUMBER", "IBAN"),
]

# Minimum confidence gap required to suppress the lower-confidence finding.
# Below this threshold the column is genuinely ambiguous and both findings are kept.
_COLLISION_GAP_THRESHOLD: float = 0.15

# Confidence boost when a high-authority engine agrees with a lower-authority engine
_AGREEMENT_BOOST: float = 0.05

# Minimum authority level to consider an engine "authoritative" (can suppress others)
_AUTHORITY_THRESHOLD: int = 8

# Minimum authority gap to suppress a lower-authority engine's conflicting findings
_AUTHORITY_GAP_MIN: int = 3


class Orchestrator:
    """Coordinates the engine cascade for column classification.

    Args:
        engines: Registered engine instances.
        mode: Pipeline mode — ``structured``, ``unstructured``, or ``prompt``.
        emitter: Event emitter for telemetry.  If None, events are discarded.
    """

    def __init__(
        self,
        engines: list[ClassificationEngine],
        *,
        mode: str = "structured",
        emitter: EventEmitter | None = None,
    ) -> None:
        self.mode = mode
        self.emitter = emitter or EventEmitter()

        # Filter engines by mode and sort by execution order
        self.engines = sorted(
            [e for e in engines if self.mode in e.supported_modes],
            key=lambda e: e.order,
        )

    def classify_column(
        self,
        column: ColumnInput,
        profile: ClassificationProfile,
        *,
        min_confidence: float = 0.5,
        budget_ms: float | None = None,
        run_id: str | None = None,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Run the engine cascade on a single column.

        Engines run in order.  Each engine can produce findings independently.
        Findings are merged with authority-weighted conflict resolution:
        - Same entity_type: higher-authority engine wins; equal authority → highest confidence wins.
        - Different entity_types: tracked per-engine for cross-engine conflict resolution.
        """
        # Track findings per entity_type along with the producing engine's authority
        all_findings: dict[str, ClassificationFinding] = {}
        finding_authority: dict[str, int] = {}  # entity_type → authority of engine that produced it
        # Track all findings per engine for cross-engine conflict resolution
        engine_findings: dict[str, list[ClassificationFinding]] = {}

        engines_executed: list[str] = []
        engines_skipped: list[str] = []
        t_start = time.monotonic()

        for engine in self.engines:
            # Budget check (iteration 2: use latency tracker p95 estimates)
            if budget_ms is not None:
                elapsed = (time.monotonic() - t_start) * 1000
                if elapsed >= budget_ms:
                    engines_skipped.append(engine.name)
                    continue

            t0 = time.monotonic()
            try:
                findings = engine.classify_column(
                    column,
                    profile=profile,
                    min_confidence=min_confidence,
                    mask_samples=mask_samples,
                    max_evidence_samples=max_evidence_samples,
                )
            except Exception:
                logger.exception("Engine %s failed on column %s", engine.name, column.column_id)
                findings = []

            elapsed_ms = (time.monotonic() - t0) * 1000
            engines_executed.append(engine.name)

            # Emit tier event
            self.emitter.emit(
                TierEvent(
                    tier=engine.name,
                    latency_ms=round(elapsed_ms, 2),
                    outcome="hit" if findings else "miss",
                    column_id=column.column_id,
                    findings_count=len(findings),
                    run_id=run_id or "",
                )
            )

            # Calibrate findings before merging
            findings = [calibrate_finding(f) for f in findings]

            engine_findings[engine.name] = list(findings)

            # Merge findings: authority-weighted, then confidence
            for f in findings:
                existing = all_findings.get(f.entity_type)
                existing_auth = finding_authority.get(f.entity_type, 0)
                if existing is None:
                    all_findings[f.entity_type] = f
                    finding_authority[f.entity_type] = engine.authority
                elif engine.authority > existing_auth:
                    # Higher authority engine always wins
                    all_findings[f.entity_type] = f
                    finding_authority[f.entity_type] = engine.authority
                elif engine.authority == existing_auth and f.confidence > existing.confidence:
                    # Same authority → highest confidence wins
                    all_findings[f.entity_type] = f

        total_ms = (time.monotonic() - t_start) * 1000

        # Apply engine priority weighting: suppress/boost based on cross-engine agreement
        all_findings = self._apply_engine_weighting(all_findings, finding_authority, engine_findings)

        # Resolve known collision pairs before emitting results
        all_findings = self._resolve_collisions(all_findings)

        # Suppress generic CREDENTIAL when more specific types are found
        all_findings = self._suppress_generic_credential(all_findings)

        # Emit classification event
        result = list(all_findings.values())
        self.emitter.emit(
            ClassificationEvent(
                column_id=column.column_id,
                total_findings=len(result),
                total_ms=round(total_ms, 2),
                engines_executed=engines_executed,
                engines_skipped=engines_skipped,
                run_id=run_id or "",
            )
        )

        return result

    def _apply_engine_weighting(
        self,
        findings: dict[str, ClassificationFinding],
        finding_authority: dict[str, int],
        engine_findings: dict[str, list[ClassificationFinding]],
    ) -> dict[str, ClassificationFinding]:
        """Apply engine priority weighting across findings.

        When a high-authority engine (e.g. column_name) has identified an entity type:
        1. Suppress findings from lower-authority engines that disagree on entity type.
        2. Boost confidence when engines agree on entity type.
        """
        if not findings or len(engine_findings) < 2:
            return findings

        # Find the highest-authority engine that produced findings
        max_authority = 0
        authoritative_types: set[str] = set()
        for entity_type, auth in finding_authority.items():
            if auth > max_authority:
                max_authority = auth
                authoritative_types = {entity_type}
            elif auth == max_authority:
                authoritative_types.add(entity_type)

        if max_authority < _AUTHORITY_THRESHOLD:
            # No engine has authoritative-level authority — skip weighting
            return findings

        # Collect entity types from lower-authority engines
        low_auth_types: set[str] = set()
        for entity_type, auth in finding_authority.items():
            if auth < max_authority and (max_authority - auth) >= _AUTHORITY_GAP_MIN:
                low_auth_types.add(entity_type)

        # Suppress low-authority findings that conflict with authoritative findings
        # A conflict means: the low-authority engine found a DIFFERENT entity type
        # AND this entity type was NOT also found by the authoritative engine
        conflicting = low_auth_types - authoritative_types
        for entity_type in conflicting:
            logger.debug(
                "Engine weighting: suppressing %s (authority=%d) — conflicts with authoritative finding(s) %s",
                entity_type,
                finding_authority[entity_type],
                authoritative_types,
            )
            del findings[entity_type]
            del finding_authority[entity_type]

        # Boost confidence when high-authority and lower-authority engines agree
        for entity_type in authoritative_types:
            # Check if any lower-authority engine also found this type
            for engine_name, efindings in engine_findings.items():
                engine_obj = next((e for e in self.engines if e.name == engine_name), None)
                if engine_obj is None:
                    continue
                if engine_obj.authority >= max_authority:
                    continue
                # Lower-authority engine — did it also find this entity type?
                for ef in efindings:
                    if ef.entity_type == entity_type:
                        current = findings[entity_type]
                        boosted = min(1.0, current.confidence + _AGREEMENT_BOOST)
                        logger.debug(
                            "Engine weighting: boosting %s confidence %.2f → %.2f (agreement between %s and %s)",
                            entity_type,
                            current.confidence,
                            boosted,
                            current.engine,
                            engine_name,
                        )
                        findings[entity_type] = ClassificationFinding(
                            column_id=current.column_id,
                            entity_type=current.entity_type,
                            category=current.category,
                            sensitivity=current.sensitivity,
                            confidence=boosted,
                            regulatory=current.regulatory,
                            engine=current.engine,
                            evidence=current.evidence + f" [+{_AGREEMENT_BOOST:.2f} agreement with {engine_name}]",
                            sample_analysis=current.sample_analysis,
                        )
                        break  # Only boost once per lower engine

        return findings

    def classify_columns(
        self,
        columns: list[ColumnInput],
        profile: ClassificationProfile,
        *,
        min_confidence: float = 0.5,
        budget_ms: float | None = None,
        run_id: str | None = None,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Two-pass classification of multiple columns with sibling context.

        Pass 1: Classify each column independently (existing single-column logic).
        Pass 2: Build table profile from high-confidence Pass 1 findings, then
                 re-adjust ambiguous columns using sibling context.

        For a single column, this is equivalent to calling ``classify_column`` directly.

        Args:
            columns: Columns to classify.
            profile: Classification profile.
            min_confidence: Minimum confidence threshold.
            budget_ms: Optional latency budget.
            run_id: Run ID for telemetry.
            mask_samples: Whether to mask sample values.
            max_evidence_samples: Max evidence samples.

        Returns:
            All findings across all columns.
        """
        if len(columns) <= 1:
            # Single column — no sibling context, use standard path
            if not columns:
                return []
            return self.classify_column(
                columns[0],
                profile,
                min_confidence=min_confidence,
                budget_ms=budget_ms,
                run_id=run_id,
                mask_samples=mask_samples,
                max_evidence_samples=max_evidence_samples,
            )

        # ── Pass 1: Independent classification ────────────────────────────────
        pass1_results: dict[str, list[ClassificationFinding]] = {}
        all_pass1_findings: list[ClassificationFinding] = []

        for column in columns:
            findings = self.classify_column(
                column,
                profile,
                min_confidence=min_confidence,
                budget_ms=budget_ms,
                run_id=run_id,
                mask_samples=mask_samples,
                max_evidence_samples=max_evidence_samples,
            )
            pass1_results[column.column_id] = findings
            all_pass1_findings.extend(findings)

        # ── Pass 2: Sibling context adjustment ────────────────────────────────
        table_profile = build_table_profile(all_pass1_findings)

        if table_profile.primary_domain is None:
            # No clear domain signal — return Pass 1 results as-is
            logger.debug("Sibling analysis: no clear domain signal, skipping Pass 2")
            return all_pass1_findings

        logger.debug(
            "Sibling analysis: detected domain '%s' with %d signals, running Pass 2",
            table_profile.primary_domain,
            table_profile.signal_count,
        )

        # Apply sibling adjustments to each column's findings
        adjusted_findings: list[ClassificationFinding] = []
        for column in columns:
            column_findings = pass1_results[column.column_id]
            adjusted = self._apply_sibling_adjustments(
                column_findings,
                table_profile,
                column.column_id,
                all_pass1_findings,
                min_confidence,
            )
            adjusted_findings.extend(adjusted)

        return adjusted_findings

    def _apply_sibling_adjustments(
        self,
        findings: list[ClassificationFinding],
        table_profile: TableProfile,
        column_id: str,
        all_findings: list[ClassificationFinding],
        min_confidence: float,
    ) -> list[ClassificationFinding]:
        """Apply sibling-context adjustments to a column's findings.

        Uses the table profile to boost/suppress entity types based on domain context.
        Only adjusts findings when there are known collision pairs or ambiguous types.
        """
        if not findings:
            return findings

        # Build column-specific profile excluding this column
        column_profile = build_table_profile(all_findings, exclude_column_id=column_id)
        if column_profile.primary_domain is None:
            # Without this column, no clear domain — keep findings as-is
            return findings

        adjusted: list[ClassificationFinding] = []
        for f in findings:
            adjustment = get_sibling_adjustment(f.entity_type, column_profile)
            if adjustment == 0.0:
                adjusted.append(f)
                continue

            new_confidence = max(0.0, min(1.0, f.confidence + adjustment))
            if new_confidence < min_confidence:
                logger.debug(
                    "Sibling analysis: suppressing %s on %s (%.2f → %.2f, domain=%s)",
                    f.entity_type,
                    column_id,
                    f.confidence,
                    new_confidence,
                    column_profile.primary_domain,
                )
                continue

            evidence_suffix = (
                f" [sibling {'+' if adjustment > 0 else ''}{adjustment:.2f} domain={column_profile.primary_domain}]"
            )
            adjusted.append(
                ClassificationFinding(
                    column_id=f.column_id,
                    entity_type=f.entity_type,
                    category=f.category,
                    sensitivity=f.sensitivity,
                    confidence=new_confidence,
                    regulatory=f.regulatory,
                    engine=f.engine,
                    evidence=f.evidence + evidence_suffix,
                    sample_analysis=f.sample_analysis,
                )
            )

        return adjusted

    def _resolve_collisions(self, findings: dict[str, ClassificationFinding]) -> dict[str, ClassificationFinding]:
        """Suppress the lower-confidence finding when known collision pairs co-occur.

        Only suppresses when the confidence gap exceeds ``_COLLISION_GAP_THRESHOLD``.
        If the gap is small, both findings are kept — the column is genuinely ambiguous.
        """
        for type_a, type_b in _COLLISION_PAIRS:
            if type_a in findings and type_b in findings:
                conf_a = findings[type_a].confidence
                conf_b = findings[type_b].confidence
                gap = abs(conf_a - conf_b)
                if gap >= _COLLISION_GAP_THRESHOLD:
                    loser = type_b if conf_a > conf_b else type_a
                    logger.debug(
                        "Collision resolution: suppressing %s (%.2f) in favour of %s (%.2f) — gap=%.2f",
                        loser,
                        findings[loser].confidence,
                        type_a if loser == type_b else type_b,
                        max(conf_a, conf_b),
                        gap,
                    )
                    del findings[loser]
        return findings

    @staticmethod
    def _suppress_generic_credential(
        findings: dict[str, ClassificationFinding],
    ) -> dict[str, ClassificationFinding]:
        """Suppress CREDENTIAL when a more specific entity type is found with higher confidence.

        CREDENTIAL from heuristic/secret scanner engines is a catch-all signal (high entropy).
        When a more specific engine (regex, column_name) already identified the entity type,
        the generic CREDENTIAL finding is almost certainly a false positive.
        """
        if "CREDENTIAL" not in findings or len(findings) < 2:
            return findings

        credential = findings["CREDENTIAL"]
        # Check if any other finding has higher or equal confidence
        for entity_type, finding in findings.items():
            if entity_type == "CREDENTIAL":
                continue
            if finding.confidence >= credential.confidence:
                logger.debug(
                    "Suppressing generic CREDENTIAL (%.2f, engine=%s) — %s has higher confidence (%.2f, engine=%s)",
                    credential.confidence,
                    credential.engine,
                    entity_type,
                    finding.confidence,
                    finding.engine,
                )
                del findings["CREDENTIAL"]
                return findings

        return findings
