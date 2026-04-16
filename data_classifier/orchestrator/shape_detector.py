"""Column-shape router — routes each column to one of three handlers.

The router inspects the engine-cascade output and column-level
statistics to decide which downstream handler a column should route
to:

  structured_single       — one entity per column (emails, SSNs, phone numbers).
                            Current v5 shadow + 7-pass merge apply.
  free_text_heterogeneous — log lines, chat, JSON events. Multiple
                            entities per column. Item B handles.
  opaque_tokens           — base64 payloads, JWTs, hashes. No dictionary
                            words. Item C handles.

Routing is deterministic and auditable: two content signals
(``avg_len_normalized``, ``dictionary_word_ratio``) plus the cascade's
entity-type count, with a narrow column-name tiebreaker band for ambiguous
middle-ground cases (the tiebreaker lands in Sprint 13 Item A Task 4 — this
module starts content-signal-only). ``cardinality_ratio`` is carried for
event emission only and is not consulted in the routing decision.
Thresholds come from the Sprint 12 safety audit §6 evidence
(see ``docs/research/meta_classifier/sprint12_safety_audit.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from data_classifier.core.types import ClassificationFinding, ColumnInput
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
    engine_findings: dict[str, list[ClassificationFinding]],
) -> ShapeDetection:
    """Pure column-shape detector. Returns the routing decision and signals.

    Routing rules (Sprint 12 safety audit §6):

      if avg_len_norm < 0.3 AND n_cascade_entities <= 1:
          structured_single
      elif dict_word_ratio >= 0.1:
          free_text_heterogeneous
      else:
          opaque_tokens

    The column-name tiebreaker (Sprint 13 scoping Q1) is added in Task 4.
    """
    values = column.sample_values
    avg_len = compute_avg_length_normalized(values)
    dict_ratio = compute_dictionary_word_ratio(values)
    cardinality = compute_cardinality_ratio(values)

    distinct_entities: set[str] = set()
    for findings in engine_findings.values():
        for f in findings:
            distinct_entities.add(f.entity_type)
    n_cascade = len(distinct_entities)

    if avg_len < _AVG_LEN_STRUCTURED_MAX and n_cascade <= 1:
        shape: Shape = "structured_single"
    elif dict_ratio >= _DICT_WORD_HETERO_MIN:
        shape = "free_text_heterogeneous"
    else:
        shape = "opaque_tokens"

    return ShapeDetection(
        shape=shape,
        avg_len_normalized=avg_len,
        dict_word_ratio=dict_ratio,
        cardinality_ratio=cardinality,
        n_cascade_entities=n_cascade,
        column_name_hint_applied=False,
    )
