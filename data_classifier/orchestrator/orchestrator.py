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

# Three-way collision types — these overlap structurally (all 9-digit numeric).
_THREE_WAY_TYPES = frozenset({"SSN", "ABA_ROUTING", "CANADIAN_SIN"})

# Column name keywords that strongly indicate NPI (vs PHONE).
_NPI_COLUMN_KEYWORDS = {"npi", "provider", "prescriber"}

# Column name keywords for DEA/IBAN disambiguation.
_DEA_COLUMN_KEYWORDS = {"dea"}
_IBAN_COLUMN_KEYWORDS = {"iban"}


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

        # Three-way SSN/ABA/SIN resolution runs first (before pairwise)
        all_findings = self._resolve_three_way_collisions(all_findings)

        # Resolve known collision pairs (including NPI/PHONE, DEA/IBAN specials)
        column_name = column.column_name
        all_findings = self._resolve_npi_phone(all_findings, column_name=column_name)
        all_findings = self._resolve_dea_iban(all_findings, column_name=column_name)
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

    # ── Three-way SSN / ABA_ROUTING / CANADIAN_SIN ──────────────────────────

    def _resolve_three_way_collisions(
        self, findings: dict[str, ClassificationFinding]
    ) -> dict[str, ClassificationFinding]:
        """Resolve the three-way SSN/ABA_ROUTING/CANADIAN_SIN collision.

        All three are 9-digit numeric patterns that structurally overlap.
        When all three co-occur, use engine signals and confidence gap to
        pick a single winner (or keep all if genuinely ambiguous).

        Must run BEFORE pairwise ``_resolve_collisions()`` so pairwise
        doesn't incorrectly suppress one of a remaining pair.
        """
        present = _THREE_WAY_TYPES & findings.keys()
        if len(present) < 3:
            return findings  # Not a three-way — let pairwise handle it

        three = {t: findings[t] for t in _THREE_WAY_TYPES}

        # Signal 1: column_name engine — if one finding came from column_name engine,
        # the column name itself matched that entity type. Strong signal.
        column_name_winners = [t for t, f in three.items() if f.engine == "column_name"]
        if len(column_name_winners) == 1:
            winner = column_name_winners[0]
            for t in _THREE_WAY_TYPES - {winner}:
                logger.debug(
                    "Three-way collision: %s wins (column_name engine) — removing %s",
                    winner,
                    t,
                )
                del findings[t]
            return findings

        # Signal 2: heuristic engine (cardinality analysis) — if one finding came
        # from heuristic engine, it has structural evidence beyond regex match.
        heuristic_winners = [t for t, f in three.items() if f.engine == "heuristic"]
        if len(heuristic_winners) == 1:
            winner = heuristic_winners[0]
            # Only use heuristic signal if confidence gap is reasonable
            others = [f.confidence for t, f in three.items() if t != winner]
            if three[winner].confidence >= max(others):
                for t in _THREE_WAY_TYPES - {winner}:
                    logger.debug(
                        "Three-way collision: %s wins (heuristic engine) — removing %s",
                        winner,
                        t,
                    )
                    del findings[t]
                return findings

        # Signal 3: confidence gap — pick the highest confidence if the gap
        # between best and worst exceeds the threshold.
        sorted_types = sorted(_THREE_WAY_TYPES, key=lambda t: three[t].confidence, reverse=True)
        best = sorted_types[0]
        worst = sorted_types[2]
        gap = three[best].confidence - three[worst].confidence

        if gap >= _COLLISION_GAP_THRESHOLD:
            # Remove all but the best
            for t in _THREE_WAY_TYPES - {best}:
                logger.debug(
                    "Three-way collision: %s wins (confidence %.2f) — removing %s (%.2f), gap=%.2f",
                    best,
                    three[best].confidence,
                    t,
                    three[t].confidence,
                    gap,
                )
                del findings[t]

        return findings

    # ── NPI vs PHONE ────────────────────────────────────────────────────────

    def _resolve_npi_phone(
        self, findings: dict[str, ClassificationFinding], *, column_name: str
    ) -> dict[str, ClassificationFinding]:
        """Resolve NPI vs PHONE collision with domain-specific logic.

        NPI (National Provider Identifier) is a 10-digit number used in healthcare.
        PHONE numbers are also 10 digits. When both collide:
        - Column name contains npi/provider/prescriber → NPI wins
        - NPI has validator confirmation → NPI wins
        - Otherwise PHONE wins (far more common in general data)
        """
        if "NPI" not in findings or "PHONE" not in findings:
            return findings

        npi = findings["NPI"]
        col_lower = column_name.lower()

        # Signal 1: column name keywords strongly indicate NPI
        if any(kw in col_lower for kw in _NPI_COLUMN_KEYWORDS):
            logger.debug("NPI/PHONE collision: NPI wins — column name '%s' matches NPI keywords", column_name)
            del findings["PHONE"]
            return findings

        # Signal 2: NPI validator confirmation (check digit validated)
        npi_validated = False
        if "validat" in (npi.evidence or "").lower():
            npi_validated = True
        elif npi.sample_analysis and npi.sample_analysis.samples_validated > 0:
            npi_validated = True

        if npi_validated:
            logger.debug("NPI/PHONE collision: NPI wins — validator confirmation")
            del findings["PHONE"]
            return findings

        # Default: PHONE wins (far more common in real-world data)
        logger.debug("NPI/PHONE collision: PHONE wins — no NPI-specific signals")
        del findings["NPI"]
        return findings

    # ── DEA_NUMBER vs IBAN ──────────────────────────────────────────────────

    def _resolve_dea_iban(
        self, findings: dict[str, ClassificationFinding], *, column_name: str
    ) -> dict[str, ClassificationFinding]:
        """Resolve DEA_NUMBER vs IBAN collision with length and validator signals.

        DEA numbers are 9 characters (2 letters + 7 digits).
        IBANs are 15-34 characters. When both collide:
        - Length-based: 9-char samples → DEA; 15+ chars → IBAN
        - Validator-based: samples_validated > 0 for either type wins
        - Column name as tiebreaker
        """
        if "DEA_NUMBER" not in findings or "IBAN" not in findings:
            return findings

        dea = findings["DEA_NUMBER"]
        iban = findings["IBAN"]
        col_lower = column_name.lower()

        # Signal 1: sample value length — strongest structural signal
        dea_lengths = self._get_sample_lengths(dea)
        iban_lengths = self._get_sample_lengths(iban)

        if dea_lengths and all(length <= 10 for length in dea_lengths):
            logger.debug("DEA/IBAN collision: DEA wins — sample lengths suggest DEA (%s)", dea_lengths)
            del findings["IBAN"]
            return findings

        if iban_lengths and all(length >= 15 for length in iban_lengths):
            logger.debug("DEA/IBAN collision: IBAN wins — sample lengths suggest IBAN (%s)", iban_lengths)
            del findings["DEA_NUMBER"]
            return findings

        # Signal 2: validator confirmation
        dea_validated = dea.sample_analysis and dea.sample_analysis.samples_validated > 0
        iban_validated = iban.sample_analysis and iban.sample_analysis.samples_validated > 0

        if dea_validated and not iban_validated:
            logger.debug("DEA/IBAN collision: DEA wins — validator confirmation")
            del findings["IBAN"]
            return findings

        if iban_validated and not dea_validated:
            logger.debug("DEA/IBAN collision: IBAN wins — validator confirmation")
            del findings["DEA_NUMBER"]
            return findings

        # Signal 3: column name tiebreaker
        if any(kw in col_lower for kw in _DEA_COLUMN_KEYWORDS):
            logger.debug("DEA/IBAN collision: DEA wins — column name '%s'", column_name)
            del findings["IBAN"]
            return findings

        if any(kw in col_lower for kw in _IBAN_COLUMN_KEYWORDS):
            logger.debug("DEA/IBAN collision: IBAN wins — column name '%s'", column_name)
            del findings["DEA_NUMBER"]
            return findings

        # No decisive signal — let pairwise confidence resolution handle it
        return findings

    @staticmethod
    def _get_sample_lengths(finding: ClassificationFinding) -> list[int]:
        """Extract sample match lengths from a finding's sample_analysis."""
        if not finding.sample_analysis or not finding.sample_analysis.sample_matches:
            return []
        return [len(s) for s in finding.sample_analysis.sample_matches]

    # ── Pairwise Collision Resolution ───────────────────────────────────────

    def _resolve_collisions(self, findings: dict[str, ClassificationFinding]) -> dict[str, ClassificationFinding]:
        """Suppress the lower-confidence finding when known collision pairs co-occur.

        Only suppresses when the confidence gap exceeds ``_COLLISION_GAP_THRESHOLD``.
        If the gap is small, both findings are kept — the column is genuinely ambiguous.

        NPI/PHONE and DEA/IBAN are handled by their dedicated methods before this
        runs, so they are typically already resolved. The pairwise logic here serves
        as a fallback if the special methods couldn't decide.
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
