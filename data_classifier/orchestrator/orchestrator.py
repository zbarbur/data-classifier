"""Unified orchestrator — coordinates engine cascade for classification.

One orchestrator, one cascade logic, three behaviors (structured, unstructured,
prompt).  The ``mode`` flag controls which engines run.  Engines declare their
``supported_modes`` and ``order``; the orchestrator filters and sequences them.

Iteration 1: single engine (regex).  The orchestrator infrastructure exists so
iteration 2 can add engines without refactoring.
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
        Findings are collected, deduplicated by entity_type (highest confidence
        wins), and filtered by min_confidence.
        """
        all_findings: dict[str, ClassificationFinding] = {}
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

            # Merge findings (highest confidence per entity_type wins)
            for f in findings:
                existing = all_findings.get(f.entity_type)
                if existing is None or f.confidence > existing.confidence:
                    all_findings[f.entity_type] = f

        total_ms = (time.monotonic() - t_start) * 1000

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
