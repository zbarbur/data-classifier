# M1 — StratifiedKFold → StratifiedGroupKFold CV fix

> **Date:** 2026-04-13
> **Sprint:** 9 (kickoff-day experiment)
> **Branch:** `research/meta-classifier`
> **Experiment ID:** `m1-2026-04-13`
> **Status:** ✅ Done. Verdict: **SHIP the CV fix via a Sprint 9 promotion item.**
> **Candidate artifact:** `data_classifier/models/meta_classifier_v1_m1_groupkfold.pkl`

## Goal

Close the Q3 methodology finding by replacing `StratifiedKFold` with
`StratifiedGroupKFold(groups=corpora)` in the meta-classifier's best-C
selection grid search.

**Why:** Q3's LOCO investigation (2026-04-12) diagnosed that the Sprint 6
headline CV macro F1 of 0.916 was inflated by corpus-fingerprint leakage
across folds. The model's top feature is `heuristic_avg_length`, which
covaries strongly with corpus identity — under StratifiedKFold, the CV
folds mix samples from all corpora, so the classifier learns to predict
corpus identity first and label second. Honest generalization (LOCO)
sits at ~0.31, a 0.55-point gap the Sprint 6 handover flagged and
Q3/Q5/Q6/E10 research confirmed is structural.

The M1 fix tightens best-C selection so the grid search no longer
rewards models that exploit the corpus shortcut. Per Q3 §5a, the fix is
expected to (a) pick a smaller C (~1) rather than C=100 and (b) drop
the reported CV score to its honest level.

## Implementation

Single-file change in `scripts/train_meta_classifier.py`:

1. Import swap: `StratifiedKFold` → `StratifiedGroupKFold`
2. Thread `corpora_arr = np.asarray(dataset.corpora)` through the outer
   `train_test_split` so `corpora_train` is aligned with `X_train` /
   `y_train`
3. Replace the splitter construction:
   ```python
   kf = StratifiedGroupKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
   ```
4. Pass `groups=corpora_train` to `kf.split(X_train_s, y_train, groups=corpora_train)`

No other changes. Outer train/test split remains a stratified random 80/20 —
that is still optimistic (leak-prone), but the backlog item scoped only the
inner CV loop. Outer split is a follow-up.

## Results

### Baseline (StratifiedKFold, `meta_classifier_v1.metadata.json` from 2026-04-12)

| Metric | Value |
|---|---:|
| `best_c` | **100.0** (Q3's "worst LOCO" C) |
| `cv_mean_macro_f1` | 0.9160 |
| `cv_std_macro_f1` | 0.0072 |
| `held_out_test_macro_f1` | 0.9185 |
| `total_rows` / `train_rows` / `test_rows` | 7770 / 6216 / 1554 |

CV history — note monotone increase, plateau at C=100:

| C | mean_f1 | std_f1 |
|---:|---:|---:|
| 0.01 | 0.5197 | 0.0257 |
| 0.1 | 0.7618 | 0.0078 |
| 1.0 | 0.8619 | 0.0050 |
| 10.0 | 0.8998 | 0.0091 |
| **100.0** | **0.9160** | **0.0072** |

### M1 — StratifiedGroupKFold (this run, 2026-04-13)

| Metric | Value | Δ vs baseline |
|---|---:|---:|
| `best_c` | **10.0** | −90 |
| `cv_mean_macro_f1` | **0.2539 ± 0.0956** | **−0.6621** |
| `held_out_test_macro_f1` | 0.9123 | −0.0062 |
| `held_out_test_ci_95_bca` | [0.8990, 0.9252] width 0.0262 | (new capture) |

Top-5 feature importances (from `top_importances` in `trained`):

| Rank | Feature | abs_coef_sum |
|---:|---|---:|
| 1 | `heuristic_avg_length` | 252.09 |
| 2 | `top_overall_confidence` | 139.68 |
| 3 | `regex_confidence` | 122.89 |
| 4 | `regex_match_ratio` | 111.18 |
| 5 | `primary_is_pii` | 108.09 |

## Interpretation

### The CV drop is a correctness improvement, not a regression

StratifiedKFold's 0.9160 was **inflated by ~0.66 F1** through corpus-identity
leakage across folds. Under StratifiedGroupKFold, each validation fold
holds out a whole corpus, so the classifier cannot learn "which corpus is
this sample from" as a proxy for the label. The resulting 0.2539 CV score
is the **honest** estimate of how well the model generalizes to a corpus
it was never trained on — which is close to the LOCO baseline (~0.31)
that Q3 and E10 both measured.

This matches Q3 §5a's prediction exactly: "GroupKFold selects C≈1–10 and
raises LOCO to ~0.3427 (Δ +0.034)." Best-C landed at 10 rather than 1,
still within Q3's band, and still a massive correction from 100.

### The 13× variance jump is also expected

`cv_std_macro_f1` jumped from 0.0072 to 0.0956. High variance is the
natural consequence of leave-one-corpus-out behavior: every fold holds
out a structurally different corpus, so fold-to-fold scores differ
enormously. Under StratifiedKFold, folds were essentially IID samples
from the same distribution (all corpora mixed), so variance was tiny.
The new 0.0956 std is the **real** variance of the estimator across
corpus identities.

### The held-out test score barely moved (0.9185 → 0.9123)

Because the outer 80/20 split is still a random stratified split, the
test set contains samples from every corpus at their natural prevalence.
The held-out test score therefore exhibits the same corpus-leak as the
old CV (just less obviously). This test number is **not** a credible
generalization estimate for the same reason the old CV wasn't. Going
forward, cite LOCO, not held-out test.

### `heuristic_avg_length` is (still) the corpus-fingerprint shortcut

The top feature by absolute coefficient sum is `heuristic_avg_length`
(252.09, ~1.8× higher than the next feature). This confirms Q3 §6's
finding: the meta-classifier's "knowledge" is dominated by a scalar
that encodes average string length, which in practice encodes
corpus identity (credential-pure corpora have short strings; mixed-
label corpora have longer ones). The M1 fix stops the grid search
from *rewarding* this feature at best-C selection, but it does **not
eliminate** the feature from the model. That's a separate concern —
see "Follow-ups" below.

## Verdict — SHIP the CV fix

The M1 fix is a pure correctness improvement. It makes the reported CV
score honest, picks a more appropriate regularization strength, and
costs essentially nothing on the (still-optimistic) held-out test set.
Ship via a Sprint 9 promotion item that applies the same edit to the
production `scripts/train_meta_classifier.py` on `sprint9/main` and
regenerates `data_classifier/models/meta_classifier_v1.pkl` from the
new training data (which will also include Gretel-EN once the
ai4privacy-license-reaudit item lands).

## Follow-ups

1. **LOCO measurement is NOT captured by `train_meta_classifier.py`**.
   The script computes in-CV macro F1 and a random-split held-out F1.
   Measuring the real LOCO number requires running
   `tests/benchmarks/meta_classifier/evaluate.py` against the new
   candidate pkl. That is a separate follow-up, not in M1's scope,
   because LOCO measurement requires a different code path and is
   sensitive to which corpora are present in `training_data.jsonl`.
   Suggested follow-up: a small `m1-loco-check` experiment once
   Gretel-EN has been wired into the training data builder (which
   happens in Sprint 9's `ai4privacy-license-reaudit` work, currently
   in flight).

2. **`heuristic_avg_length` is still the dominant feature**. The M1 fix
   penalizes models that exploit it, but it doesn't *remove* the
   feature. Two downstream paths to weaken it further: (a) Sprint 9's
   Gretel-EN ingest (done, commit `e49e1d8` on `sprint9/main`) adds a
   mixed-label corpus where credentials co-occur with PII/health/
   financial labels in single documents, breaking the
   avg-length→corpus-identity correlation at the data source; (b) a
   Sprint 10 item could explicitly drop `heuristic_avg_length` from
   the feature set and re-measure LOCO to quantify how much of the
   remaining performance is load-bearing on the shortcut.

3. **Outer 80/20 split is still random.** A proper GroupShuffleSplit or
   LeaveOneCorpusOut outer split would give a more honest held-out
   number. Not in M1 scope; a Sprint 10 candidate.

4. **Training data will change on the next rebuild.** Sprint 9's
   `ai4privacy-license-reaudit` item (in flight) drops ai4privacy and
   adds Gretel-EN to `training_data.jsonl`. Any metric re-measured
   after that rebuild will reflect a different corpus composition, so
   the M1 results in this memo are a snapshot against the **pre-Gretel**
   training data (~7770 rows with ai4privacy).

## Artifacts

- **Candidate model:** `data_classifier/models/meta_classifier_v1_m1_groupkfold.pkl`
  (non-v1 suffix per research workflow contract; do NOT rename to v1 on
  this branch)
- **Candidate metadata:** `data_classifier/models/meta_classifier_v1_m1_groupkfold.metadata.json`
  (contains cv_history, per-class F1 on the held-out test, and the
  training_date ISO stamp)
- **Code change:** `scripts/train_meta_classifier.py` (single-function
  diff in `train()`, import swap + groups threading)
- **Baseline for comparison:** `data_classifier/models/meta_classifier_v1.metadata.json`
  (unchanged on this branch; committed 2026-04-12)

## Provenance

- **Feature extraction:** reused the existing `training_data.jsonl`
  (7770 rows, 13 features) built on 2026-04-12 by the Q3 experiment
  run. Not rebuilt for M1.
- **Q3 primary source numbers:** `docs/experiments/meta_classifier/runs/q3-*/result.md`
  on `research/meta-classifier`
- **Memory notes consulted:** `project_active_research.md` (cite +0.191
  meta-classifier delta from E10, not +0.257), `project_research_workflow.md`
  (non-v1 pkl naming, single-commit result memo)

## Promotion checklist (for the Sprint 9 or Sprint 10 promotion item)

When promoting this result to production on `sprint9/main`:

1. Apply the same `StratifiedKFold → StratifiedGroupKFold` edit to
   `scripts/train_meta_classifier.py` on `sprint9/main` (the file is
   not touched by the `ai4privacy-license-reaudit` agent, so merge
   should be conflict-free as long as ai4privacy lands first)
2. Rebuild `training_data.jsonl` from the post-ai4privacy corpus set
   (includes Gretel-EN, excludes ai4privacy)
3. Run `scripts/train_meta_classifier.py` with default output paths
   to regenerate `meta_classifier_v1.pkl` + metadata
4. Verify `best_c ≤ 10` in the new metadata (M1 invariant)
5. Run a full `pytest tests/ -v` + `scripts/install_smoke_test.py`
6. Update `docs/process/PROJECT_CONTEXT.md` with the new CV/LOCO
   numbers and cite this memo
7. Close the Sprint 9 `m1-meta-classifier-cv-fix-stratifiedkfold-stratifiedgroupkfold-q3-diagnosis`
   item as done in the same commit
