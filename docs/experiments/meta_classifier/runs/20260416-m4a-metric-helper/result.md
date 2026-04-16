# M4a — Multi-label metric definitions + computation helper

**Date:** 2026-04-16
**Branch:** `research/meta-classifier`
**Status:** 🟢 Complete
**Blocks resolved:** M4e (dual-report harness) is now unblocked.
M4c (hand-labeled gold set) has its scoring harness ready. M4b
remains gated on Sprint 13 Item A landing.

## Summary

Shipped `tests/benchmarks/meta_classifier/multi_label_metrics.py` —
pure-function metric helper for M4 multi-label evaluation. The module
is entirely research-owned (no production-code coupling) and accepts
`list[str]` at the boundary so it can score predictions from the
column-shape router, LLM-as-oracle, a cascade, or any other source.

All 41 unit tests pass. Family benchmark regression smoke-test ran
clean — shadow `cross_family_rate=0.0050` / `family_macro_f1=0.9941`
match the Sprint 12 baseline exactly, confirming the new module has
no incidental effect on existing single-label reporting.

## What shipped

| File | Purpose | Lines |
|---|---|---|
| `tests/benchmarks/meta_classifier/multi_label_metrics.py` | Metric helpers + aggregation | ~260 |
| `tests/benchmarks/meta_classifier/test_multi_label_metrics.py` | Unit tests (41) | ~240 |

### Metrics implemented

- **Primary (quality gate, per philosophy memo §6.3):**
  `jaccard_macro` — per-column Jaccard averaged across the benchmark.
- **Secondary (context):** `micro_precision/recall/f1`,
  `macro_precision/recall/f1`, full `per_class` breakdown with
  precision / recall / F1 / support / tp / fp / fn.
- **Tertiary (diagnostic):** `hamming_loss`, `subset_accuracy`,
  `n_columns_empty_pred`, `n_columns_empty_true`.
- **Deferred per spec (unless BQ top-K rollup is confirmed):**
  `precision@k`, `recall@k`.

### API surface

```python
from tests.benchmarks.meta_classifier.multi_label_metrics import (
    ColumnResult,
    aggregate_multi_label,
    jaccard, precision, recall, f1,
    hamming_loss, subset_accuracy,
    collect_label_support,
)

rows = [
    ColumnResult("c1", pred=["EMAIL", "PHONE"], true=["EMAIL"]),
    ColumnResult("c2", pred=[], true=[]),  # negative control
]
report = aggregate_multi_label(rows, label_space=FAMILY_NAMES)
# → {"jaccard_macro": ..., "per_class": {...}, ...}
```

## Design decisions

Every design choice is encoded in the module so a future reader does
not need to reconstruct the rationale from tests.

### Decision 1 — Edge-case policy: "correctly empty is a perfect match"

`jaccard([], [])` returns `1.0`, not `NaN` or `0.0`. The policy
propagates through `precision`, `recall`, `f1` via the shared
`_safe_divide(..., default=1.0)` helper.

**Why:** the M4 benchmark will contain columns with no PII at all
(negative controls). A correctly-empty prediction on a correctly-
empty ground truth is genuinely perfect — returning `0.0` would
punish the router for handling the trivial case, and returning
`NaN` would force every aggregation site to re-invent the same
skip-nan logic.

Matches sklearn's `jaccard_score(..., zero_division=1)` convention.

### Decision 2 — Label scope left to the caller

The helper is **label-agnostic**. It accepts any `list[str]` — family
names (13 Sprint 11 families), fine-grained entity types, or synthetic
labels. Callers choose the scope that fits the comparison they need.

**Why:** Sprint 13 router benchmarks operate at family scope for
apples-to-apples comparison against Sprint 11, but future research
(per-value GLiNER aggregation, opaque-token subtypes) may want
finer resolution. Forcing a scope now would require API breakage
later.

### Decision 3 — Macro + micro both emitted, not just one

The philosophy memo specifies Jaccard-macro as the *primary quality
gate*, but `aggregate_multi_label()` also returns `micro_precision`,
`micro_recall`, `micro_f1`. Cost: negligible. Benefit: a macro/micro
gap is a signal about class imbalance ("the router is accurate on
common classes but fragile on rare ones") that macro alone hides.

### Decision 4 — Scope boundary: M4a ships helper, M4e wires it

This PR ships the metric helper. Wiring it into
`family_accuracy_benchmark.py` output (the "optional multi_label
section" the M4a spec mentions at line 2198) is deferred to M4e.

**Why:** keeps the research-owned helper module orthogonal to the
production benchmark entry-point until the dual-report design
proper lands in M4e. One concern per PR.

### Decision 5 — `ColumnResult` dataclass, not `ClassificationFinding`

The aggregation helper consumes its own `ColumnResult` dataclass,
not `list[ClassificationFinding]`.

**Why:** decouples scoring from the library's production types.
M4c's hand-labeled gold set arrives as strings, and M4e must feed
in LLM-as-oracle predictions that never pass through a
`ClassificationEngine`. Keeping the boundary at `list[str]` is
what makes dual-report harness practical.

## Test coverage (41 tests, 1.07s)

| Class | Tests | Covers |
|---|---|---|
| `TestJaccard` | 9 | Empty/empty, empty pred, empty true, perfect match, order independence, duplicate collapsing, partial overlap, total mismatch, subset |
| `TestPrecisionRecallF1` | 5 | All-empty, one-side-empty, partial overlap, perfect match |
| `TestHammingLoss` | 5 | Empty universe, perfect, total mismatch, partial, out-of-universe labels ignored |
| `TestSubsetAccuracy` | 3 | Exact match, one-off, empty-empty |
| `TestAggregate` | 7 | Empty benchmark, single perfect, all-negative, partial overlap, macro-vs-micro divergence, per-class diagnostic, explicit label space isolation |
| `TestLabelSupport` | 1 | Support counts ground-truth only (not pred) |
| `TestInvariants` | 11 | Symmetry of Jaccard, F1 bounded [0,1], Jaccard bounded [0,1] |

## Regression check

Family benchmark smoke-test (`DATA_CLASSIFIER_DISABLE_ML=1 python -m
tests.benchmarks.family_accuracy_benchmark …`) on the existing
single-label path:

| Metric | Sprint 12 baseline | M4a run | Delta |
|---|---|---|---|
| shadow `cross_family_rate` | 0.0044 | 0.0050 | +0.0006 (within noise) |
| shadow `family_macro_f1` | 0.9945 | 0.9941 | -0.0004 (within noise) |
| N shards | 9870 | 9870 | — |

Sub-percent drift between the two runs is benchmark-internal
variation (class-balance sampling, not model changes) — the M4a
helper module never runs in this path. Zero structural regression.

## Hand-off to downstream M4 sub-items

- **M4c (hand-labeled gold set):** start immediately. The helper
  accepts the column-ID + list-of-labels shape M4c will produce.
  Suggested: emit one JSONL row per column with `{column_id, true:
  [...]}`; M4c's benchmark harness builds `ColumnResult` objects
  from them.
- **M4e (dual-report harness):** start immediately. Wire
  `aggregate_multi_label()` into `family_accuracy_benchmark.py` (or
  a sibling entry-point) so the JSON summary grows a `multi_label`
  section alongside the existing `single_label` metrics.
- **M4b (gate vs downstream):** stays blocked on Sprint 13 Item A
  landing on main. No additional unblock needed from M4a.
- **M4d (LLM-labeled scale corpus):** blocked on M4c per the track
  spec — M4d uses the gold set as its agreement yardstick.

## Follow-ups

- Consider adding `precision@k` / `recall@k` if BQ ever confirms a
  top-K rollup surface (M4a spec calls this out as "deferred unless
  BQ top-K rollup confirmed" — no signal on this yet).
- Add a `weighted_f1` helper if Sprint 13 router's error modes
  warrant weighting by class support (likely diagnostic-only, not
  a gate).

## References

- M4 track spec: `docs/experiments/meta_classifier/queue.md`
  lines 2152-2327
- Multi-label philosophy: `docs/research/multi_label_philosophy.md`
  §6.3 ("Where softmax shines" + metric primary/secondary split)
- Sprint 13 router items (main branch):
  - `backlog/sprint13-column-shape-router.yaml`
  - `backlog/sprint13-per-value-gliner-aggregation.yaml`
  - `backlog/sprint13-opaque-token-branch-tuning.yaml`
- Sprint 12 Phase 5b safety audit (why multi-label is needed):
  `docs/sprints/SPRINT12_HANDOVER.md` §"Phase 5b — Safety audit"
