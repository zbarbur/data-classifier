"""Table profile inference from sibling column findings.

Builds a domain profile from high-confidence findings across sibling columns.
Used in the orchestrator's two-pass classification to disambiguate collisions
on ambiguous columns using context from their siblings.

Domain Categories:
  - healthcare: columns suggesting medical/clinical data (NPI, DIAGNOSIS, MRN, etc.)
  - financial: columns suggesting financial/payment data (ABA_ROUTING, CREDIT_CARD, etc.)
  - customer_pii: columns suggesting personal identity data (SSN, EMAIL, PHONE, etc.)

Each domain has boost/suppress rules for entity types that are more or less
likely given the domain context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from data_classifier.core.types import ClassificationFinding

logger = logging.getLogger(__name__)

# Minimum confidence to include a finding in table profile inference
_PROFILE_CONFIDENCE_THRESHOLD: float = 0.70

# Minimum number of high-confidence sibling findings to trigger domain inference
_MIN_SIBLING_SIGNALS: int = 1

# ── Domain definitions ────────────────────────────────────────────────────────

# Entity types that signal each domain
_DOMAIN_SIGNALS: dict[str, set[str]] = {
    "healthcare": {
        "NPI",
        "DIAGNOSIS",
        "MRN",
        "DEA_NUMBER",
        "MEDICATION",
        "ICD_CODE",
        "MEDICARE_BENEFICIARY",
    },
    "financial": {
        "ABA_ROUTING",
        "CREDIT_CARD",
        "IBAN",
        "BIC",
        "BANK_ACCOUNT",
        "SALARY",
    },
    "customer_pii": {
        "SSN",
        "EMAIL",
        "PHONE",
        "DATE_OF_BIRTH",
        "FIRST_NAME",
        "LAST_NAME",
        "ADDRESS",
        "DRIVERS_LICENSE",
        "PASSPORT",
        "NATIONAL_ID",
        "CANADIAN_SIN",
    },
}

# Per-domain boost/suppress adjustments for ambiguous entity types.
# Positive = boost, negative = suppress.
_DOMAIN_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "healthcare": {
        "NPI": 0.10,
        "DIAGNOSIS": 0.10,
        "MRN": 0.10,
        "DEA_NUMBER": 0.10,
        "PHONE": -0.05,  # PHONE in healthcare table is less likely a personal phone
        "SSN": 0.05,  # Patients have SSNs
        "ABA_ROUTING": -0.10,  # ABA unlikely in healthcare context
    },
    "financial": {
        "ABA_ROUTING": 0.10,
        "CREDIT_CARD": 0.05,
        "IBAN": 0.05,
        "BANK_ACCOUNT": 0.10,
        "SSN": -0.05,  # SSN less likely in financial tables (tax ID, not SSN)
        "NPI": -0.10,  # NPI unlikely in financial context
    },
    "customer_pii": {
        "SSN": 0.10,
        "EMAIL": 0.05,
        "PHONE": 0.05,
        "CANADIAN_SIN": 0.05,
        "NPI": -0.10,  # NPI unlikely in customer PII context
        "ABA_ROUTING": -0.10,  # ABA unlikely in customer PII context
    },
}


@dataclass
class TableProfile:
    """Inferred domain profile for a table based on sibling column findings.

    Attributes:
        domains: Detected domains with their signal counts.
        primary_domain: The strongest domain signal, or None if ambiguous.
        signal_count: Total number of high-confidence sibling signals.
        entity_types_seen: Entity types found across all sibling columns.
    """

    domains: dict[str, int] = field(default_factory=dict)
    """Domain name -> count of entity types signaling this domain."""

    primary_domain: str | None = None
    """The dominant domain, if one is clearly strongest."""

    signal_count: int = 0
    """Total high-confidence sibling findings used for inference."""

    entity_types_seen: set[str] = field(default_factory=set)
    """All entity types detected across sibling columns."""


def build_table_profile(
    sibling_findings: list[ClassificationFinding],
    *,
    exclude_column_id: str | None = None,
    confidence_threshold: float = _PROFILE_CONFIDENCE_THRESHOLD,
) -> TableProfile:
    """Build a table profile from sibling column findings.

    Args:
        sibling_findings: All findings from other columns in the same table.
        exclude_column_id: Column ID to exclude from profile (the column being disambiguated).
        confidence_threshold: Minimum confidence to include a finding.

    Returns:
        TableProfile with inferred domain and entity types.
    """
    profile = TableProfile()

    # Filter to high-confidence siblings, excluding the target column
    strong_findings = [
        f
        for f in sibling_findings
        if f.confidence >= confidence_threshold and (exclude_column_id is None or f.column_id != exclude_column_id)
    ]

    if not strong_findings:
        return profile

    profile.signal_count = len(strong_findings)
    profile.entity_types_seen = {f.entity_type for f in strong_findings}

    # Count domain signals
    for f in strong_findings:
        for domain, signal_types in _DOMAIN_SIGNALS.items():
            if f.entity_type in signal_types:
                profile.domains[domain] = profile.domains.get(domain, 0) + 1

    # Determine primary domain (must have at least _MIN_SIBLING_SIGNALS)
    if profile.domains:
        best_domain = max(profile.domains, key=lambda d: profile.domains[d])
        if profile.domains[best_domain] >= _MIN_SIBLING_SIGNALS:
            # Check if it's clearly dominant (at least 1 more signal than runner-up,
            # or the only domain)
            sorted_domains = sorted(profile.domains.values(), reverse=True)
            if len(sorted_domains) == 1 or sorted_domains[0] > sorted_domains[1]:
                profile.primary_domain = best_domain

    logger.debug(
        "Table profile: domains=%s, primary=%s, signals=%d, types=%s",
        profile.domains,
        profile.primary_domain,
        profile.signal_count,
        profile.entity_types_seen,
    )

    return profile


def get_sibling_adjustment(
    entity_type: str,
    table_profile: TableProfile,
) -> float:
    """Get the confidence adjustment for an entity type given the table profile.

    Args:
        entity_type: The entity type to check.
        table_profile: The inferred table domain profile.

    Returns:
        Confidence adjustment (positive = boost, negative = suppress).
        Returns 0.0 if no adjustment applies.
    """
    if table_profile.primary_domain is None:
        return 0.0

    adjustments = _DOMAIN_ADJUSTMENTS.get(table_profile.primary_domain, {})
    return adjustments.get(entity_type, 0.0)
