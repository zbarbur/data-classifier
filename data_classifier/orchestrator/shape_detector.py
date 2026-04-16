"""Column-shape router — routes each column to one of three handlers.

The router inspects the post-merge findings and column-level statistics to
decide which downstream handler a column should route to:

  structured_single       — one entity per column (emails, SSNs, phone numbers).
                            Current v5 shadow + 7-pass merge apply.
  free_text_heterogeneous — log lines, chat, JSON events. Multiple
                            entities per column. Item B handles.
  opaque_tokens           — base64 payloads, JWTs, hashes. No dictionary
                            words. Item C handles.

IMPORTANT: ``detect_column_shape`` accepts the **post-merge** findings list
produced by the orchestrator's authority resolution + suppression passes.
Passing the raw pre-merge output inflates ``n_cascade_entities`` by engine
collisions on homogeneous columns (e.g., ABA_ROUTING columns trigger both
column_name → ABA_ROUTING and regex → SSN+ABA_ROUTING pre-merge; authority
resolution drops SSN, leaving 1 entity type post-merge). The
``structured_single`` route's ``n_cascade <= 1`` guard requires the
post-merge count.

Routing is deterministic and auditable: two content signals
(``avg_len_normalized``, ``dictionary_word_ratio``) plus the cascade's
entity-type count, with a narrow column-name tiebreaker band for ambiguous
middle-ground cases. ``cardinality_ratio`` is carried for event emission
only and is not consulted in the routing decision.
Thresholds come from the Sprint 12 safety audit §6 evidence
(see ``docs/research/meta_classifier/sprint12_safety_audit.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from data_classifier.core.types import ClassificationFinding, ColumnInput

if TYPE_CHECKING:
    from data_classifier.engines.column_name_engine import ColumnNameEngine
from data_classifier.engines.heuristic_engine import (
    compute_avg_length_normalized,
    compute_cardinality_ratio,
    compute_dictionary_word_ratio,
)

Shape = Literal["structured_single", "free_text_heterogeneous", "opaque_tokens"]

# Thresholds from the Sprint 12 safety audit §6:
#   Homogeneous single-entity columns: avg_len 0.11-0.16
#   Log-shaped columns: avg_len 0.51-0.90
#   Base64 tokens: dict_word_ratio ~0
_AVG_LEN_STRUCTURED_MAX: float = 0.3
_DICT_WORD_HETERO_MIN: float = 0.1

# Sprint 13 scoping Q1 decision (2026-04-16): column-name tiebreaker
# middle-band. Only consulted when content signals land in this
# ambiguous zone. Content signals remain authoritative outside the band.
_TIEBREAKER_AVG_LEN_MIN: float = 0.3
_TIEBREAKER_AVG_LEN_MAX: float = 0.45
_TIEBREAKER_DICT_RATIO_MIN: float = 0.05


@dataclass(frozen=True)
class ShapeDetection:
    """Result of ``detect_column_shape``. Carries the decision and the
    signals that drove it so a ``ColumnShapeEvent`` can be built
    without recomputing. Frozen so instances are safe to cache and pass
    across coroutine boundaries without defensive copying.
    """

    shape: Shape
    avg_len_normalized: float
    dict_word_ratio: float
    cardinality_ratio: float
    n_cascade_entities: int
    column_name_hint_applied: bool


def detect_column_shape(
    column: ColumnInput,
    findings: list[ClassificationFinding],
) -> ShapeDetection:
    """Pure column-shape detector. Returns the routing decision and signals.

    ``findings`` MUST be the post-merge, deduped list of findings produced
    by the orchestrator's authority resolution + suppression passes. Passing
    the raw pre-merge output would inflate ``n_cascade_entities`` by engine
    collisions on homogeneous columns (e.g., ABA_ROUTING columns trigger
    both column_name → ABA_ROUTING and regex → SSN before merge — 2 entity
    types pre-merge, 1 post-merge). The structured_single route's
    ``n_cascade <= 1`` guard requires the post-merge count.

    Routing rules (Sprint 12 safety audit §6):

      if avg_len_norm < 0.3 AND n_cascade_entities <= 1:
          structured_single
      elif dict_word_ratio >= 0.1:
          free_text_heterogeneous
      else:
          opaque_tokens

    With the column-name tiebreaker (Sprint 13 scoping Q1): when content
    signals land in the ambiguous middle band, consult column_name for
    a low-weight hint. Content remains authoritative outside the band.
    """
    values = column.sample_values
    avg_len = compute_avg_length_normalized(values)
    dict_ratio = compute_dictionary_word_ratio(values)
    cardinality = compute_cardinality_ratio(values)

    distinct_entities = {f.entity_type for f in findings}
    n_cascade = len(distinct_entities)

    # Content-signal routing (authoritative).
    if avg_len < _AVG_LEN_STRUCTURED_MAX and n_cascade <= 1:
        shape: Shape = "structured_single"
    elif dict_ratio >= _DICT_WORD_HETERO_MIN:
        shape = "free_text_heterogeneous"
    else:
        shape = "opaque_tokens"

    hint_applied = False
    # Column-name tiebreaker (Sprint 13 scoping Q1): only when content
    # signal is ambiguous (middle band). Content remains authoritative
    # outside this narrow zone.
    # Middle band EXCLUDES the content-authoritative heterogeneous zone
    # (dict_ratio >= _DICT_WORD_HETERO_MIN is confidently heterogeneous per
    # the content router; the tiebreaker must not override a content decision
    # that was already clear). The tiebreaker only fires where content is
    # genuinely ambiguous: long-ish values with few dictionary words.
    in_middle_band = (
        _TIEBREAKER_AVG_LEN_MIN <= avg_len <= _TIEBREAKER_AVG_LEN_MAX
        and _TIEBREAKER_DICT_RATIO_MIN <= dict_ratio < _DICT_WORD_HETERO_MIN
    )
    if in_middle_band:
        hint = _lookup_column_name_hint(column.column_name)
        if hint == "heterogeneous":
            shape = "free_text_heterogeneous"
            hint_applied = True
        elif hint == "structured" and n_cascade <= 1:
            # Mirror the content router's structured_single contract — requires
            # BOTH content-ambiguous AND <= 1 cascade entity. A column with
            # multiple cascade entities is not structured-single regardless of
            # what the column name hints at.
            shape = "structured_single"
            hint_applied = True

    return ShapeDetection(
        shape=shape,
        avg_len_normalized=avg_len,
        dict_word_ratio=dict_ratio,
        cardinality_ratio=cardinality,
        n_cascade_entities=n_cascade,
        column_name_hint_applied=hint_applied,
    )


# Lazy singleton: column-name engine takes ~5ms to initialize. Creating
# it inside detect_column_shape would add that cost to every call; the
# module-level lazy init amortizes it across the first call.
_COLUMN_NAME_ENGINE: "ColumnNameEngine | None" = None


def _lookup_column_name_hint(column_name: str) -> str | None:
    """Return ``"structured"``, ``"heterogeneous"``, or ``None``.

    Lazy-loads the ColumnNameEngine on first use.
    """
    global _COLUMN_NAME_ENGINE
    if _COLUMN_NAME_ENGINE is None:
        # Local import to avoid a module-load-time circular dependency:
        # engines/column_name_engine.py imports from core.types, and
        # this module imports from engines.heuristic_engine. Importing
        # ColumnNameEngine lazily here keeps the orchestrator layer's
        # import graph clean.
        from data_classifier.engines.column_name_engine import ColumnNameEngine

        _COLUMN_NAME_ENGINE = ColumnNameEngine()
    return _COLUMN_NAME_ENGINE.get_variant_category(column_name)
