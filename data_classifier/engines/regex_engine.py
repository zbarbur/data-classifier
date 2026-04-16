"""Regex classification engine — RE2 two-phase matching.

Implements the spec's two-phase RE2 architecture:
  Phase 1 (screening): All content patterns compiled into an RE2 Set.
    One pass identifies WHICH patterns matched.  C++ execution, releases GIL.
  Phase 2 (extraction): Only matched patterns run individually to extract
    positions and values.  Secondary validators (Luhn, format checks) applied.

Two classification paths:
  1. Column name matching — profile rules matched against the column name.
     Uses RE2 Set for screening, then individual pattern extraction.
  2. Sample value matching — content patterns from the pattern library matched
     against each sample value.  All matches collected across all values.
"""

from __future__ import annotations

import logging
import typing
from dataclasses import dataclass
from pathlib import Path

import re2

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
    SampleAnalysis,
)
from data_classifier.engines.interface import ClassificationEngine
from data_classifier.engines.validators import VALIDATORS
from data_classifier.patterns import ContentPattern, load_default_patterns
from data_classifier.patterns._decoder import decode_encoded_strings

logger = logging.getLogger(__name__)

# Default context boost/suppress factor
_CONTEXT_BOOST = 0.30
_CONTEXT_SUPPRESS = 0.30
_CONTEXT_WINDOW_TOKENS = 10  # tokens before/after match to scan


# ── Masking ──────────────────────────────────────────────────────────────────


def _mask_value(value: str, entity_type: str) -> str:
    """Partially redact a matched value based on entity type."""
    if len(value) <= 4:
        return "*" * len(value)

    if entity_type in ("SSN", "NATIONAL_ID"):
        return "*" * (len(value) - 4) + value[-4:]

    if entity_type in ("CREDIT_CARD", "BANK_ACCOUNT"):
        return "*" * (len(value) - 4) + value[-4:]

    if entity_type == "EMAIL":
        at_idx = value.find("@")
        if at_idx > 1:
            return value[0] + "*" * (at_idx - 1) + value[at_idx:]
        return "*" * len(value)

    if entity_type == "PHONE":
        return "*" * (len(value) - 4) + value[-4:]

    return value[0] + "*" * (len(value) - 2) + value[-1]


# ── Confidence ───────────────────────────────────────────────────────────────


def _compute_sample_confidence(base_confidence: float, matches: int, validated: int) -> float:
    """Compute confidence from sample match results.

    Confidence reflects "how sure are we this entity type EXISTS" — based
    on match count (not ratio).  Validation failures reduce proportionally.
    """
    if matches == 0:
        return 0.0

    if validated < matches:
        base_confidence *= validated / matches

    if matches == 1:
        return base_confidence * 0.65
    elif matches <= 4:
        return base_confidence * 0.85
    elif matches <= 20:
        return base_confidence
    else:
        return min(base_confidence * 1.05, 1.0)


# ── Stopword / Allowlist / Context ──────────────────────────────────────────


_GLOBAL_STOPWORDS_FILE: Path = Path(__file__).parent.parent / "patterns" / "stopwords.json"


def _load_global_stopwords() -> set[str]:
    """Load global stopwords from stopwords.json (known placeholder values).

    Entries may use the optional ``xor:`` / ``b64:`` encoding prefixes
    handled by :func:`data_classifier.patterns._decoder.decode_encoded_strings`
    so credential-shaped placeholder values (Stripe docs test keys,
    PAT placeholders) can live in the file without tripping GitHub
    push-protection on commit. Decoding happens before the
    case-fold so the base64 body is never lowercased.
    """
    import json

    if _GLOBAL_STOPWORDS_FILE.exists():
        with open(_GLOBAL_STOPWORDS_FILE) as f:
            data = json.load(f)
        decoded = decode_encoded_strings(data.get("stopwords", []))
        return {s.lower() for s in decoded}
    return set()


_GLOBAL_STOPWORDS: set[str] | None = None


def _get_global_stopwords() -> set[str]:
    global _GLOBAL_STOPWORDS
    if _GLOBAL_STOPWORDS is None:
        _GLOBAL_STOPWORDS = _load_global_stopwords()
    return _GLOBAL_STOPWORDS


def _is_stopword(value: str, pattern: ContentPattern) -> bool:
    """Check if the matched value is a known placeholder/test value."""
    lower = value.lower().strip()
    # Check pattern-specific stopwords
    if pattern.stopwords and lower in {s.lower() for s in pattern.stopwords}:
        return True
    # Check global stopwords
    return lower in _get_global_stopwords()


def _matches_allowlist(value: str, pattern: ContentPattern) -> bool:
    """Check if the matched value matches any allowlist regex (known FP patterns)."""
    for allow_re in pattern.allowlist_patterns:
        try:
            if re2.search(allow_re, value):
                return True
        except Exception:
            pass
    return False


def _column_hint_allows_pattern(column_name: str, pattern: ContentPattern) -> bool:
    """Check whether the column name satisfies a pattern's column hint gate.

    Patterns with ``requires_column_hint=True`` only fire when the column
    name contains one of ``column_hint_keywords`` (case-insensitive substring
    match). This prevents content-based FPs for patterns that cannot be
    reliably distinguished from similar content in other contexts —
    e.g. random passwords, which look like any mixed-class short string.

    Patterns without the gate (the default) always pass.
    """
    if not pattern.requires_column_hint:
        return True
    if not pattern.column_hint_keywords:
        return False
    name_lower = column_name.lower()
    return any(kw.lower() in name_lower for kw in pattern.column_hint_keywords)


def _compute_context_adjustment(value: str, pattern: ContentPattern) -> float:
    """Scan text around the match for context words, return confidence adjustment.

    Positive = boost, negative = suppress.  Checks case-insensitively within
    a window of tokens around the value.
    """
    if not pattern.context_words_boost and not pattern.context_words_suppress:
        return 0.0

    # Tokenize the full value text (for free-text columns, the value may contain surrounding text)
    tokens = value.lower().split()
    token_set = set(tokens)

    # Check boost words
    boost_words = {w.lower() for w in pattern.context_words_boost}
    if boost_words & token_set:
        return _CONTEXT_BOOST

    # Check suppress words
    suppress_words = {w.lower() for w in pattern.context_words_suppress}
    if suppress_words & token_set:
        return -_CONTEXT_SUPPRESS

    return 0.0


# ── RE2 Pattern Set ─────────────────────────────────────────────────────────


@dataclass
class _CompiledPatternSet:
    """Pre-compiled RE2 Set for two-phase matching."""

    re2_set: re2.Set
    """Compiled RE2 Set for Phase 1 screening."""

    patterns: list[ContentPattern]
    """Pattern metadata indexed by Set position."""

    individual: list[re2._Regexp]
    """Individually compiled patterns for Phase 2 extraction."""

    validators: list[typing.Callable | None]
    """Validator function per pattern (None = no validation)."""


def _build_content_pattern_set(patterns: list[ContentPattern]) -> _CompiledPatternSet:
    """Compile all content patterns into an RE2 Set + individual patterns."""
    re2_set = re2.Set(re2._Anchor.UNANCHORED)
    individual = []
    validators = []

    for p in patterns:
        re2_set.Add(p.regex)
        individual.append(re2.compile(p.regex))
        validators.append(VALIDATORS.get(p.validator))

    re2_set.Compile()
    return _CompiledPatternSet(
        re2_set=re2_set,
        patterns=patterns,
        individual=individual,
        validators=validators,
    )


def _build_profile_pattern_set(profile: ClassificationProfile) -> _CompiledPatternSet:
    """Compile profile column-name patterns into an RE2 Set.

    Each rule may have multiple patterns.  We flatten them into a single Set
    and track which rule each Set index maps back to.
    """
    re2_set = re2.Set(re2._Anchor.UNANCHORED)
    flat_patterns: list[ContentPattern] = []
    individual = []
    validators: list[typing.Callable | None] = []

    for rule in profile.rules:
        for pattern_str in rule.patterns:
            # Column name patterns use case-insensitive matching
            re2_pattern = f"(?i){pattern_str}"
            re2_set.Add(re2_pattern)
            individual.append(re2.compile(re2_pattern))
            validators.append(None)
            # Store rule metadata as a ContentPattern for uniform handling
            flat_patterns.append(
                ContentPattern(
                    name=f"profile:{rule.entity_type}",
                    regex=pattern_str,
                    entity_type=rule.entity_type,
                    category=rule.category,
                    sensitivity=rule.sensitivity,
                    confidence=rule.confidence,
                )
            )

    re2_set.Compile()
    return _CompiledPatternSet(
        re2_set=re2_set,
        patterns=flat_patterns,
        individual=individual,
        validators=validators,
    )


# ── Match Accumulator ────────────────────────────────────────────────────────


class _MatchAccumulator:
    """Accumulates sample matches for a single entity type."""

    __slots__ = ("pattern", "matched_count", "validated_count", "matched_values")

    def __init__(self, pattern: ContentPattern) -> None:
        self.pattern = pattern
        self.matched_count = 0
        self.validated_count = 0
        self.matched_values: list[str] = []

    def add_match(self, value: str, *, validated: bool = True) -> None:
        self.matched_count += 1
        if validated:
            self.validated_count += 1
        self.matched_values.append(value)


# ── Engine ───────────────────────────────────────────────────────────────────


class RegexEngine(ClassificationEngine):
    """RE2-based regex classification engine.

    Two-phase matching per spec:
      Phase 1: RE2 Set screens all patterns in one C++ pass
      Phase 2: Only matched patterns extract individually + run validators

    Two classification paths:
      1. Column name matching — profile rules against column name
      2. Sample value matching — content patterns against sample values
    """

    name = "regex"
    order = 2
    authority = 5
    min_confidence = 0.0
    supported_modes = frozenset({"structured", "unstructured", "prompt"})

    def __init__(self) -> None:
        self._content_patterns: list[ContentPattern] = []
        self._content_set: _CompiledPatternSet | None = None
        self._profile_sets: dict[str, _CompiledPatternSet] = {}

    def startup(self) -> None:
        """Load and compile the default content pattern library."""
        self._content_patterns = load_default_patterns()
        self._content_set = _build_content_pattern_set(self._content_patterns)
        logger.info("RegexEngine: compiled %d content patterns into RE2 Set", len(self._content_patterns))

    def _ensure_started(self) -> None:
        """Lazy startup if not explicitly called."""
        if self._content_set is None:
            self.startup()

    def _get_profile_set(self, profile: ClassificationProfile) -> _CompiledPatternSet:
        """Get or build the RE2 Set for a profile's column-name patterns."""
        if profile.name not in self._profile_sets:
            self._profile_sets[profile.name] = _build_profile_pattern_set(profile)
        return self._profile_sets[profile.name]

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Classify a column using RE2 two-phase matching.

        Pass 1: Match column name against profile rules (first-match-wins)
        Pass 2: Match sample values against content pattern library
        """
        self._ensure_started()
        findings: dict[str, ClassificationFinding] = {}

        # Pass 1: Column name matching via RE2 Set
        name_finding = self._match_column_name(column, profile)
        if name_finding is not None:
            findings[name_finding.entity_type] = name_finding

        # Pass 2: Sample value matching via RE2 Set
        if column.sample_values and self._content_set is not None:
            sample_findings = self._match_sample_values(
                column,
                self._content_set,
                mask_samples=mask_samples,
                max_evidence_samples=max_evidence_samples,
            )
            for sf in sample_findings:
                existing = findings.get(sf.entity_type)
                if existing is None or sf.confidence > existing.confidence:
                    findings[sf.entity_type] = sf

        return [f for f in findings.values() if f.confidence >= min_confidence]

    def _match_column_name(
        self,
        column: ColumnInput,
        profile: ClassificationProfile,
    ) -> ClassificationFinding | None:
        """Match column name against profile rules using RE2.

        First matching rule wins (preserves profile rule ordering).
        Uses RE2 Set for screening, then returns the first hit's rule.
        """
        pset = self._get_profile_set(profile)
        col_name = column.column_name

        # Phase 1: RE2 Set screening
        hit_indices = pset.re2_set.Match(col_name)
        if not hit_indices:
            return None

        # The profile Set is built in rule order (rule 0 patterns first, then rule 1, etc.)
        # We need the FIRST rule that matched, not the first pattern.
        # Since rules are added in order, the lowest index maps to the earliest rule.
        first_idx = min(hit_indices)
        p = pset.patterns[first_idx]

        # Look up the full rule from the profile for regulatory info
        rule = next((r for r in profile.rules if r.entity_type == p.entity_type), None)

        return ClassificationFinding(
            column_id=column.column_id,
            entity_type=p.entity_type,
            category=p.category,
            sensitivity=p.sensitivity,
            confidence=p.confidence,
            regulatory=list(rule.regulatory) if rule else [],
            engine=self.name,
            evidence=f"Column name '{col_name}' matches {p.entity_type} pattern",
        )

    def _match_sample_values(
        self,
        column: ColumnInput,
        pset: _CompiledPatternSet,
        *,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Phase 1+2 on sample values: RE2 Set screen → extract + validate.

        Scans ALL sample values.  For each value:
          Phase 1: RE2 Set identifies which patterns matched (one C++ pass)
          Phase 2: For each hit, run the individual pattern + validator
        """
        accumulators: dict[str, _MatchAccumulator] = {}
        total_scanned = len(column.sample_values)

        for value in column.sample_values:
            # Phase 1: RE2 Set screening — one pass per value
            hit_indices = pset.re2_set.Match(value)
            if not hit_indices:
                continue

            # Phase 2: Extract + validate + suppress for each hit
            for idx in hit_indices:
                p = pset.patterns[idx]
                validator = pset.validators[idx]

                # Column hint gate — some patterns (e.g. random_password)
                # only fire when the column name hints at them
                if not _column_hint_allows_pattern(column.column_name, p):
                    continue

                # Stopword check — known placeholder values → skip entirely
                if _is_stopword(value, p):
                    continue

                # Allowlist check — known FP patterns → skip
                if _matches_allowlist(value, p):
                    continue

                # Run validator if present
                validated = True
                if validator is not None:
                    try:
                        validated = validator(value)
                    except Exception:
                        validated = False

                entity_type = p.entity_type
                if entity_type not in accumulators:
                    accumulators[entity_type] = _MatchAccumulator(p)
                accumulators[entity_type].add_match(value, validated=validated)

        # Convert to findings with context adjustment
        findings: list[ClassificationFinding] = []
        for entity_type, acc in accumulators.items():
            confidence = _compute_sample_confidence(
                acc.pattern.confidence,
                acc.matched_count,
                acc.validated_count,
            )
            if confidence <= 0.0:
                continue

            # Context boosting — scan matched values for context words
            if acc.pattern.context_words_boost or acc.pattern.context_words_suppress:
                adjustments = [_compute_context_adjustment(v, acc.pattern) for v in acc.matched_values]
                if adjustments:
                    avg_adj = sum(adjustments) / len(adjustments)
                    confidence = max(0.0, min(1.0, confidence + avg_adj))

            match_ratio = acc.matched_count / total_scanned if total_scanned > 0 else 0.0

            evidence_values = acc.matched_values[:max_evidence_samples]
            if mask_samples:
                evidence_values = [_mask_value(v, entity_type) for v in evidence_values]

            findings.append(
                ClassificationFinding(
                    column_id=column.column_id,
                    entity_type=entity_type,
                    category=acc.pattern.category,
                    sensitivity=acc.pattern.sensitivity,
                    confidence=confidence,
                    regulatory=[],  # Content patterns don't carry regulatory — profile rules do
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
