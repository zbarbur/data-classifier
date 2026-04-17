"""Finding-level credential noise suppressor (F2).

Drops individual CREDENTIAL-family findings whose matched value is a
config literal (R2) or placeholder (R3), without touching other
findings in the same column.  This is the revised F2 spec — the
original shard-level suppressor was archived because it killed 6.6%
of true positives on mixed-entity columns under multi-label scoring.

Design constraints:
- Only CREDENTIAL-family findings are inspected (OPAQUE_SECRET,
  API_KEY, PRIVATE_KEY, PASSWORD, PASSWORD_HASH, CREDENTIAL).
- A finding with no ``sample_analysis`` is never suppressed (safety:
  don't suppress what you can't inspect).
- Non-CREDENTIAL findings are always kept, even if their matched
  values look placeholder-y.
"""

from __future__ import annotations

import logging
import re

from data_classifier.core.types import ClassificationFinding

logger = logging.getLogger(__name__)

# ── R2: config literal ────────────────────────────────────────────────────────
# Values that look like config assignments: `= 42`, `= true`, `= "hello"`, etc.
CONFIG_LITERAL = re.compile(
    r"=\s*(?:\d+|true|false|null|None|INFO|DEBUG|WARN|ERROR|"
    r'OFF|ON|"[\d\s\w]{1,15}")\s*[;,]*\s*$',
    re.IGNORECASE,
)

# ── R3: placeholder noise ────────────────────────────────────────────────────
# Repeated mask characters: xxxx, ****, ####, ~~~~
PLACEHOLDER_X = re.compile(r"[xX*]{4,}|#{4,}|~{4,}")

# Bracketed placeholders: [PASSWORD], [TOKEN], <API_KEY>, etc.
BRACKET_PH = re.compile(
    r"\[(?:PASSWORD|IP|TOKEN|KEY|SECRET|"
    r"REDACTED|EXAMPLE|REPLACE|YOUR|USER|HOST)\]"
    r"|<[A-Z_]{3,}>",
    re.IGNORECASE,
)

# Entity types belonging to the CREDENTIAL family.
_CREDENTIAL_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "CREDENTIAL",
        "API_KEY",
        "OPAQUE_SECRET",
        "PRIVATE_KEY",
        "PASSWORD",
        "PASSWORD_HASH",
    }
)


def _is_noise_value(value: str) -> bool:
    """Return True if *value* matches any noise pattern (R2 or R3)."""
    if CONFIG_LITERAL.search(value):
        return True
    if PLACEHOLDER_X.search(value):
        return True
    if BRACKET_PH.search(value):
        return True
    return False


def _finding_is_credential_noise(finding: ClassificationFinding) -> bool:
    """Return True if *finding* is a CREDENTIAL-family noise match.

    Safety: findings with no ``sample_analysis`` are never suppressed —
    we cannot inspect what we cannot see.
    """
    # Only inspect CREDENTIAL-family findings
    if finding.family != "CREDENTIAL" and finding.entity_type not in _CREDENTIAL_ENTITY_TYPES:
        return False

    # Safety: never suppress findings we cannot inspect
    if finding.sample_analysis is None:
        return False

    # Check each matched sample value — if ALL are noise, suppress
    matched = finding.sample_analysis.sample_matches
    if not matched:
        return False

    return all(_is_noise_value(v) for v in matched)


def filter_credential_noise(
    findings: list[ClassificationFinding],
) -> list[ClassificationFinding]:
    """Drop CREDENTIAL-family findings whose matched values are all noise.

    Non-CREDENTIAL findings pass through unconditionally. CREDENTIAL
    findings with no ``sample_analysis`` or with at least one non-noise
    matched value are kept.

    Returns a new list; the input is not mutated.
    """
    kept: list[ClassificationFinding] = []
    for f in findings:
        if _finding_is_credential_noise(f):
            logger.debug(
                "credential_gate: suppressing %s finding (column=%s) — all matched values are noise",
                f.entity_type,
                f.column_id,
            )
            continue
        kept.append(f)
    return kept
