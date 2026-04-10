"""Regex classification engine — column name + sample value pattern matching.

Ported from BigQuery-connector/classifier/engine.py.  This is the iteration 1
engine: matches column names and sample values against profile regex rules.

Column name matching: first-match-wins against profile rules (identical to
the original BQ connector behavior).

Sample value matching: scans all provided sample values against the same
patterns, computing match counts and confidence based on the number of
matches (not the ratio).
"""

from __future__ import annotations

import logging

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ClassificationRule,
    ColumnInput,
    SampleAnalysis,
)
from data_classifier.engines.interface import ClassificationEngine

logger = logging.getLogger(__name__)


def _mask_value(value: str, entity_type: str) -> str:
    """Partially redact a matched value based on entity type."""
    if len(value) <= 4:
        return "*" * len(value)

    if entity_type in ("SSN", "NATIONAL_ID"):
        # Show last 4: "123-45-6789" → "***-**-6789"
        return "*" * (len(value) - 4) + value[-4:]

    if entity_type in ("CREDIT_CARD", "BANK_ACCOUNT"):
        # Show last 4: "4111111111111111" → "************1111"
        return "*" * (len(value) - 4) + value[-4:]

    if entity_type == "EMAIL":
        # Mask local part: "john@acme.com" → "j***@acme.com"
        at_idx = value.find("@")
        if at_idx > 1:
            return value[0] + "*" * (at_idx - 1) + value[at_idx:]
        return "*" * len(value)

    if entity_type == "PHONE":
        # Show last 4: "555-867-5309" → "***-***-5309"
        return "*" * (len(value) - 4) + value[-4:]

    # Default: show first and last char
    return value[0] + "*" * (len(value) - 2) + value[-1]


def _compute_sample_confidence(base_confidence: float, matches: int, validated: int) -> float:
    """Compute confidence from sample match results.

    Confidence reflects "how sure are we this entity type EXISTS" — based
    on match count (not ratio).  More matches = less likely coincidence.

    Validation failures reduce confidence proportionally.
    """
    if matches == 0:
        return 0.0

    # Validation adjustment
    if validated < matches:
        validation_ratio = validated / matches
        base_confidence *= validation_ratio

    # Match count adjustment
    if matches == 1:
        return base_confidence * 0.65
    elif matches <= 4:
        return base_confidence * 0.85
    elif matches <= 20:
        return base_confidence
    else:
        return min(base_confidence * 1.05, 1.0)


class RegexEngine(ClassificationEngine):
    """Regex-based classification engine.

    Two classification paths:
    1. Column name matching — regex patterns from the profile matched against
       the column name.  First matching rule wins.
    2. Sample value matching — same patterns matched against each sample value.
       Multiple entity types can be found in one column's samples.
    """

    name = "regex"
    order = 2
    min_confidence = 0.0
    supported_modes = frozenset({"structured", "unstructured", "prompt"})

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Classify a column using regex pattern matching.

        Runs two independent passes:
        1. Match column name against profile rules (first-match-wins)
        2. Match sample values against profile rules (all matches collected)

        Returns findings from both passes, deduplicated by entity_type
        (if both name and samples find the same type, the higher confidence wins).
        """
        findings: dict[str, ClassificationFinding] = {}

        # Pass 1: Column name matching (first-match-wins, identical to BQ connector)
        name_finding = self._match_column_name(column, profile)
        if name_finding is not None:
            findings[name_finding.entity_type] = name_finding

        # Pass 2: Sample value matching
        if column.sample_values:
            sample_findings = self._match_sample_values(
                column, profile, mask_samples=mask_samples, max_evidence_samples=max_evidence_samples
            )
            for sf in sample_findings:
                existing = findings.get(sf.entity_type)
                if existing is None or sf.confidence > existing.confidence:
                    findings[sf.entity_type] = sf

        # Apply min_confidence filter
        return [f for f in findings.values() if f.confidence >= min_confidence]

    def _match_column_name(
        self,
        column: ColumnInput,
        profile: ClassificationProfile,
    ) -> ClassificationFinding | None:
        """Match column name against profile rules.  First matching rule wins."""
        col_name = column.column_name

        for rule in profile.rules:
            if any(cp.search(col_name) for cp in rule.compiled_patterns):
                return ClassificationFinding(
                    column_id=column.column_id,
                    entity_type=rule.entity_type,
                    category=rule.category,
                    sensitivity=rule.sensitivity,
                    confidence=rule.confidence,
                    regulatory=list(rule.regulatory),
                    engine=self.name,
                    evidence=f"Column name '{col_name}' matches {rule.entity_type} pattern",
                )

        return None

    def _match_sample_values(
        self,
        column: ColumnInput,
        profile: ClassificationProfile,
        *,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Match sample values against all profile rules.

        Unlike column name matching, ALL rules are checked against ALL samples.
        Returns one finding per entity_type that has matches above threshold.
        """
        # Accumulate matches per rule
        rule_matches: dict[str, _RuleMatchAccumulator] = {}

        for value in column.sample_values:
            for rule in profile.rules:
                if any(cp.search(value) for cp in rule.compiled_patterns):
                    if rule.entity_type not in rule_matches:
                        rule_matches[rule.entity_type] = _RuleMatchAccumulator(rule)
                    rule_matches[rule.entity_type].add_match(value)

        # Convert accumulated matches to findings
        findings: list[ClassificationFinding] = []
        total_scanned = len(column.sample_values)

        for entity_type, acc in rule_matches.items():
            confidence = _compute_sample_confidence(acc.rule.confidence, acc.matched_count, acc.validated_count)

            if confidence <= 0.0:
                continue

            match_ratio = acc.matched_count / total_scanned if total_scanned > 0 else 0.0

            # Build sample_matches evidence list
            evidence_values = acc.matched_values[:max_evidence_samples]
            if mask_samples:
                evidence_values = [_mask_value(v, entity_type) for v in evidence_values]

            findings.append(
                ClassificationFinding(
                    column_id=column.column_id,
                    entity_type=entity_type,
                    category=acc.rule.category,
                    sensitivity=acc.rule.sensitivity,
                    confidence=confidence,
                    regulatory=list(acc.rule.regulatory),
                    engine=self.name,
                    evidence=(
                        f"Regex: {entity_type} format matched "
                        f"{acc.matched_count}/{total_scanned} samples "
                        f"({match_ratio:.0%})"
                    ),
                    sample_analysis=SampleAnalysis(
                        samples_scanned=total_scanned,
                        samples_matched=acc.matched_count,
                        samples_validated=acc.validated_count,
                        match_ratio=match_ratio,
                        sample_matches=evidence_values,
                    ),
                )
            )

        return findings


class _RuleMatchAccumulator:
    """Internal helper to accumulate sample matches for a single rule."""

    __slots__ = ("rule", "matched_count", "validated_count", "matched_values")

    def __init__(self, rule: ClassificationRule) -> None:
        self.rule = rule
        self.matched_count = 0
        self.validated_count = 0
        self.matched_values: list[str] = []

    def add_match(self, value: str) -> None:
        self.matched_count += 1
        # TODO: secondary validation (Luhn, SSN zero-group check, etc.)
        # For now, all matches count as validated
        self.validated_count += 1
        self.matched_values.append(value)
