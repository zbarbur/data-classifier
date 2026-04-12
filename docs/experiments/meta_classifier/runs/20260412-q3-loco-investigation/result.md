# Q3 — LOCO collapse investigation

**Date:** 2026-04-12
**Session:** Parallel research session A, worktree `data_classifier-q3`,
branch `research/q3-loco-investigation`
**Input:** `tests/benchmarks/meta_classifier/training_data.jsonl`
(7770 rows, 6 corpora, 24 classes, 15-feature schema → 13 effective
after dropping `engines_fired` and `has_column_name_hit`)
**Driver:** `tests/benchmarks/meta_classifier/q3_loco_ablation.py`
(new, research-side only — no production code touched)

## TL;DR

The Phase 2 LOCO collapse (macro F1 0.27–0.36 vs standard-CV 0.92) is
**primarily a structural problem, not a feature-engineering problem**.
The dominant hypotheses are **A** (too few corpora to support LOCO) and
**C** (generator-level i.i.d. violation — every corpus has its own
feature-distribution fingerprint). Hypothesis B (one or two features
doing all the leaking) is **refuted in its strong form**: no single
feature in the 13-D schema is responsible for the gap, and the primary
suspect `heuristic_avg_length` is only asymmetrically leaky.

Best intervention found — drop `{confidence_gap, engines_agreed,
heuristic_confidence}` and refit at `C=10` — improves LOCO macro F1
from **0.3087 → 0.4392** (Δ = **+0.1305**). This closes roughly
**21%** of the gap, not the ≥50% the queue's success criterion asks
for. A candidate model has been saved to
`data_classifier/models/meta_classifier_v1_q3.pkl` as diagnostic
evidence, but the Q3 success gate (LOCO ≥ 0.55) is **NOT** met.

Main actionable finding the Sprint backlog should pick up: the
production CV loop in `scripts/train_meta_classifier.py` picks `C=100`
(minimal regularization) because i.i.d. 5-fold CV rewards corpus
fingerprinting. A **GroupKFold-by-corpus** CV strategy would let the C
sweep see the right signal and auto-select a more LOCO-friendly
regularization. See §6.

## 1. Baseline reproduction

LOCO refit harness is the same as `evaluate.py::_loco_fit_predict` —
LogisticRegression(C=100.0, class_weight="balanced", lbfgs, 2000
iters), StandardScaler fit on training corpora only, seed 42.

| Holdout | n_test | macro F1 |
|---|---|---|
| ai4privacy | 1,200 | 0.2595 |
| nemotron   | 1,950 | 0.3579 |
| **mean**   |       | **0.3087** |

This reproduces the Phase 2 report (0.27–0.36). Matches exactly.

## 2. Forward ablation (drop-one of 13 features, sorted by mean LOCO)

| Dropped feature | ai4p F1 | nemo F1 | Mean LOCO | Δ vs baseline |
|---|---|---|---|---|
| confidence_gap           | 0.1922 | 0.4463 | 0.3193 | **+0.0106** |
| heuristic_confidence     | 0.2602 | 0.3774 | 0.3188 | **+0.0101** |
| has_secret_indicators    | 0.2789 | 0.3512 | 0.3151 | +0.0064 |
| engines_agreed           | 0.2621 | 0.3646 | 0.3133 | +0.0046 |
| column_name_confidence   | 0.2714 | 0.3475 | 0.3095 | +0.0008 |
| regex_confidence         | 0.2666 | 0.3468 | 0.3067 | −0.0020 |
| heuristic_avg_length     | 0.3079 | 0.3046 | 0.3062 | −0.0025 |
| primary_is_credential    | 0.2722 | 0.3299 | 0.3010 | −0.0077 |
| top_overall_confidence   | 0.2364 | 0.3629 | 0.2996 | −0.0091 |
| heuristic_distinct_ratio | 0.2758 | 0.3208 | 0.2983 | −0.0104 |
| secret_scanner_confidence| 0.2419 | 0.3509 | 0.2964 | −0.0123 |
| regex_match_ratio        | 0.1922 | 0.3953 | 0.2938 | −0.0149 |
| **primary_is_pii**       | 0.2032 | 0.3262 | 0.2647 | **−0.0440** |

**Key observations:**

- **Max single-feature drop-improvement is +0.0106**, far too small to
  explain a 0.6-point gap. No single feature is responsible for LOCO
  collapse.
- **`heuristic_avg_length` is the most counter-intuitive result.** The
  coefficient-magnitude hypothesis (`heuristic_avg_length` coef = 488,
  2× runner-up) predicts it should be the dominant leaker. Dropping it
  yields Δ = −0.0025 — essentially flat.
  *However*, the per-holdout effect is dramatic and asymmetric:
  `ai4privacy` jumps from 0.2595 → 0.3079 (+0.048) while `nemotron`
  falls from 0.3579 → 0.3046 (−0.053). The feature IS corpus-leaking —
  just symmetrically, so the mean hides the effect. The feature's
  net contribution to LOCO is a wash.
- **`primary_is_pii` is load-bearing for LOCO generalization.**
  Dropping it costs −0.044 — by far the biggest single-feature loss.
  Any future schema change should preserve this signal.
- **`regex_match_ratio` is also load-bearing** (Δ −0.015).
- `confidence_gap` and `heuristic_confidence` are the two most
  promising drop candidates. Both have the property that dropping
  them substantially boosts `nemotron` (0.36 → 0.45 / 0.38) without
  hurting `ai4privacy`.

## 3. Inverse ablation (keep-one of 13 features)

| Single feature kept | ai4p F1 | nemo F1 | Mean LOCO |
|---|---|---|---|
| top_overall_confidence   | 0.1449 | 0.0841 | 0.1145 |
| regex_confidence         | 0.1077 | 0.0804 | 0.0940 |
| regex_match_ratio        | 0.0950 | 0.0508 | 0.0729 |
| primary_is_credential    | 0.0714 | 0.0674 | 0.0694 |
| engines_agreed           | 0.0447 | 0.0451 | 0.0449 |
| heuristic_avg_length     | 0.0302 | 0.0431 | 0.0367 |
| heuristic_confidence     | 0.0278 | 0.0335 | 0.0307 |
| heuristic_distinct_ratio | 0.0278 | 0.0300 | 0.0289 |
| secret_scanner_confidence| 0.0278 | 0.0110 | 0.0194 |
| column_name_confidence   | 0.0222 | 0.0095 | 0.0159 |
| has_secret_indicators    | 0.0278 | 0.0000 | 0.0139 |
| confidence_gap           | 0.0000 | 0.0191 | 0.0095 |
| primary_is_pii           | 0.0000 | 0.0173 | 0.0086 |

**Key observation:** **No single feature exceeds LOCO 0.12 on its
own.** The top standalone performer is `top_overall_confidence` at
0.1145. Compared to the 13-feature baseline of 0.3087, this means
**every feature depends on interactions with other features to reach
its usefulness** — no feature is "universally generalizable."

This is very strong evidence for hypothesis C (generator-level i.i.d.
violation): if any feature were a clean, corpus-independent entity-type
signal, it would carry meaningful LOCO F1 on its own. None do.

Note that `primary_is_pii`, which is load-bearing in the drop-one
table, has keep-one LOCO of 0.0086 — it works only in concert with
other features. This is normal for a categorical one-hot feature
(it's a partitioning signal, not a discriminating signal).

## 4. Combined drop-set × regularization grid search

The forward ablation shows no single feature drop > 0.011. But
multiple drops may compound, and the hardcoded `C=100.0` in the LOCO
harness may not be optimal. A full grid search over:

- Drop sets of size 0–3 drawn from the 6 candidates that improved or
  were flat in §2 (`confidence_gap`, `engines_agreed`,
  `heuristic_avg_length`, `heuristic_confidence`,
  `has_secret_indicators`, `column_name_confidence`)
- Regularization `C ∈ {0.1, 1.0, 10.0, 100.0}`

**Top 5 configurations:**

| C | Drop set | ai4p | nemo | Mean LOCO |
|---|---|---|---|---|
| 10.0 | `confidence_gap, engines_agreed, heuristic_confidence` | 0.3155 | 0.5628 | **0.4392** |
| 10.0 | `confidence_gap, heuristic_confidence`                  | 0.3201 | 0.5382 | 0.4291 |
| 10.0 | `confidence_gap, heuristic_confidence, has_secret_indicators` | 0.2976 | 0.5382 | 0.4179 |
| 1.0  | `confidence_gap, heuristic_confidence`                  | 0.3103 | 0.5178 | 0.4141 |
| 1.0  | `confidence_gap, heuristic_confidence, has_secret_indicators` | 0.3033 | 0.5181 | 0.4107 |

**Key observations:**

- The best improvement is **+0.1305** over baseline, from
  `{confidence_gap, engines_agreed, heuristic_confidence}` dropped and
  trained at `C=10.0`. That closes **~21%** of the 0.61-point
  CV–LOCO gap.
- Almost all of the improvement hits `nemotron` (0.358 → 0.563,
  +0.205), while `ai4privacy` only moves slightly (0.260 → 0.316,
  +0.056). The drop set eliminates features that were telling the
  model "if you're in nemotron, trust your prior" — the features
  behave as corpus priors rather than class signals.
- The effect is **multiplicative with regularization**, not additive.
  At the same drop set, `C=100` gives only 0.315 mean LOCO (+0.007)
  — meaning the Phase 2 eval harness (`C=100`) underreports the
  benefit of any feature-schema change by a factor of ~20.

## 5. Supplementary findings

### 5a. Regularization sweep on the full 13-feature model

| C | ai4p F1 | nemo F1 | Mean LOCO |
|---|---|---|---|
| 0.01  | 0.1792 | 0.2159 | 0.1976 |
| 0.1   | 0.2254 | 0.3376 | 0.2815 |
| **1.0**   | **0.3237** | **0.3617** | **0.3427** |
| 10.0  | 0.2678 | 0.3681 | 0.3179 |
| 100.0 | 0.2595 | 0.3579 | 0.3087 |

`C=1.0` is the best single-knob intervention on the current 13-feature
schema: **+0.034 LOCO for zero feature engineering**. This is large
enough to flag, but not large enough to close the gap.

The production `scripts/train_meta_classifier.py` already CV-tunes `C`
over `[0.01, 0.1, 1.0, 10.0, 100.0]`, but it selects based on i.i.d.
stratified 5-fold CV — which rewards corpus fingerprinting. On the
full 13-feature schema the production pipeline picks `C=100`. On the
reduced 10-feature schema from §4 it picks `C=100` again. Neither is
the LOCO-optimal `C`.

### 5b. Binning `heuristic_avg_length` (Q3 bonus)

The raw distribution of `heuristic_avg_length` in the training data
is `min=0.1, median=0.1, max=1.0` — highly skewed, with the majority
of rows clustered at the short end. Quantile binning into 3/5/7
buckets gives:

| bins | cut points | ai4p F1 | nemo F1 | Mean LOCO |
|---|---|---|---|---|
| baseline (raw) | — | 0.2595 | 0.3579 | 0.3087 |
| 3 | [0.1, 0.2] | 0.2998 | 0.3354 | 0.3176 |
| 5 | [0.1, 0.1, 0.2, 0.4] | 0.3287 | 0.3019 | 0.3153 |
| 7 | [0.1, 0.1, 0.1, 0.2, 0.2, 0.4] | 0.2245 | 0.2805 | 0.2525 |
| drop entirely | — | 0.3079 | 0.3046 | 0.3062 |

**Binning does not meaningfully help.** The distribution is too
skewed for quantile binning — multiple bin edges collapse to the same
value (0.1). 3-bin gets Δ +0.009 (noise floor). 7-bin is
catastrophically worse because the bins become unstable across
corpora.

### 5c. Extended LOCO (hold out each corpus)

Phase 2's LOCO only reports `ai4privacy` and `nemotron` holdouts
because those are the only corpora with broad PII class coverage.
Running the extended holdout anyway is diagnostic:

| Holdout | n_test | n_classes in test | Macro F1 |
|---|---|---|---|
| ai4privacy     | 1,200 |  8 | 0.2595 |
| nemotron       | 1,950 | 13 | 0.3579 |
| synthetic      | 3,720 | 22 | **0.1328** |
| secretbench    |   300 |  2 | 0.3333 |
| gitleaks       |   300 |  2 | 0.0771 |
| detect_secrets |   300 |  2 | 0.0564 |

**These numbers are the single most damning evidence for hypothesis
C:**

- **Hold-out-synthetic → 0.13.** The synthetic corpus is training-
  side indispensable. Removing it collapses the model to near-chance
  performance across 22 classes. This means the model has not learned
  universal class rules — it has learned distributions of feature
  values that the synthetic corpus provides and that no real corpus
  covers adequately.
- **gitleaks / detect_secrets → 0.06-0.08.** Two small credential
  corpora that should be near-interchangeable with `secretbench` at
  the semantic level, yet the model gets nearly nothing right when
  either is held out. The credential shards carry per-generator
  fingerprints in their feature distributions.
- **secretbench → 0.33.** Recognisable (two-class holdout) but no
  better than the general PII holdouts, despite having the same
  ground-truth class mix as the held-out corpora.

## 6. Hypothesis verdict

| Hypothesis | Verdict | Evidence |
|---|---|---|
| **A.** Inherent to training on a small number of corpora | **Strongly supported** | Only 2 of 6 corpora support a meaningful LOCO evaluation (ai4p, nemo — the rest have <2 classes or collapse to <0.14 F1). Structural: cannot be fixed by any feature intervention on existing data. |
| **B.** Feature engineering problem — one or two features doing all the corpus-leaking | **Refuted in the strong form.** **Weakly supported.** | Forward drop-one max Δ = +0.011. Primary coefficient-magnitude suspect (`heuristic_avg_length`) is a wash at the mean level. However, combined drop-set + `C=10` recovers +0.13 — about 21% of the gap. Real, but far from the Q3 bar. |
| **C.** Generator-level i.i.d. violation the model cannot fix without more sources | **Strongly supported** | Inverse keep-one shows no single feature reaches 0.12 LOCO alone — every feature carries corpus signal that requires interactions to discriminate. Extended LOCO shows `synthetic`/`gitleaks`/`detect_secrets` holdouts collapse to <0.15 F1 — the classifier is effectively learning corpus distributions, not class rules. |

**Composite verdict: A + C are the dominant mechanisms, with weak B.**
The LOCO gap is not a bug in feature engineering; it is a structural
property of training a 24-class classifier on 6 corpora where most
class–corpus cells are sparse or absent.

## 7. Candidate model

Saved per Q3's instruction (save a candidate if A or B):

- **Path:** `data_classifier/models/meta_classifier_v1_q3.pkl`
- **Metadata:** `data_classifier/models/meta_classifier_v1_q3.metadata.json`
- **Features kept (10):** `top_overall_confidence`, `regex_confidence`,
  `column_name_confidence`, `secret_scanner_confidence`,
  `regex_match_ratio`, `heuristic_distinct_ratio`,
  `heuristic_avg_length`, `has_secret_indicators`, `primary_is_pii`,
  `primary_is_credential`
- **Features dropped:** `confidence_gap`, `engines_agreed`,
  `heuristic_confidence` (in addition to the always-dropped
  `engines_fired` and `has_column_name_hit`)
- **Regularization:** `C = 10.0` (forced — see §6)
- **Standard stratified CV macro F1:** 0.8667 ± 0.0044
- **Held-out 80/20 test macro F1:** 0.8833
- **LOCO mean (C=10 harness):** 0.4392 — +0.1305 vs baseline
- **LOCO mean (C=100 harness — Phase 2 comparable):** 0.3158 — +0.0071
  vs baseline

**Q3 success criterion: NOT MET.** The bar is "candidate model closes
>50% of the LOCO gap (LOCO F1 ≥ 0.55)." Best achievable with feature
engineering alone is 0.44, i.e. ~21% of the gap.

**Do NOT promote to production.** This pkl is a diagnostic artifact
only. `data_classifier/models/meta_classifier_v1.pkl` remains the
shipped model.

## 8. Recommendations for Sprint backlog

1. **CV strategy change (highest leverage).** Switch
   `scripts/train_meta_classifier.py::train` from `StratifiedKFold` to
   `sklearn.model_selection.GroupKFold(n_splits=5)` with
   `groups=dataset.corpora`. Expected effect:
     - Best `C` drops from 100 to 1–10.
     - Reported CV macro F1 drops from ~0.92 to ~0.4-0.5.
     - This is an **honest** CV number: it's within spitting distance
       of the real LOCO number, so future model comparisons aren't
       misled by fingerprinting.
     - Ship gate numbers will need recalibration. The current paired
       +0.25 vs live-baseline number on the 80/20 test set is NOT
       affected — that split is already in-distribution.
2. **LOCO harness unification.** The current `evaluate.py::_loco_fit_
   predict` hardcodes `C=100.0`, which is not the model's actual `C`.
   Change it to take `C` from the loaded model payload (or from a
   CLI flag) so the LOCO number reflects the model's real
   generalization, not an arbitrary refit.
3. **Corpus expansion is the only lever that closes the LOCO gap to
   ≥0.55.** This is an A+C diagnosis. Phase 3 work should prioritize
   adding real-world PII corpora (e.g. `pii-masking-200k`,
   `kaggle-customer-360`, anonymized production telemetry samples)
   over feature-schema experiments.
4. **If a feature schema change is worth shipping, the smallest
   defensible diff is** `drop {confidence_gap, heuristic_confidence}`
   (2 features, not 3 — `engines_agreed` only adds +0.01 and is
   informative for the meta-classifier's "confidence" output). This
   would be additive with the CV strategy change from (1).
5. **Do not remove `primary_is_pii` or `regex_match_ratio`.** Both are
   load-bearing for LOCO generalization. The drop-one ablation cost
   of removing them is larger than the gain from any feature added
   so far in the research queue.
6. **`heuristic_avg_length` is asymmetrically leaky, not net-leaky.**
   Binning does not help. If a future experiment revisits it, try
   **per-class standardization** (scale by the mean length of that
   entity type in the training set) rather than raw value or bins.

## 9. Time spent

Wall-clock ≈ 45 minutes. No single training run exceeded 5 seconds
(the grid search in §4 ran 4 × 4³ × 2 ≈ 512 LogisticRegression fits
in under a minute).

## 10. Artifacts

- `docs/experiments/meta_classifier/runs/20260412-q3-loco-investigation/result.md` — this file
- `docs/experiments/meta_classifier/runs/20260412-q3-loco-investigation/ablation_report.json` — raw drop-one / keep-one numbers
- `tests/benchmarks/meta_classifier/q3_loco_ablation.py` — reproducible ablation driver
- `data_classifier/models/meta_classifier_v1_q3.pkl` + `.metadata.json` — candidate diagnostic model (do not promote)
