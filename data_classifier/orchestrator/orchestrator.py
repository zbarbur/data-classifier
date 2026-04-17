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
import os
import time
from dataclasses import dataclass

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.events.emitter import EventEmitter
from data_classifier.events.types import (
    ClassificationEvent,
    ColumnShapeEvent,
    GateRoutingEvent,
    MetaClassifierEvent,
    TierEvent,
)
from data_classifier.orchestrator.calibration import calibrate_finding
from data_classifier.orchestrator.meta_classifier import MetaClassifier, MetaClassifierPrediction
from data_classifier.orchestrator.shape_detector import detect_column_shape
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

# Directional suppression: when a *specific* numeric-format PII type co-occurs
# with PHONE, PHONE is always the false positive (digit-heavy values like dates
# and credit card numbers match the PHONE regex spuriously). Unlike symmetric
# collision pairs above, the winner is pre-determined — PHONE is always
# suppressed regardless of confidence gap.
# Mapping: entity_type → set of entity types that PHONE should be suppressed in
# favour of (i.e., if any of these co-occur with PHONE, drop PHONE).
_PHONE_SUPPRESSION_WINNERS: set[str] = {
    "DATE_OF_BIRTH",
    "CREDIT_CARD",
}

# Confidence boost when a high-authority engine agrees with a lower-authority engine
_AGREEMENT_BOOST: float = 0.05

# Minimum authority level to consider an engine "authoritative" (can suppress others)
_AUTHORITY_THRESHOLD: int = 8

# Minimum authority gap to suppress a lower-authority engine's conflicting findings
_AUTHORITY_GAP_MIN: int = 3

# ── Sprint 11 Phase 9: tier-1 pattern-hit gate ──────────────────────────────
#
# The gate fires on a column when either:
#   (a) the primary finding is a credential AND the regex engine is both
#       confident (>= 0.85) AND saw the pattern across a meaningful
#       fraction of sampled values (match_ratio >= 0.30), OR
#   (b) the secret scanner fired with confidence >= 0.50.
#
# Thresholds intentionally loose on (b) because the secret scanner is
# already authority-gated upstream; the gate's job there is simply to
# record that a tier-1 credential signal was observed. Thresholds on
# (a) are tighter because regex alone is prone to prefix-collision
# false positives.
_GATE_REGEX_CONFIDENCE_MIN: float = 0.85
_GATE_REGEX_MATCH_RATIO_MIN: float = 0.30
_GATE_SECRET_SCANNER_CONFIDENCE_MIN: float = 0.50


@dataclass
class _Tier1GateDecision:
    """Pure result of evaluating the tier-1 credential pattern-hit gate.

    Returned by :func:`_evaluate_tier1_gate`. Contains everything
    needed to construct a :class:`GateRoutingEvent`. Kept as a plain
    dataclass (not the event type itself) so the evaluator stays free
    of any telemetry concern.
    """

    gate_fired: bool
    gate_reason: str
    primary_entity: str
    primary_confidence: float
    primary_is_credential: bool
    regex_confidence: float
    regex_match_ratio: float
    secret_scanner_confidence: float


def _evaluate_tier1_gate(
    result: list[ClassificationFinding],
    engine_findings: dict[str, list[ClassificationFinding]],
) -> _Tier1GateDecision | None:
    """Pure tier-1 credential pattern-hit gate evaluator.

    Returns ``None`` when the gate is not applicable to this column
    (no credential signal anywhere), so the orchestrator can skip
    event emission on columns that have no bearing on tier-1
    coverage. Returns a populated :class:`_Tier1GateDecision` whenever
    credential signal is present, with ``gate_fired=True`` iff at
    least one of the two gate conditions holds.
    """
    regex_findings = engine_findings.get("regex", [])
    secret_findings = engine_findings.get("secret_scanner", [])

    regex_confidence = 0.0
    regex_match_ratio = 0.0
    if regex_findings:
        top_regex = max(regex_findings, key=lambda f: f.confidence)
        regex_confidence = top_regex.confidence
        if top_regex.sample_analysis is not None:
            regex_match_ratio = top_regex.sample_analysis.match_ratio

    secret_scanner_confidence = 0.0
    if secret_findings:
        secret_scanner_confidence = max(f.confidence for f in secret_findings)

    if result:
        top = max(result, key=lambda f: f.confidence)
        primary_entity = top.entity_type
        primary_confidence = top.confidence
        primary_is_credential = top.category == "Credential"
    else:
        primary_entity = ""
        primary_confidence = 0.0
        primary_is_credential = False

    # Applicability guard: only record the gate when the column shows
    # tier-1 credential signal. Otherwise we'd spam events for every
    # PII column in the cascade.
    has_credential_signal = primary_is_credential or secret_scanner_confidence >= _GATE_SECRET_SCANNER_CONFIDENCE_MIN
    if not has_credential_signal:
        return None

    # Gate condition (a): regex credential + strong confidence + strong prevalence.
    regex_path_fires = (
        primary_is_credential
        and regex_confidence >= _GATE_REGEX_CONFIDENCE_MIN
        and regex_match_ratio >= _GATE_REGEX_MATCH_RATIO_MIN
    )
    # Gate condition (b): secret scanner confidence threshold alone.
    secret_path_fires = secret_scanner_confidence >= _GATE_SECRET_SCANNER_CONFIDENCE_MIN

    if regex_path_fires and secret_path_fires:
        reason = "regex+ratio+secret_scanner"
    elif regex_path_fires:
        reason = "regex+ratio"
    elif secret_path_fires:
        reason = "secret_scanner"
    elif primary_is_credential and regex_confidence < _GATE_REGEX_CONFIDENCE_MIN:
        reason = "regex_confidence_low"
    elif primary_is_credential and regex_match_ratio < _GATE_REGEX_MATCH_RATIO_MIN:
        reason = "regex_match_ratio_low"
    else:
        reason = "no_tier1_signal"

    return _Tier1GateDecision(
        gate_fired=regex_path_fires or secret_path_fires,
        gate_reason=reason,
        primary_entity=primary_entity,
        primary_confidence=primary_confidence,
        primary_is_credential=primary_is_credential,
        regex_confidence=regex_confidence,
        regex_match_ratio=regex_match_ratio,
        secret_scanner_confidence=secret_scanner_confidence,
    )


def _union_findings(
    cascade: list[ClassificationFinding],
    additions: list[ClassificationFinding],
) -> list[ClassificationFinding]:
    """Union cascade findings with per-value aggregated additions.

    Dedup on (column_id, entity_type) — keep the higher-confidence finding.
    Cascade findings are never dropped; additions add entity types the
    cascade did not express.
    """
    by_key: dict[tuple[str, str], ClassificationFinding] = {(f.column_id, f.entity_type): f for f in cascade}
    for f in additions:
        key = (f.column_id, f.entity_type)
        existing = by_key.get(key)
        if existing is None or f.confidence > existing.confidence:
            by_key[key] = f
    return list(by_key.values())


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
        meta_classifier_directive: bool | None = None,
    ) -> None:
        self.mode = mode
        self.emitter = emitter or EventEmitter()

        # Filter engines by mode and sort by execution order
        self.engines = sorted(
            [e for e in engines if self.mode in e.supported_modes],
            key=lambda e: e.order,
        )

        # Meta-classifier shadow inference (Sprint 6 Phase 3).
        # Opt-OUT via DATA_CLASSIFIER_DISABLE_META=1. The instance is
        # created eagerly but the model load happens lazily on the first
        # predict_shadow call — instantiation itself is free.
        self._meta_classifier: MetaClassifier | None
        disable_meta = os.environ.get("DATA_CLASSIFIER_DISABLE_META", "").lower()
        if disable_meta in ("1", "true", "yes"):
            self._meta_classifier = None
        else:
            self._meta_classifier = MetaClassifier()

        # Sprint 14: meta-classifier directive mode on structured_single columns.
        # When True, the meta-classifier's prediction replaces the cascade output
        # on structured_single columns instead of being shadow-only.
        # Opt-OUT via DATA_CLASSIFIER_DISABLE_META_DIRECTIVE=1.
        if meta_classifier_directive is not None:
            self._meta_directive = meta_classifier_directive
        else:
            disable_directive = os.environ.get("DATA_CLASSIFIER_DISABLE_META_DIRECTIVE", "").lower()
            self._meta_directive = disable_directive not in ("1", "true", "yes")

    def _find_engine_by_name(self, name: str) -> ClassificationEngine | None:
        for engine in self.engines:
            if engine.name == name:
                return engine
        return None

    @staticmethod
    def _apply_meta_directive(
        prediction: "MetaClassifierPrediction",
        cascade_result: list[ClassificationFinding],
        column: ColumnInput,
        profile: ClassificationProfile,
    ) -> list[ClassificationFinding] | None:
        """Apply the meta-classifier directive: replace cascade output.

        Returns a new result list with the meta-classifier's predicted
        entity_type as the top finding, or ``None`` if the directive
        cannot be applied (e.g. entity type has no metadata).

        Strategy:
        1. If the predicted entity_type matches the cascade's top finding,
           no change needed — return ``None`` to keep cascade output as-is.
        2. If a cascade finding already exists for the predicted entity_type,
           promote it to the top by boosting its confidence.
        3. Otherwise, construct a new finding using profile metadata.

        Cascade findings are preserved as supporting evidence — the
        meta-classifier only changes which entity_type is primary.
        """
        if not prediction.predicted_entity or prediction.predicted_entity == "NEGATIVE":
            return None

        # Confidence gate: only apply directive when the meta-classifier
        # is reasonably confident.  On the family benchmark every correct
        # prediction has confidence >= 0.53; 0.50 gives a small margin.
        min_directive_confidence = 0.50
        if prediction.confidence < min_directive_confidence:
            return None

        # If cascade already agrees, no directive needed
        if cascade_result:
            top = max(cascade_result, key=lambda f: f.confidence)
            if top.entity_type == prediction.predicted_entity:
                return None
            # If cascade has a high-confidence answer, trust the cascade.
            # The directive should only override when the cascade is uncertain.
            cascade_trust_threshold = 0.80
            if top.confidence >= cascade_trust_threshold:
                return None

        # Look for the predicted entity_type in existing cascade findings
        existing = None
        for f in cascade_result:
            if f.entity_type == prediction.predicted_entity:
                existing = f
                break

        if existing is not None:
            # Promote existing finding: set its confidence to be the highest
            top_conf = max((f.confidence for f in cascade_result), default=0.0)
            promoted_conf = max(top_conf + 0.01, prediction.confidence)
            promoted_conf = min(1.0, promoted_conf)
            promoted = ClassificationFinding(
                column_id=existing.column_id,
                entity_type=existing.entity_type,
                category=existing.category,
                sensitivity=existing.sensitivity,
                confidence=promoted_conf,
                regulatory=existing.regulatory,
                engine="meta_classifier",
                evidence=f"Meta-classifier directive (promoted from {existing.engine}, "
                f"cascade confidence={existing.confidence:.2f})",
                sample_analysis=existing.sample_analysis,
            )
            # Replace the existing finding with the promoted one, keep others
            new_result = [promoted] + [f for f in cascade_result if f.entity_type != prediction.predicted_entity]
            return new_result

        # Construct a new finding from profile metadata
        rule_meta = None
        for rule in profile.rules:
            if rule.entity_type == prediction.predicted_entity:
                rule_meta = rule
                break

        if rule_meta is None:
            # No metadata for this entity type — cannot construct a finding
            logger.debug(
                "Meta-classifier directive: no profile metadata for %s; skipping",
                prediction.predicted_entity,
            )
            return None

        new_finding = ClassificationFinding(
            column_id=column.column_id,
            entity_type=prediction.predicted_entity,
            category=rule_meta.category,
            sensitivity=rule_meta.sensitivity,
            confidence=prediction.confidence,
            regulatory=list(rule_meta.regulatory),
            engine="meta_classifier",
            evidence=f"Meta-classifier directive (confidence={prediction.confidence:.2f})",
        )
        # Prepend the new finding, keep cascade findings as supporting data
        return [new_finding] + list(cascade_result)

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

        # Post-processing merges run on ALL shapes — deterministic dedup +
        # FP suppression is valuable regardless of shape. Only the v5
        # shadow emission below is gated by the detected shape.
        all_findings = self._apply_engine_weighting(all_findings, finding_authority, engine_findings)

        # Suppress ML-only findings when a non-ML engine already has a strong match
        all_findings = self._suppress_ml_when_strong_match(all_findings, engine_findings)

        # Resolve known collision pairs before emitting results
        all_findings = self._resolve_collisions(all_findings)

        # Directional PHONE suppression: numeric-format PII types (dates,
        # credit cards) match PHONE regex spuriously. When a specific numeric
        # PII type co-occurs with PHONE, PHONE is always the false positive.
        all_findings = self._suppress_phone_on_numeric_pii(all_findings)

        # Suppress generic CREDENTIAL when more specific types are found
        all_findings = self._suppress_generic_credential(all_findings)

        # Suppress IP_ADDRESS findings when every matched value is embedded in a URL
        all_findings = self._suppress_url_embedded_ips(all_findings)

        # Emit classification event
        result = list(all_findings.values())

        # ── Sprint 13 Item A: column-shape detection ──────────────────────
        # Runs AFTER the merge passes so n_cascade_entities reflects the
        # deduped/resolved entity types, not the noisy pre-merge count that
        # is inflated by engine collisions on homogeneous columns (e.g., an
        # ABA_ROUTING column triggers both column_name_engine → ABA_ROUTING
        # and regex_engine → SSN pre-merge — authority resolution drops SSN,
        # leaving 1 entity type post-merge). The structured_single route's
        # n_cascade <= 1 guard requires the post-merge count.
        try:
            shape_detection = detect_column_shape(column, result)
        except Exception:
            logger.debug("Shape detection failed; defaulting to structured_single behavior", exc_info=True)
            shape_detection = None
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

        # ── Sprint 13 Item B: per-value GLiNER on heterogeneous branch ────
        per_value_inference_ms: int | None = None
        sampled_row_count: int | None = None
        if shape_detection is not None and shape_detection.shape == "free_text_heterogeneous":
            gliner = self._find_engine_by_name("gliner2")
            if gliner is not None:
                t0 = time.monotonic()
                try:
                    per_value_spans, sampled = gliner.classify_per_value(column)
                    if sampled > 0:
                        from data_classifier.orchestrator.per_value_aggregator import (
                            aggregate_per_value_spans,
                        )

                        aggregated = aggregate_per_value_spans(
                            per_value_spans,
                            n_samples=sampled,
                            column_id=column.column_id,
                        )
                        result = _union_findings(result, aggregated)
                        sampled_row_count = sampled
                except Exception:
                    logger.exception(
                        "Per-value GLiNER handler failed for column %s; falling back to cascade output",
                        column.column_id,
                    )
                finally:
                    per_value_inference_ms = int((time.monotonic() - t0) * 1000)

        # ── Sprint 13 Item C: entropy-based handler on opaque_tokens branch ──
        # Only add OPAQUE_SECRET when the cascade found nothing. If the cascade
        # already identified the column (e.g., BITCOIN_ADDRESS, ETHEREUM_ADDRESS),
        # the cascade's answer is more specific and should not be diluted.
        if shape_detection is not None and shape_detection.shape == "opaque_tokens" and not result:
            try:
                from data_classifier.orchestrator.opaque_token_handler import classify_opaque_tokens

                opaque_findings = classify_opaque_tokens(column.column_id, column.sample_values)
                if opaque_findings:
                    result = _union_findings(result, opaque_findings)
            except Exception:
                logger.exception(
                    "Opaque-token handler failed for column %s; falling back to cascade output",
                    column.column_id,
                )

        # ── Sprint 13 Item A: emit ColumnShapeEvent (moved after Item B) ──
        if shape_detection is not None:
            self.emitter.emit(
                ColumnShapeEvent(
                    column_id=column.column_id,
                    shape=shape_detection.shape,
                    avg_len_normalized=shape_detection.avg_len_normalized,
                    dict_word_ratio=shape_detection.dict_word_ratio,
                    cardinality_ratio=shape_detection.cardinality_ratio,
                    n_cascade_entities=shape_detection.n_cascade_entities,
                    column_name_hint_applied=shape_detection.column_name_hint_applied,
                    per_value_inference_ms=per_value_inference_ms,
                    sampled_row_count=sampled_row_count,
                    run_id=run_id or "",
                )
            )

        # Meta-classifier inference (Sprint 6 Phase 3 shadow → Sprint 14 directive).
        # Sprint 13 Item A gates on shape detection. v5 is documented to
        # collapse on free_text_heterogeneous and opaque_tokens shapes
        # (see docs/research/meta_classifier/sprint12_safety_audit.md §3).
        # Skip emission on those branches to stop feeding wrong-class
        # predictions into downstream telemetry.
        #
        # Sprint 14 directive flip: on structured_single columns, the
        # meta-classifier prediction REPLACES the cascade output when
        # _meta_directive is True. On other branches or when directive
        # is disabled, behavior is shadow-only (observability).
        is_structured_single = shape_detection is not None and shape_detection.shape == "structured_single"
        should_run_meta = shape_detection is None or is_structured_single
        use_directive = self._meta_directive and is_structured_single
        if self._meta_classifier is not None and should_run_meta:
            try:
                shadow = self._meta_classifier.predict_shadow(
                    result,
                    column.sample_values,
                    engine_findings=engine_findings,
                )
                if shadow is not None:
                    directive_applied = False
                    if use_directive:
                        directive_result = self._apply_meta_directive(
                            shadow,
                            result,
                            column,
                            profile,
                        )
                        if directive_result is not None:
                            result = directive_result
                            directive_applied = True
                    self.emitter.emit(
                        MetaClassifierEvent(
                            column_id=shadow.column_id or column.column_id,
                            predicted_entity=shadow.predicted_entity,
                            confidence=shadow.confidence,
                            live_entity=shadow.live_entity,
                            agreement=shadow.agreement,
                            directive=directive_applied,
                            run_id=run_id or "",
                        )
                    )
            except Exception:
                logger.debug("MetaClassifier inference path failed", exc_info=True)

        # Sprint 11 Phase 9: tier-1 credential pattern-hit gate.
        # Evaluation is pure and observability-only — the decision
        # never mutates ``result``. Consumers of the GateRoutingEvent
        # stream use it to measure how often a strong tier-1 signal
        # would fire before promoting the gate to a directive rule.
        try:
            gate_decision = _evaluate_tier1_gate(result, engine_findings)
            if gate_decision is not None:
                self.emitter.emit(
                    GateRoutingEvent(
                        column_id=column.column_id,
                        gate_fired=gate_decision.gate_fired,
                        gate_reason=gate_decision.gate_reason,
                        primary_entity=gate_decision.primary_entity,
                        primary_confidence=gate_decision.primary_confidence,
                        primary_is_credential=gate_decision.primary_is_credential,
                        regex_confidence=gate_decision.regex_confidence,
                        regex_match_ratio=gate_decision.regex_match_ratio,
                        secret_scanner_confidence=gate_decision.secret_scanner_confidence,
                        run_id=run_id or "",
                    )
                )
        except Exception:  # pragma: no cover — defensive
            logger.debug("Tier-1 gate evaluation failed", exc_info=True)

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
        column_keys: list[str] = []
        all_pass1_findings: list[ClassificationFinding] = []

        for i, column in enumerate(columns):
            # Use column_id if set, otherwise generate a unique key
            key = column.column_id or f"_col_{i}_{column.column_name}"
            column_keys.append(key)
            findings = self.classify_column(
                column,
                profile,
                min_confidence=min_confidence,
                budget_ms=budget_ms,
                run_id=run_id,
                mask_samples=mask_samples,
                max_evidence_samples=max_evidence_samples,
            )
            pass1_results[key] = findings
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
        for column, key in zip(columns, column_keys):
            column_findings = pass1_results[key]
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
    def _suppress_phone_on_numeric_pii(
        findings: dict[str, ClassificationFinding],
    ) -> dict[str, ClassificationFinding]:
        """Directional PHONE suppression for numeric-format PII collisions.

        Numeric PII types (DATE_OF_BIRTH, CREDIT_CARD) contain digit-heavy
        values that spuriously match PHONE regex patterns. Unlike symmetric
        collision pairs, PHONE is *always* the false positive here — a column
        of dates or credit card numbers is never actually phone numbers.

        This suppression is unconditional (no confidence gap required) because
        the structural overlap is deterministic: any column where DATE_OF_BIRTH
        or CREDIT_CARD fires will also fire PHONE due to the digit patterns.
        """
        if "PHONE" not in findings:
            return findings
        winners = _PHONE_SUPPRESSION_WINNERS & findings.keys()
        if winners:
            winner_str = ", ".join(sorted(winners))
            logger.debug(
                "Directional PHONE suppression: dropping PHONE (%.2f) — %s present in findings",
                findings["PHONE"].confidence,
                winner_str,
            )
            del findings["PHONE"]
        return findings

    @staticmethod
    def _suppress_ml_when_strong_match(
        findings: dict[str, ClassificationFinding],
        engine_findings: dict[str, list[ClassificationFinding]],
    ) -> dict[str, ClassificationFinding]:
        """Suppress ML-only entity types when a non-ML engine has a strong match.

        If any non-ML engine produced a finding with confidence >= 0.85,
        remove ML-only findings for *different* entity types.  This prevents
        GLiNER2 from adding PERSON_NAME noise on columns where regex already
        confidently identified EMAIL, IP_ADDRESS, etc.

        ML findings that *agree* with non-ML findings are kept (they reinforce).
        ML findings on columns where no non-ML engine found anything are kept
        (they fill detection gaps — the whole point of the ML engine).
        """
        ml_engines = frozenset({"gliner2"})
        suppress_threshold = 0.85

        # Collect non-ML entity types with strong confidence
        non_ml_types: set[str] = set()
        for engine_name, efindings in engine_findings.items():
            if engine_name in ml_engines:
                continue
            for f in efindings:
                if f.confidence >= suppress_threshold:
                    non_ml_types.add(f.entity_type)

        if not non_ml_types:
            return findings  # No strong non-ML signal — keep everything

        # Identify ML-only entity types (in findings but only from ML engines)
        ml_only_types: set[str] = set()
        for entity_type, f in findings.items():
            if f.engine in ml_engines and entity_type not in non_ml_types:
                ml_only_types.add(entity_type)

        if not ml_only_types:
            return findings

        # Suppress ML-only types that differ from the strong non-ML signal
        suppressed = {et: f for et, f in findings.items() if et not in ml_only_types}
        for et in ml_only_types:
            logger.debug("Suppressed ML-only %s (non-ML has strong %s)", et, non_ml_types)
        return suppressed

    @staticmethod
    def _suppress_url_embedded_ips(
        findings: dict[str, ClassificationFinding],
    ) -> dict[str, ClassificationFinding]:
        """Suppress IP_ADDRESS findings whose every matched sample is a URL.

        RE2 doesn't support variable-width lookbehinds, so the ``ipv4_address``
        regex fires inside URL strings like ``http://192.168.1.1/api``. Worse,
        the ``url`` regex requires a letter-only TLD (``[a-zA-Z]{2,}``) and
        therefore does NOT match bare-IP URLs — so we can't rely on a URL
        co-finding to signal the suppression.

        Instead, inspect the IP_ADDRESS finding's ``sample_analysis.sample_matches``
        (the original values that matched). If every matched value begins with a
        URL scheme (``http://`` or ``https://``), the IP is never standalone and
        the finding is a false positive — drop it.

        A standalone IP ``192.168.1.1`` has no scheme and is preserved.
        A mixed column with both standalone IPs and IP-in-URL values still has
        standalone IPs in ``sample_matches``, so the finding is preserved.

        Kills the Sprint 5 Nemotron col_12 URL → IP_ADDRESS blind-mode FP.
        """
        ip_finding = findings.get("IP_ADDRESS")
        if ip_finding is None or ip_finding.sample_analysis is None:
            return findings

        matches = ip_finding.sample_analysis.sample_matches
        if not matches:
            return findings

        def _is_url_embedded(value: str) -> bool:
            stripped = value.strip().lower()
            return stripped.startswith("http://") or stripped.startswith("https://")

        if all(_is_url_embedded(v) for v in matches):
            logger.debug(
                "Suppressing IP_ADDRESS — all %d matched samples are URL-embedded",
                len(matches),
            )
            filtered = {et: f for et, f in findings.items() if et != "IP_ADDRESS"}
            return filtered
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
