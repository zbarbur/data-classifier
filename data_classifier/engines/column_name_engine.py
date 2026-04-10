"""Column Name Semantics Engine — fuzzy column name matching.

Classifies columns purely by their name, using fuzzy matching against
400+ sensitive field name variants. This is the second engine in the
cascade (order=1, runs before the regex engine at order=2).

Matching strategy (in priority order):
  1. Direct lookup: normalize column name → exact match in variants dict
  2. Abbreviation expansion: expand known abbreviations then re-lookup
  3. Multi-token subsequence: split column name into tokens, check if any
     contiguous subsequence matches a known variant

Confidence scaling:
  - Direct match: full confidence from JSON
  - Abbreviation expansion: confidence * 0.95
  - Multi-token subsequence: confidence * 0.85
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from data_classifier.core.types import (
    ClassificationFinding,
    ClassificationProfile,
    ColumnInput,
)
from data_classifier.engines.interface import ClassificationEngine

logger = logging.getLogger(__name__)

_COLUMN_NAMES_FILE = Path(__file__).parent.parent / "patterns" / "column_names.json"

# ── Abbreviation mappings ──────────────────────────────────────────────────

# Maps short abbreviations to their expanded form (used for lookup after expansion)
_ABBREVIATIONS: dict[str, str] = {
    "dob": "date_of_birth",
    "cc": "credit_card",
    "cc_num": "credit_card",
    "cc_no": "credit_card",
    "ccn": "credit_card",
    "dl": "drivers_license",
    "dl_num": "dl_number",
    "dl_no": "dl_number",
    "fn": "first_name",
    "ln": "last_name",
    "fname": "first_name",
    "lname": "last_name",
    "addr": "address",
    "acct": "account_number",
    "acct_num": "account_number",
    "acct_no": "account_number",
    "pwd": "password",
    "passwd": "password",
    "tel": "telephone",
    "mob": "mobile",
    "ph": "phone",
    "ph_num": "phone_number",
    "ssn": "social_security_number",
    "dea": "dea_number",
    "npi": "npi_number",
    "mbi": "medicare_beneficiary",
    "mrn": "medical_record_number",
    "vin": "vehicle_identification_number",
    "ein": "employer_identification_number",
    "sin": "social_insurance_number",
    "ip": "ip_address",
    "iban": "iban",
    "bic": "bic_code",
    "btc": "bitcoin_address",
    "eth": "ethereum_address",
    "aba": "aba_routing",
}

# Regex for splitting camelCase into tokens
_CAMEL_SPLIT = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


# ── Variant entry ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _VariantEntry:
    """Metadata for a matched column name variant."""

    entity_type: str
    category: str
    sensitivity: str
    confidence: float


# ── Normalization ──────────────────────────────────────────────────────────


def _normalize(name: str) -> str:
    """Normalize a column name for lookup.

    Lowercases, splits camelCase, replaces hyphens/spaces with underscores,
    and collapses multiple underscores.
    """
    # Split camelCase first (e.g. "customerSsn" → "customer_Ssn")
    name = _CAMEL_SPLIT.sub("_", name)
    # Lowercase
    name = name.lower()
    # Replace hyphens and spaces with underscores
    name = name.replace("-", "_").replace(" ", "_")
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing underscores
    name = name.strip("_")
    return name


def _tokenize(normalized: str) -> list[str]:
    """Split a normalized name into tokens on underscores."""
    return [t for t in normalized.split("_") if t]


# ── Engine ─────────────────────────────────────────────────────────────────


class ColumnNameEngine(ClassificationEngine):
    """Column name semantics engine — fuzzy column name classification.

    Classifies columns by matching their name against a curated dictionary
    of 400+ sensitive field name variants. Runs before the regex engine
    (order=1) to provide fast, high-confidence column name classification.
    """

    name = "column_name"
    order = 1
    min_confidence = 0.0
    supported_modes = frozenset({"structured"})

    def __init__(self) -> None:
        self._lookup: dict[str, _VariantEntry] = {}
        self._loaded = False

    def startup(self) -> None:
        """Load column_names.json and build the normalized lookup dict."""
        self._lookup = _load_column_names()
        self._loaded = True
        logger.info("ColumnNameEngine: loaded %d column name variants", len(self._lookup))

    def _ensure_started(self) -> None:
        """Lazy startup if not explicitly called."""
        if not self._loaded:
            self.startup()

    def classify_column(
        self,
        column: ColumnInput,
        *,
        profile: ClassificationProfile | None = None,
        min_confidence: float = 0.5,
        mask_samples: bool = False,
        max_evidence_samples: int = 5,
    ) -> list[ClassificationFinding]:
        """Classify a column by its name.

        Tries three matching strategies in order:
        1. Direct lookup after normalization
        2. Abbreviation expansion
        3. Multi-token subsequence matching

        Returns a list with at most one finding, or empty if no match.
        """
        self._ensure_started()

        normalized = _normalize(column.column_name)

        # Strategy 1: Direct lookup
        entry = self._lookup.get(normalized)
        if entry is not None:
            confidence = entry.confidence
            evidence = f"Column name '{column.column_name}' directly matches {entry.entity_type} variant '{normalized}'"
            return self._make_finding(column, entry, confidence, evidence, min_confidence)

        # Strategy 2: Abbreviation expansion
        expanded = _ABBREVIATIONS.get(normalized)
        if expanded is not None:
            entry = self._lookup.get(_normalize(expanded))
            if entry is not None:
                confidence = entry.confidence * 0.95
                evidence = (
                    f"Column name '{column.column_name}' matches {entry.entity_type} "
                    f"via abbreviation expansion '{normalized}' -> '{expanded}'"
                )
                return self._make_finding(column, entry, confidence, evidence, min_confidence)

        # Strategy 3: Multi-token subsequence matching
        tokens = _tokenize(normalized)
        if len(tokens) >= 2:
            result = self._try_subsequence_match(column, tokens, min_confidence)
            if result:
                return result

        return []

    def _try_subsequence_match(
        self,
        column: ColumnInput,
        tokens: list[str],
        min_confidence: float,
    ) -> list[ClassificationFinding]:
        """Try matching contiguous token subsequences against the lookup.

        Tries longer subsequences first (more specific matches preferred).
        Also tries abbreviation expansion on individual tokens within subsequences.
        """
        n = len(tokens)
        # Try from longest to shortest subsequences (skip full — already tried as direct)
        for length in range(n, 0, -1):
            for start in range(n - length + 1):
                subseq = "_".join(tokens[start : start + length])
                entry = self._lookup.get(subseq)
                if entry is not None:
                    confidence = entry.confidence * 0.85
                    evidence = (
                        f"Column name '{column.column_name}' matches {entry.entity_type} via subsequence '{subseq}'"
                    )
                    return self._make_finding(column, entry, confidence, evidence, min_confidence)

                # Try abbreviation expansion on the subsequence
                expanded = _ABBREVIATIONS.get(subseq)
                if expanded is not None:
                    entry = self._lookup.get(_normalize(expanded))
                    if entry is not None:
                        confidence = entry.confidence * 0.85 * 0.95
                        evidence = (
                            f"Column name '{column.column_name}' matches {entry.entity_type} "
                            f"via subsequence abbreviation '{subseq}' -> '{expanded}'"
                        )
                        return self._make_finding(column, entry, confidence, evidence, min_confidence)

        return []

    def _make_finding(
        self,
        column: ColumnInput,
        entry: _VariantEntry,
        confidence: float,
        evidence: str,
        min_confidence: float,
    ) -> list[ClassificationFinding]:
        """Create a ClassificationFinding if confidence meets threshold."""
        if confidence < min_confidence:
            return []
        return [
            ClassificationFinding(
                column_id=column.column_id,
                entity_type=entry.entity_type,
                category=entry.category,
                sensitivity=entry.sensitivity,
                confidence=confidence,
                regulatory=[],
                engine=self.name,
                evidence=evidence,
            )
        ]


# ── JSON loading ───────────────────────────────────────────────────────────


def _load_column_names() -> dict[str, _VariantEntry]:
    """Load column_names.json and build normalized lookup dict."""
    with open(_COLUMN_NAMES_FILE) as fh:
        raw = json.load(fh)

    lookup: dict[str, _VariantEntry] = {}
    for et in raw["entity_types"]:
        entry = _VariantEntry(
            entity_type=et["entity_type"],
            category=et["category"],
            sensitivity=et["sensitivity"],
            confidence=et["confidence"],
        )
        for variant in et["variants"]:
            normalized = _normalize(variant)
            if normalized not in lookup:
                lookup[normalized] = entry

    return lookup
