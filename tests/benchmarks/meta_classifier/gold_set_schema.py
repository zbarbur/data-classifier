"""Schema + sanity validator for the M4c heterogeneous gold set.

Used by ``test_gold_set_schema.py`` and as a drift-check before
downstream M4 sub-items (M4b, M4d, M4e) consume the gold set.

The validator is structural — it does NOT enforce label correctness
(that's the human labeler's job). It enforces:

- Every row has the required schema fields with the right types
- Every label in ``true_labels`` exists in
  ``ENTITY_TYPE_TO_FAMILY``
- ``true_labels_family`` is consistent with ``true_labels``
  (auto-derivable, catches hand-edit drift)
- ``true_shape`` is one of the three valid Sprint 13 router branches
- ``encoding`` is ``plaintext`` or ``xor``
- ``review_status`` is one of ``prefilled`` / ``human_reviewed`` /
  ``needs_review``
- ``column_id`` values are unique across the set
- ``values`` is non-empty (prevalence floor ≥1 instance)
- XOR-encoded values are actually decodable (catches corruption)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from data_classifier.core.taxonomy import ENTITY_TYPE_TO_FAMILY, family_for
from data_classifier.patterns._decoder import decode_encoded_strings

REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "column_id": str,
    "source": str,
    "source_reference": str,
    "encoding": str,
    "values": list,
    "true_shape": str,
    "true_labels": list,
    "true_labels_family": list,
    "true_labels_prevalence": dict,
    "review_status": str,
    "annotator": str,
    "annotated_on": str,
    "notes": str,
}

VALID_SHAPES = frozenset({"structured_single", "free_text_heterogeneous", "opaque_tokens"})
VALID_ENCODINGS = frozenset({"plaintext", "xor"})
VALID_REVIEW_STATUS = frozenset({"prefilled", "human_reviewed", "needs_review"})


@dataclass
class ValidationIssue:
    """A single validation failure.

    ``level`` is ``error`` (breaks the contract) or ``warning``
    (worth flagging but not blocking). Tests treat errors as failing.
    """

    row_idx: int
    column_id: str | None
    field: str
    level: str  # "error" | "warning"
    message: str

    def __str__(self) -> str:
        ident = self.column_id or f"row[{self.row_idx}]"
        return f"[{self.level.upper()}] {ident}.{self.field}: {self.message}"


def _check_field_types(row: dict, row_idx: int, issues: list[ValidationIssue]) -> None:
    column_id = row.get("column_id")
    for field_name, expected_type in REQUIRED_FIELDS.items():
        if field_name not in row:
            issues.append(
                ValidationIssue(
                    row_idx=row_idx,
                    column_id=column_id,
                    field=field_name,
                    level="error",
                    message="missing required field",
                )
            )
            continue
        value = row[field_name]
        if not isinstance(value, expected_type):
            issues.append(
                ValidationIssue(
                    row_idx=row_idx,
                    column_id=column_id,
                    field=field_name,
                    level="error",
                    message=f"expected {expected_type}, got {type(value).__name__}",
                )
            )


def _check_enum_fields(row: dict, row_idx: int, issues: list[ValidationIssue]) -> None:
    column_id = row.get("column_id")
    if row.get("true_shape") not in VALID_SHAPES:
        issues.append(
            ValidationIssue(
                row_idx=row_idx,
                column_id=column_id,
                field="true_shape",
                level="error",
                message=f"not one of {sorted(VALID_SHAPES)}",
            )
        )
    if row.get("encoding") not in VALID_ENCODINGS:
        issues.append(
            ValidationIssue(
                row_idx=row_idx,
                column_id=column_id,
                field="encoding",
                level="error",
                message=f"not one of {sorted(VALID_ENCODINGS)}",
            )
        )
    if row.get("review_status") not in VALID_REVIEW_STATUS:
        issues.append(
            ValidationIssue(
                row_idx=row_idx,
                column_id=column_id,
                field="review_status",
                level="error",
                message=f"not one of {sorted(VALID_REVIEW_STATUS)}",
            )
        )


def _check_labels_known(row: dict, row_idx: int, issues: list[ValidationIssue]) -> None:
    column_id = row.get("column_id")
    labels = row.get("true_labels", [])
    if not isinstance(labels, list):
        return  # already caught by _check_field_types
    for lbl in labels:
        if lbl not in ENTITY_TYPE_TO_FAMILY:
            issues.append(
                ValidationIssue(
                    row_idx=row_idx,
                    column_id=column_id,
                    field="true_labels",
                    level="error",
                    message=f"unknown entity type {lbl!r} (not in ENTITY_TYPE_TO_FAMILY)",
                )
            )


def _check_family_consistency(row: dict, row_idx: int, issues: list[ValidationIssue]) -> None:
    """``true_labels_family`` must equal the family-derived set of ``true_labels``."""
    column_id = row.get("column_id")
    labels = row.get("true_labels", [])
    stored_families = row.get("true_labels_family", [])
    if not isinstance(labels, list) or not isinstance(stored_families, list):
        return
    expected = sorted({family_for(lbl) for lbl in labels if family_for(lbl)})
    if sorted(stored_families) != expected:
        issues.append(
            ValidationIssue(
                row_idx=row_idx,
                column_id=column_id,
                field="true_labels_family",
                level="error",
                message=f"inconsistent with true_labels: stored={stored_families}, expected={expected}",
            )
        )


def _check_prevalence_floor(row: dict, row_idx: int, issues: list[ValidationIssue]) -> None:
    """At least one value (prevalence floor from M4c spec: ≥1 observed instance)."""
    column_id = row.get("column_id")
    values = row.get("values", [])
    if isinstance(values, list) and len(values) < 1:
        issues.append(
            ValidationIssue(
                row_idx=row_idx,
                column_id=column_id,
                field="values",
                level="error",
                message="empty values — violates prevalence floor (≥1 observed instance)",
            )
        )


def _check_xor_roundtrip(row: dict, row_idx: int, issues: list[ValidationIssue]) -> None:
    """XOR-encoded values must be decodable — catches corruption."""
    if row.get("encoding") != "xor":
        return
    column_id = row.get("column_id")
    values = row.get("values", [])
    if not values:
        return
    try:
        decode_encoded_strings([values[0]])
    except Exception as exc:  # noqa: BLE001
        issues.append(
            ValidationIssue(
                row_idx=row_idx,
                column_id=column_id,
                field="values",
                level="error",
                message=f"first XOR-encoded value failed to decode: {exc}",
            )
        )


def _check_prevalence_keys(row: dict, row_idx: int, issues: list[ValidationIssue]) -> None:
    """Prevalence keys must be a subset of true_labels."""
    column_id = row.get("column_id")
    labels = set(row.get("true_labels", []))
    prevalence = row.get("true_labels_prevalence", {})
    if not isinstance(prevalence, dict):
        return
    for key, val in prevalence.items():
        if key not in labels:
            issues.append(
                ValidationIssue(
                    row_idx=row_idx,
                    column_id=column_id,
                    field="true_labels_prevalence",
                    level="warning",
                    message=f"prevalence key {key!r} not in true_labels",
                )
            )
        if not isinstance(val, (int, float)) or not (0.0 <= val <= 1.0):
            issues.append(
                ValidationIssue(
                    row_idx=row_idx,
                    column_id=column_id,
                    field="true_labels_prevalence",
                    level="error",
                    message=f"prevalence for {key!r} must be float in [0,1], got {val!r}",
                )
            )


def validate_row(row: Any, row_idx: int) -> list[ValidationIssue]:
    """Run every structural check against one row."""
    issues: list[ValidationIssue] = []
    if not isinstance(row, dict):
        issues.append(
            ValidationIssue(
                row_idx=row_idx,
                column_id=None,
                field="<row>",
                level="error",
                message=f"row is not a dict (got {type(row).__name__})",
            )
        )
        return issues

    _check_field_types(row, row_idx, issues)
    # Only run semantic checks if the row has at least the required basic structure.
    if any(i.level == "error" and i.field in ("column_id", "values") for i in issues):
        return issues

    _check_enum_fields(row, row_idx, issues)
    _check_labels_known(row, row_idx, issues)
    _check_family_consistency(row, row_idx, issues)
    _check_prevalence_floor(row, row_idx, issues)
    _check_prevalence_keys(row, row_idx, issues)
    _check_xor_roundtrip(row, row_idx, issues)
    return issues


def validate_gold_set(rows: list[dict]) -> list[ValidationIssue]:
    """Run per-row validation + cross-row checks (column_id uniqueness)."""
    issues: list[ValidationIssue] = []
    for idx, row in enumerate(rows):
        issues.extend(validate_row(row, idx))

    # Cross-row: column_id uniqueness.
    column_ids = [r.get("column_id") for r in rows if isinstance(r, dict)]
    dupes = [cid for cid, count in Counter(column_ids).items() if count > 1]
    for cid in dupes:
        issues.append(
            ValidationIssue(
                row_idx=-1,
                column_id=cid,
                field="column_id",
                level="error",
                message=f"duplicate column_id across {Counter(column_ids)[cid]} rows",
            )
        )

    return issues


def load_gold_set(path: Path) -> list[dict]:
    import json as _json

    with path.open() as f:
        return [_json.loads(line) for line in f if line.strip()]


__all__ = [
    "REQUIRED_FIELDS",
    "VALID_ENCODINGS",
    "VALID_REVIEW_STATUS",
    "VALID_SHAPES",
    "ValidationIssue",
    "load_gold_set",
    "validate_gold_set",
    "validate_row",
]
