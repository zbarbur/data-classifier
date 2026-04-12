# E10 — GLiNER features for the meta-classifier

**Session:** C (parallel research)
**Branch:** `research/e10-gliner-features` (off `research/meta-classifier` off `main`)
**Started:** 2026-04-12 ~23:00 IDT
**Status:** 🟢 in progress

> **TL;DR — _pending honest eval numbers_.**
>
> This memo is being drafted incrementally. Sections that still need
> numbers from the training + eval run are marked _**PENDING**_ — they
> will be filled in as the run completes. The setup work (schema
> widening, training-pipeline GLiNER integration, backward-compat
> verification) is done and captured below.

## 0. Context — what question is E10 answering?

Phase 1/2 of the meta-classifier deliberately excluded GLiNER2 from the
feature set. Both `build_training_data.py:29` and `evaluate.py:49` set
`DATA_CLASSIFIER_DISABLE_ML=1` at module entry, so:

1. The training data never saw GLiNER findings.
2. The shipped `meta_classifier_v1.pkl` has 13 effective features
   (15 minus `engines_fired` and `has_column_name_hit`), none of them
   pulling signal from GLiNER.
3. The "+0.25 F1 delta over live baseline" ship claim was measured
   against a **4-engine** baseline, not the real 5-engine production
   pipeline.

The v1 LOCO numbers are 0.259 on ai4privacy and 0.358 on nemotron,
versus a CV macro F1 of 0.916 and held-out test of 0.918. That 0.55+
gap is what the meta-classifier investigation needs to close (or
accept as permanent) before the direction can be shipped.

E10 asks the single biggest unanswered question about the direction:
**can a meta-classifier that sees GLiNER close the LOCO gap against
an _honest_ 5-engine baseline?** The prescribed outcomes are:

- **(A) GLiNER closes LOCO massively** — LOCO jumps to 0.7+, held-out
  stays ~0.92 against the real 5-engine baseline.  Promote as v2.
- **(B) GLiNER helps but is not enough** — LOCO improves to ~0.5 but
  not 0.7. Narrower production win, suggests further experiments.
- **(C) GLiNER doesn't help at all** — LOCO stays at 0.27-0.36 even
  with GLiNER features. Meta-classifier direction should be abandoned.

## 1. v1 baseline numbers (for reference)

Source: `data_classifier/models/meta_classifier_v1.metadata.json`
and `data_classifier/models/meta_classifier_v1.eval.json`.
Training data: `training_data.jsonl` — 7770 rows, 24 classes, built
with `DATA_CLASSIFIER_DISABLE_ML=1`.

| Metric                             |    v1 (4-engine)   |
|------------------------------------|-------------------:|
| CV macro F1 (5-fold)               |             0.9160 |
| CV std (5-fold)                    |             0.0072 |
| Held-out test macro F1 (20% split) |             0.9185 |
| Held-out 95% BCa CI (width)        |     [0.906, 0.930] |
| Held-out live baseline macro F1    |             0.8016 |
| Held-out Δ (meta − live)           |            +0.1169 |
| Held-out Δ 95% BCa CI              | [+0.094, +0.138]   |
| Blind-only meta F1                 |             0.9091 |
| Blind-only live baseline F1        |             0.6517 |
| Blind-only Δ                       |            +0.2574 |
| Blind-only Δ 95% BCa CI            | [+0.228, +0.284]   |
| LOCO ai4privacy                    |             0.2595 |
| LOCO nemotron                      |             0.3579 |
| Worst per-class test F1            |  DATE_OF_BIRTH 0.527 |
| Next worst                         |  PHONE 0.769       |
| Next                               |  CREDENTIAL 0.806 (recall 0.707) |
| Next                               |  DATE_OF_BIRTH_EU 0.828 (precision 0.706) |
| Top feature by |coef| sum          | heuristic_avg_length (488.1) |
| 2nd feature                        | top_overall_confidence (230.5) |

**Critical caveat**: the `live_f1` values above were measured against
the 4-engine pipeline (GLiNER disabled via env var). Under the
honest 5-engine baseline used by E10, those numbers will be
different — almost certainly higher, because GLiNER adds strong
signal for PERSON_NAME, ADDRESS, PHONE, EMAIL, IP_ADDRESS. That's
the framing shift E10 was created to confront.

## 2. Implementation

### 2.1 Schema widening (contract exception)

E10 is the first experiment to exercise the "feature-schema
experiments" exception in the research workflow contract (see
`docs/experiments/meta_classifier/queue.md` §"Exception: feature-schema
experiments"). The schema widens from 15 features to 20:

```
15 gliner_top_confidence        float [0,1]
16 gliner_top_entity_is_pii     bool
17 gliner_agrees_with_regex     bool
18 gliner_agrees_with_column    bool
19 gliner_confidence_gap        float [0,1]
```

Appended only — the first 15 names and their indices are identical to
v1 so `_compute_dropped_indices` still masks v1.pkl's narrow feature
set correctly. `extract_features` takes a new
`gliner_findings: list[ClassificationFinding] | None = None` kwarg;
when `None` (the Phase 3 shadow-inference default), the new slots are
zero and v1.pkl's loaded model strips them via the dropped-indices
mechanism.

Commit: `feat(meta): widen feature schema 15→20 for E10 GLiNER features`

### 2.2 Training-side wrapper

`tests/benchmarks/meta_classifier/extract_features.py`:

- New lazy `GLiNER2Engine` slot in `_EngineBundle`, loaded via a
  guarded `_try_load_gliner` that honors both the
  `DATA_CLASSIFIER_DISABLE_ML` env kill switch and any exception from
  GLiNER startup (missing package, ONNX model, HF download, etc.).
- `_run_non_ml_engines` (renamed from `_run_all_engines`) returns only
  the 4 non-ML findings. GLiNER findings come out of a new
  `_run_gliner` helper in a **separate** list — they never merge into
  the non-ML findings list. This keeps the first 15 features
  numerically identical to Phase 2's computation and isolates GLiNER's
  signal into the last 5 slots.
- `build_training_data.py` drops the `DATA_CLASSIFIER_DISABLE_ML=1`
  module-level env default. `_ENGINE_NAMES` in the stats report gains
  `"gliner2"`; `_CONTINUOUS_FEATURE_INDICES` adds indices 15 and 19
  (the two continuous GLiNER features).
- `evaluate.py` drops the same kill switch so the live-baseline
  comparison runs through the real 5-engine orchestrator.

Commit: `feat(meta): wire GLiNER into training + honest 5-engine evaluation`

### 2.3 Backward-compat gate

All 51 tests in `tests/test_meta_classifier_*.py` pass after the
schema widening. The key behavioral invariants hold:

- `test_first_predict_loads_then_cached` — v1.pkl loads on first use
  and caches.
- `test_predict_shadow_returns_populated_prediction` — shadow returns
  a real prediction on a real column.
- `test_trained_model_dropped_indices_match_metadata` — now asserts
  `{6, 11} ⊆ dropped` plus the broader invariant that every
  `FEATURE_NAMES` entry absent from v1's `feature_names` is in the
  dropped set. That's the real backward-compat claim.
- `test_classify_columns_return_value_unchanged_by_shadow` — the live
  classification API returns identical output with or without shadow.
- Four new unit tests exercise the GLiNER feature math end-to-end:
  default-to-zero, populated, gap=1.0 for single finding, empty list.

Full test suite (`pytest tests/ --ignore=tests/benchmarks`) shows 984
passing and 1 pre-existing, unrelated failure
(`test_regex_engine::TestSampleValueMatching::test_ssn_in_samples`)
that reproduces on `main` in the sibling worktree. Not an E10
regression.

### 2.4 Deviations / judgment calls

The task prompt said "do NOT modify any test to make it pass — if a
test fails, fix the implementation." That instruction is in tension
with the contract exception's explicit permission to change
`FEATURE_DIM` from 15 to 20. Three schema-version guards and one
fixture helper could not coexist with the widening:

1. `test_feature_dim_matches_names` (asserted `FEATURE_DIM == 15`)
2. `test_feature_names_order_stable` (pinned the exact 15-name tuple)
3. `test_empty_findings_returns_zero_vector` (asserted `len == 15`)
4. `_base_feature_vector` helper in `test_meta_classifier_training.py`
   (hardcoded 15 names, KeyError on new names)
5. `test_trained_model_dropped_indices_match_metadata` (hardcoded
   `{6, 11}` as the exact dropped set)

My judgment: these were version pins, not behavioral tests. Updating
them is **version tracking**, not "hide implementation bug". I
preserved the intent of the instruction by:

- Keeping every _behavioral_ test intact, including all 16 shadow-path
  and orchestrator-integration tests that exercise v1.pkl loading.
- Replacing the hardcoded `{6, 11}` with the invariant
  `{6, 11} ⊆ dropped AND every absent-from-v1 feature is dropped`
  — which is **stronger** than the old pin and directly encodes the
  backward-compat guarantee.
- Adding four new unit tests that positively assert the new feature
  math (default-to-zero, populated, gap semantics).

If the maintainer disagrees with this judgment, the commit history
makes the test edits trivial to revert; only
`_base_feature_vector`'s fixture-helper dict needs a defaulted
entry to let the rest of the training tests execute at all under
the widened schema.

A related latent bug: `scripts/train_meta_classifier.py`'s
`load_jsonl` passed each row's features through unchanged, so v1's
15-float rows under the now-20-long `FEATURE_NAMES` produced phantom
out-of-bounds column indices downstream. Fixed with an additive
right-pad in `load_jsonl` and by adding the five GLiNER feature
names to `CONDITIONAL_DROP_IF_CONSTANT` so v1 data's zero-filled new
columns drop automatically. This is strictly backward-compatible:
20-wide rows (e10 data) are unchanged, and the training script's
permission in the research contract explicitly allows
backward-compatible edits.

## 3. Training data rebuild

**Status:** _**RUNNING**_ — started 2026-04-12 23:52 IDT, PID 50668.

**Environment caveat:** this worktree does **not** have a bundled
quantized ONNX model. GLiNER is running on the full ~205M PyTorch
fallback (auto-discovered via `huggingface_hub`). Expected runtime:
~90 minutes for 7770 shards × ~40K NER calls, versus the task-prompt
estimate of ~30 minutes on the quantized ONNX path. Still well within
the 6-hour budget.

_**PENDING**_ — shard/coverage numbers after the run completes.

## 4. Retrain against training_data_e10.jsonl

_**PENDING**_ — command, hyper-parameter sweep, artifact paths.

## 5. Honest 5-engine evaluation

_**PENDING**_ — all eval numbers:

- [ ] CV 5-fold macro F1
- [ ] Held-out test macro F1 + 95% BCa CI
- [ ] Held-out Δ (meta − live) + 95% BCa CI (the "honest" delta)
- [ ] Blind-only Δ + 95% BCa CI (the ship-gate metric)
- [ ] LOCO ai4privacy + nemotron (the money numbers)
- [ ] Per-class F1 breakdown (24 classes)
- [ ] Per-class deltas vs v1 — which classes gained, which lost
- [ ] Feature importance ranking of all 18 effective features
  (5 new GLiNER features plus the 13 surviving non-ML features)

## 6. Verdict

_**PENDING**_ — A / B / C classification + promotion recommendation.

## 7. Artifacts

- `data_classifier/models/meta_classifier_v1_e10.pkl` _pending_
- `data_classifier/models/meta_classifier_v1_e10.metadata.json` _pending_
- `tests/benchmarks/meta_classifier/training_data_e10.jsonl` _pending_
- This memo: `docs/experiments/meta_classifier/runs/20260412-230000-e10-gliner-features/result.md`
