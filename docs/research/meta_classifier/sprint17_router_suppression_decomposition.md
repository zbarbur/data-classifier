# Sprint 17 — Router Suppression Decomposition

> **Date:** 2026-04-30
> **Trigger:** Diagnostic spike during PR #22 (unified WASM detector merge) verification.
> **TL;DR:** The headline `shadow.overall.family.cross_family_rate` is **not** a system-level quality signal — it tracks router-suppression policy. The honest end-to-end miss rate on Sprint 17's corpus is **7.6%, not 37%**. The single biggest concrete recall hole is **CONTACT in free-text-heterogeneous shapes** (333 shards, 37% of all joint misses).

## 1. Why this investigation happened

PR #22 disclosed a LIVE family_macro_f1 regression of -0.018 vs the committed S17 baseline. Initial verification reproduced the regression and surfaced an apparent SHADOW regression of -0.13 family_macro_f1. A diagnostic spike (instead of jumping to "block the PR") found the regression was a **measurement artifact**:

- `tests/fixtures/.gitignore` excludes `/corpora` → 8 corpus sample files are not tracked in git.
- `_load_raw_records()` in `shard_builder.py:194` silently returns `[]` when a fixture is missing.
- The committed S17 baseline JSON was generated on a worktree where only `openpii_1m_sample.json` was cached → 4,620 shards instead of 11,820.
- PR #22 was measured on a worktree where all 8 corpora were cached → 11,820 shards.

Apples-to-apples comparison (both runs on the same 11,820-shard pool) shows PR #22 is **identical to sprint17/main to ±0.0002** across every metric. PR's own disclosed -0.018 was the same artifact mirrored on their side.

Follow-up filed: `fail-loud-benchmark-fixture-loader-replace-silent-empty-list-fallback`.

## 2. The honest S17 baseline

Replaced `docs/research/meta_classifier/sprint17_family_benchmark.json` with a full-corpus measurement. Headline numbers:

| Path | metric | old (incomplete) | true S17 |
|---|---|---:|---:|
| LIVE | cross_family_rate | 0.0790 | 0.1028 |
| LIVE | family_macro_f1 | 0.9733 | 0.9542 |
| SHADOW | cross_family_rate | 0.3136 | 0.3693 |
| SHADOW | family_macro_f1 | 0.8271 | 0.6933 |
| SHADOW | router_suppression_rate | 0.2671 | 0.3300 |

The "regression vs S16" disclosed in this baseline is **measurement honesty, not a code regression** — the same code on a more complete corpus produces these numbers. S16 baseline was almost certainly also generated on an incomplete corpus and is therefore non-comparable; re-baselining S16 is out of scope (sprint closed) but worth flagging in any historical comparison.

## 3. Router suppression decomposition

Routing is by **shape**, exactly as designed in the multi-label architecture spec (`docs/spec/11-multi-label-architecture.md`):

| shape | total | suppressed | rate |
|---|---:|---:|---:|
| `structured_single` | 7,919 | 0 | 0% |
| `opaque_tokens` | 2,211 | 2,211 | 100% |
| `free_text_heterogeneous` | 1,690 | 1,690 | 100% |

Suppression is binary per shape — the meta-classifier simply doesn't run on opaque or free-text-heterogeneous shapes (it was trained on structured single-label columns). LIVE path runs on all shapes.

### Per-family suppression verdict

For each family, what fraction of suppressed shards does LIVE catch (i.e., produce a correct family-level prediction)?

| Family | suppressed | LIVE catches | LIVE misses | Verdict |
|---|---:|---:|---:|---|
| CRYPTO | 600 | 100% | 0 | ✓ correctly routed away from meta-classifier |
| HEALTHCARE | 150 | 100% | 0 | ✓ |
| PAYMENT_CARD | 105 | 100% | 0 | ✓ |
| NETWORK | 54 | 100% | 0 | ✓ |
| CREDENTIAL | 1,321 | 87.5% | 165 | mostly OK |
| GOVERNMENT_ID | 402 | 81.3% | 75 | mostly OK |
| FINANCIAL | 380 | 80.0% | 76 | mostly OK |
| URL | 148 | 75.7% | 36 | mostly OK |
| **CONTACT** | **533** | **37.5%** | **333** | **REAL recall hole** |
| NEGATIVE | 208 | 0% | (208) | metric artifact — see §5 |

## 4. Joint miss rate

Defining a "joint miss" as a shard where no path's predicted_family ∈ ground_truth_families and ground_truth ≠ NEGATIVE:

| | shards | % of corpus |
|---|---:|---:|
| Meta-classifier emits | 7,919 | 67.0% |
| Suppressed → LIVE catches at family level | 3,008 | 25.4% |
| **Joint miss (suppressed AND LIVE missed)** | **893** | **7.6%** |

**The headline `shadow.cross_family_rate = 0.37` is 5× larger than the joint miss rate.** Most of the 37% is router suppression that LIVE compensates for via regex.

### Joint miss decomposition (893 shards)

By ground-truth family:
- CONTACT: 333 (37.3%)
- NEGATIVE: 208 (23.3%) — see §5
- CREDENTIAL: 165 (18.5%)
- FINANCIAL: 76 (8.5%)
- GOVERNMENT_ID: 75 (8.4%)
- URL: 36 (4.0%)

By shape:
- `free_text_heterogeneous`: 526 (58.9%)
- `opaque_tokens`: 367 (41.1%)

By corpus (where the missed shards came from):
- `nemotron`: heavy CONTACT contributor
- `gretel_finance`: heavy CONTACT and CREDENTIAL contributor

## 5. NEGATIVE family is a metric artifact

208 NEGATIVE shards are counted as suppressed-and-missed. But for NEGATIVE ground truth, "predict nothing" is the *correct* answer — the benchmark metric is symmetric and treats no-prediction as wrong for any class. This is ~5% of the headline regression and ~23% of the joint-miss count. The real joint miss for non-NEGATIVE classes is 685 shards (5.8% of corpus, not 7.6%).

The sibling backlog item (`add-joint-miss-rate-metric-to-family-benchmark-use-as-sprint-gate`) should explicitly exclude NEGATIVE from the joint miss numerator.

## 6. Implications

### Sprint completion gate (CLAUDE.md)

The current gate metric `shadow.overall.family.cross_family_rate` is unsuitable as a quality signal:

- It mostly tracks **router-suppression rate**, which is determined by corpus shape composition.
- Adding harder corpora to the pool will mechanically increase this metric without any code change.
- It also penalizes correctly-routed-and-LIVE-caught shards as if they were misses.

The gate should be replaced with `joint_miss_rate` (excluding NEGATIVE), which gives a direct system-level signal that's invariant to corpus composition.

### Sprint 18 candidates

1. **`lift-contact-recall-in-free-text-heterogeneous-shape-333-shard-joint-miss`** (P1, M) — recover the 333 CONTACT shards. Dovetails with the existing per-value-gliner-aggregation handler (Sprint 13, shipped). Concrete target: joint-miss for CONTACT 333 → <100, LIVE CONTACT F1 0.7621 → ≥0.85.

2. **`add-joint-miss-rate-metric-to-family-benchmark-use-as-sprint-gate`** (P1, S) — emit the metric, excluding NEGATIVE; update CLAUDE.md gate language.

3. **`fail-loud-benchmark-fixture-loader-replace-silent-empty-list-fallback`** (P1, S) — already filed. Prevents this measurement-honesty failure mode from recurring.

### Sprint 17 handover note

The "regression vs S16 baseline" in this sprint's family_macro_f1 numbers is **honest measurement on the full corpus, not a code regression**. The corpus-coverage delta accounts for the entire shift. PR #22 (unified WASM detector merge) does not change detection accuracy.

## Appendix — reproducing this analysis

The diagnostic was driven by `/tmp/main_full.bench.predictions.jsonl` (per-shard predictions from the full-corpus benchmark on `sprint17/main` at `765b0a3`). Each record has:

- `ground_truth`, `ground_truth_families` — gold labels
- `predicted` (LIVE entity-type), `findings[].family` (LIVE family per finding)
- `shadow_predicted`, `shadow_suppressed_by_router` — meta-classifier outputs
- `shape` — `structured_single` / `opaque_tokens` / `free_text_heterogeneous`
- `corpus`, `mode` (named/blind), `source` (real/synthetic)

Re-run the family benchmark with `DATA_CLASSIFIER_DISABLE_ML=0` from a worktree with all 8 fixture files in `tests/fixtures/corpora/` to reproduce.
