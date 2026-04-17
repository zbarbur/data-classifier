"""Family-level taxonomy for classification findings.

Sprint 11 introduced a new public classification tier — **family** —
sitting between the fine-grained ``entity_type`` (26 labels) and the
coarse regulatory ``category`` (PII / Financial / Credential / Health).

Families are structural *handling* buckets.  Two entity types are in
the same family when downstream consumers (e.g. a DLP policy engine)
would apply the same handling rule to both.  For example:

* ``API_KEY``, ``OPAQUE_SECRET``, ``PRIVATE_KEY``, ``PASSWORD_HASH``
  and ``CREDENTIAL`` all share the ``CREDENTIAL`` family because a
  DLP policy treats them identically — reject, rotate, audit.
* ``CREDIT_CARD`` is split into its own ``PAYMENT_CARD`` family
  even though it shares the ``Financial`` category with IBAN,
  because PCI-DSS and GLBA are distinct regulatory regimes with
  distinct handling (tokenization, scope reduction).
* ``PERSON_NAME`` lives in ``CONTACT`` alongside EMAIL / PHONE /
  ADDRESS because a notice-and-opt-out policy treats them the same.

The relationship to ``category``:

* ``category`` is the **regulatory** classification (GDPR scope,
  HIPAA scope, GLBA scope, SOC2 scope). Four values.
* ``family`` is the **handling** classification (what does a DLP
  policy do with this?). Thirteen values.

Both are useful and both are kept on ``ClassificationFinding``.
Consumers that want regulatory bucketing read ``category``;
consumers that want policy-matching bucketing read ``family``.

The family taxonomy is the **sprint quality metric**.  Benchmarks
score classifier quality at the family level (Tier 1) and report
subtype-level accuracy (Tier 2) as informational only, because
within-family mislabels do not change downstream handling.

Rationale for each family grouping is captured in
``docs/research/meta_classifier/sprint11_family_ab_result.md``.
Structural changes to this mapping should update that memo so
the reasoning survives refactors.
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

# Every subtype emitted by the library must appear here or
# :func:`family_for` will warn and return the raw subtype (treated as
# its own singleton family).
ENTITY_TYPE_TO_FAMILY: dict[str, str] = {
    # ── DATE family ─────────────────────────────────────────────────
    # Date of birth in any format (US MM/DD/YYYY, EU DD/MM/YYYY, ISO-8601,
    # long-form "March 15 1985", etc.). Sprint 12 retired the
    # ``DATE_OF_BIRTH_EU`` subtype from emission; Sprint 14 completed
    # the cleanup by retraining the meta-classifier as v6 without the
    # DOB_EU class label and removing the compatibility alias.
    "DATE_OF_BIRTH": "DATE",
    # ── CREDENTIAL family ───────────────────────────────────────────
    # All credential subtypes share the same sensitivity tier and
    # the same DLP handling (reject, rotate, audit). The subtype
    # distinction is retained as metadata for vendor-aware tooling.
    "CREDENTIAL": "CREDENTIAL",
    "API_KEY": "CREDENTIAL",
    "OPAQUE_SECRET": "CREDENTIAL",
    "PRIVATE_KEY": "CREDENTIAL",
    "PASSWORD_HASH": "CREDENTIAL",
    # ── FINANCIAL family (GLBA-scoped bank identifiers) ─────────────
    # CREDIT_CARD is intentionally split into its own PAYMENT_CARD
    # family because PCI-DSS is a distinct regulatory regime with
    # distinct downstream handling.
    "ABA_ROUTING": "FINANCIAL",
    "IBAN": "FINANCIAL",
    "SWIFT_BIC": "FINANCIAL",
    "BANK_ACCOUNT": "FINANCIAL",
    # Generic FINANCIAL entity_type — used by the column-name engine
    # when a column looks financial but doesn't match a specific
    # subtype (e.g. "balance", "account_total"). Same family.
    "FINANCIAL": "FINANCIAL",
    # ── PAYMENT_CARD family (PCI-scoped) ────────────────────────────
    "CREDIT_CARD": "PAYMENT_CARD",
    # ── GOVERNMENT_ID family ────────────────────────────────────────
    # Government-issued identity numbers. Per-country structural
    # differences are preserved as subtypes; family reflects shared
    # handling.
    "SSN": "GOVERNMENT_ID",
    "CANADIAN_SIN": "GOVERNMENT_ID",
    "EIN": "GOVERNMENT_ID",
    "NATIONAL_ID": "GOVERNMENT_ID",
    # ── HEALTHCARE family (HIPAA 45 CFR 164) ────────────────────────
    "HEALTH": "HEALTHCARE",
    "NPI": "HEALTHCARE",
    "DEA_NUMBER": "HEALTHCARE",
    "MBI": "HEALTHCARE",
    # ── CONTACT family ──────────────────────────────────────────────
    # Contact/identity information with shared downstream policy
    # (notice, opt-out, right-to-delete).  PERSON_NAME lives here
    # intentionally: it is the dominant catch-all confusion target,
    # and including it in CONTACT correctly treats ADDRESS <->
    # PERSON_NAME as a within-family mislabel rather than a
    # cross-family quality error.
    "EMAIL": "CONTACT",
    "PHONE": "CONTACT",
    "ADDRESS": "CONTACT",
    "PERSON_NAME": "CONTACT",
    # ── URL family (singleton) ──────────────────────────────────────
    # URLs are heterogeneous (API endpoints, documentation, tracking
    # URLs, personal homepages) and don't share sensitivity with
    # CONTACT. Kept separate so URL <-> CONTACT is cross-family.
    "URL": "URL",
    # ── NETWORK family ──────────────────────────────────────────────
    "IP_ADDRESS": "NETWORK",
    "MAC_ADDRESS": "NETWORK",
    # ── CRYPTO family ───────────────────────────────────────────────
    "BITCOIN_ADDRESS": "CRYPTO",
    "ETHEREUM_ADDRESS": "CRYPTO",
    # ── VEHICLE family (singleton) ──────────────────────────────────
    "VIN": "VEHICLE",
    # ── DEMOGRAPHIC family ──────────────────────────────────────────
    # Low-sensitivity personal attributes used by the column-name
    # engine as generic fallbacks. These are PII but weaker
    # identifiers than EMAIL / SSN / ADDRESS — they carry
    # notice-and-aggregation obligations but not the stricter
    # handling the core CONTACT and GOVERNMENT_ID families do.
    "AGE": "DEMOGRAPHIC",
    "DEMOGRAPHIC": "DEMOGRAPHIC",
    # ── NEGATIVE family (singleton) ─────────────────────────────────
    # Non-sensitive columns. Singleton ensures any false positive
    # on a genuinely non-sensitive column counts as a cross-family
    # error — the binding product concern.
    "NEGATIVE": "NEGATIVE",
}

#: The canonical family vocabulary, in a stable alphabetical order
#: for reporting.
FAMILIES: tuple[str, ...] = (
    "CONTACT",
    "CREDENTIAL",
    "CRYPTO",
    "DATE",
    "DEMOGRAPHIC",
    "FINANCIAL",
    "GOVERNMENT_ID",
    "HEALTHCARE",
    "NEGATIVE",
    "NETWORK",
    "PAYMENT_CARD",
    "URL",
    "VEHICLE",
)


def family_for(entity_type: str | None) -> str:
    """Return the family name for an entity type label.

    ``None`` or empty string both map to the empty string so callers
    can distinguish "no prediction" from "unknown subtype".

    Unknown subtypes map to themselves (treated as singleton families)
    and emit a warning so the taxonomy map can be updated.
    """
    if not entity_type:
        return ""
    if entity_type in ENTITY_TYPE_TO_FAMILY:
        return ENTITY_TYPE_TO_FAMILY[entity_type]
    _log.warning(
        "family_for: no family mapping for entity_type=%r; using singleton. "
        "Update data_classifier.core.taxonomy.ENTITY_TYPE_TO_FAMILY.",
        entity_type,
    )
    return entity_type


__all__ = ["ENTITY_TYPE_TO_FAMILY", "FAMILIES", "family_for"]
