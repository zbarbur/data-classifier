# M4e — Dual-report harness (Sprint 11 single-label + Sprint 13+ multi-label)

**Date:** 2026-04-16
**Branch:** `research/meta-classifier`
**Status:** 🟢 Complete
**Unblocks:** Sprint 13 router work — router output now has a
canonical multi-label quality gate to land against.

## Summary

Wired `aggregate_multi_label()` (from M4a) into the canonical family
benchmark (`tests/benchmarks/family_accuracy_benchmark.py`). Every
run now emits **three peer tiers** per prediction path:

- `family` (Sprint 11 — cross-family rate + macro F1 at 13 families)
- `subtype` (Sprint 11 — per-entity-type accuracy + F1 at 25 subtypes)
- `multi_label` (**new** — M4a metrics at both family and subtype scopes)

The single-label tiers are untouched, so every downstream consumer
(CLAUDE.md Sprint Completion Gate, `--compare-to` baseline diffs, CI
smoke scripts reading `shadow.overall.family.cross_family_rate`)
continues to work without modification. The multi-label tier adds
`jaccard_macro`, `micro_f1`, `macro_f1`, `per_class`, `hamming_loss`,
`subset_accuracy`, and `n_columns_empty_pred` — the full set M4a
ships — at both granularities per path (live + shadow) per split
(overall + named + blind).

## What shipped

| File | Change |
|---|---|
| `tests/benchmarks/family_accuracy_benchmark.py` | Added `_project_to_multi_label_rows()` + `_compute_multi_label_metrics()`; extended `_build_tiered()` to include new `multi_label` section |
| `tests/benchmarks/test_multi_label_metrics_benchmark_parity.py` | 12 regression tests (summary shape + K=1 invariants + cross-tier agreement + label-space pinning) |

## Zero regression verified

Full-run benchmark (9 870 shards, 41 s):

| Metric | Sprint 12 baseline | M4e run | Delta |
|---|---|---|---|
| `shadow.cross_family_rate` | 0.0044 | 0.0046 | +0.0002 (within noise) |
| `shadow.family_macro_f1` | 0.9945 | 0.9943 | -0.0002 (within noise) |
| `live.cross_family_rate` | ~0.16 | 0.1627 | — |
| `live.family_macro_f1` | ~0.83 | 0.8329 | — |
| `n_shards` | 9 870 | 9 870 | — |

The sub-percent drift is benchmark-internal variation (class-balance
sampling, not model changes — identical to the M4a smoke run). Zero
structural regression.

## New numbers from the dual-report view

Full-run shadow path:

| Scope | Jaccard macro | Micro F1 | Macro F1 | Subset-acc | Hamming |
|---|---|---|---|---|---|
| Family | 0.9954 | 0.9954 | 0.9943 | 0.9954 | 0.0007 |
| Subtype | 0.9951 | 0.9951 | 0.9960 | 0.9951 | 0.0003 |

For today's K=1 projection these are a re-statement of Sprint 11's
existing accuracy/F1 numbers through the multi-label helper — exactly
what the K=1 regression tests assert. They become *diagnostically*
interesting the moment Sprint 13's column-shape router lands and
starts emitting `list[Finding]` per column.

## Design decisions

### Decision 1 — Non-invasive schema extension

The M4e spec reads:

> Benchmark JSON top-level schema carries `single_label_metrics`,
> `multi_label_metrics`, ...

Literal interpretation would require a schema break: restructure
every `summary["live"]["overall"]["family"]` path consumer to read
`summary["live"]["overall"]["single_label_metrics"]["family"]`
instead. That would break:

- CLAUDE.md's Sprint Completion Gate snippet
  (`shadow.overall.family.cross_family_rate`)
- `_compare_to()` / `--compare-to` with any committed baseline
  (e.g. `docs/research/meta_classifier/sprint12_family_benchmark.json`)
- CI smoke scripts anywhere

Instead, chose **additive extension**: the `multi_label` section sits
alongside `family` and `subtype` as a peer tier inside the existing
structure. No consumer is forced to change. Anyone who cares about
multi-label reads the new path; nobody else sees a difference.

This matches the spec's intent ("alongside, not instead of") while
keeping Sprint 11 continuity work-free.

### Decision 2 — K=1 projection, both directions

Per the spec's projection logic:

- **Current (Sprint 11 → multi-label):** single-label prediction
  projected to ``[class]`` if non-empty, ``[]`` otherwise. Ground
  truth projected the same way. The helper scores each column as a
  set-of-length-1.
- **Future (Sprint 13 router → single-label):** when `list[Finding]`
  lands, `findings[0]` (top-confidence) is still what gets compared
  to the Sprint 11 `family_macro_f1`. The router's multi-label gains
  show up *only* in the multi-label tier — which is exactly the
  point of dual-report.

Today the projection is the identity at K=1; Sprint 13 is where the
two tiers start telling different stories.

### Decision 3 — Pin label space to the canonical taxonomy

`aggregate_multi_label()` accepts an optional `label_space`. Passing
None would let the universe drift with what labels happen to appear
in the benchmark run, making Hamming loss non-comparable across
sprints. M4e wires in:

- Family scope: `label_space=FAMILIES` (13 canonical families)
- Subtype scope: `label_space=sorted(ENTITY_TYPE_TO_FAMILY.keys())`
  (25 canonical entity types)

This pins the denominator of Hamming loss to the taxonomy, not to
observed labels.

### Decision 4 — Regression-test-as-documentation

The 12-test regression suite doubles as executable documentation of
the invariant structure:

- `TestK1Invariants` carries two distinct claims in two tests:
  - "subset_acc == jaccard_macro" (always holds at K=1)
  - "subset_acc == micro_f1" (holds only when no empty preds)
- `test_shadow_full_k1_convergence` additionally asserts
  `n_columns_empty_pred == 0` as the reason the stricter claim
  holds on the shadow path
- `test_live_path_has_empty_preds` asserts the *opposite* on the
  live path — documenting that the cascade's intentional silence
  is by design, so a future refactor can't hide it

If the underlying structure shifts (say, Sprint 13 makes the cascade
always-fire and the live path loses its empty preds), the second
test fails loudly instead of silently absorbing the change.

## Honest bug caught during writing

First draft of `test_live_path_invariants_too` asserted the full
three-way `subset_accuracy == jaccard_macro == micro_f1` on the live
path. It failed at the `== micro_f1` step (0.688 vs 0.740). The
failure was informative: empty preds on the live cascade (≈5% of
shards) contribute to global `fn` without a symmetric `fp`, which
skews global P/R (and hence micro_f1) while leaving per-column
Jaccard and subset_accuracy untouched.

Test split into two orthogonal claims (see Decision 4). The looser
invariant is now asserted on both paths; the stricter invariant is
asserted only where its precondition (no empty preds) holds.

## Test count

| Suite | Tests | Status |
|---|---|---|
| `test_multi_label_metrics.py` (M4a) | 41 | ✓ |
| `test_gold_set_schema.py` (M4c) | 22 | ✓ |
| `test_multi_label_metrics_benchmark_parity.py` (M4e) | 12 | ✓ |
| **Total M4 track** | **75** | **✓ 75 passed** |

Ruff clean (check + format) across all modified files.

## Hand-off to downstream M4 sub-items

- **M4d (LLM-labeled scale corpus, ~1 week):** blocked on M4c gold
  set reaching ≥80% human-reviewed. M4e adds no new blocker.
- **M4b (gate vs downstream harness, ~3-4 days):** blocked on
  Sprint 13 Item A landing on main. When that lands, M4b wires the
  router's `list[Finding]` output into the *same* `_build_tiered()`
  path — the multi-label section will then carry router gains
  without further harness changes.

## Follow-ups

- Sprint 13 router will require a new per-shard field like
  `predicted_findings: list[str]` that the router populates with
  the full multi-label output. Today's `predicted` stays as the
  single-label projection. `_project_to_multi_label_rows()` will
  branch on whether that field is present.
- `_print_report()` currently displays only the single-label tiers
  at the headline level. A future M4b work item may add a
  multi-label headline block (optional — the JSON is authoritative,
  the printer is human-convenience).
- Consider adding a CLAUDE.md Sprint Completion Gate reference for
  `shadow.overall.multi_label.family.jaccard_macro` alongside the
  existing `cross_family_rate` gate, once Sprint 13 delivers multi-
  label gains worth gating on.

## References

- M4e spec: `docs/experiments/meta_classifier/queue.md` lines 2317-2347
- M4a metric helper (prerequisite): `docs/experiments/meta_classifier/runs/20260416-m4a-metric-helper/result.md`
- M4c gold-set scaffolding (parallel track): `docs/experiments/meta_classifier/runs/20260416-m4c-gold-set/result.md`
- Multi-label philosophy (framing): `docs/research/multi_label_philosophy.md`
- CLAUDE.md Sprint Completion Gate: uses the single-label tiers unchanged
