# Q5 — Feature distribution audit (descriptive stats)

**Run date:** 2026-04-12
**Branch:** `research/q5-feature-audit` (off `research/meta-classifier`)
**Session:** Session B (parallel to Q3 model-based ablation)
**Type:** Descriptive statistics only — **no model retraining**
**Inputs:** `tests/benchmarks/meta_classifier/training_data.jsonl` (7,770 rows)
**Reproduce:** `.venv/bin/python analyze.py` from this directory.
Outputs: `feature_ranking.csv`, `per_corpus_stats.csv`, `pairwise_ks.csv`,
`summary.json`, `hist_<feature>.png` for the top-5 suspects.

## TL;DR

The coefficient-based hypothesis (`heuristic_avg_length` is the dominant
leaker, 2× runner-up) is **confirmed but incomplete**. `heuristic_avg_length`
is one of *four* features whose per-corpus distributions are perfectly
separated (max KS = 1.000) — the model has at least four corpus-fingerprint
shortcuts available, not one. Binning `heuristic_avg_length` alone is
necessary but not sufficient to close the LOCO gap.

The deeper structural finding: three of the six corpora (gitleaks,
secretbench, detect_secrets) are **label-pure** — every row is either
`CREDENTIAL` or `NEGATIVE`. So any feature that discriminates "credential
corpus vs. PII corpus" is mathematically equivalent to predicting the
label, and there is no way for the LR model to learn within-corpus
discrimination for those labels. This is a data-construction issue as
much as a feature-engineering one.

## Method

1. Loaded `training_data.jsonl` into a `pandas.DataFrame`. Each row carries
   `corpus`, the 15-dim `features` vector (matches
   `data_classifier.orchestrator.meta_classifier.FEATURE_NAMES`), and
   `ground_truth`.
2. For every feature × corpus pair, computed n, mean, std, min/max,
   and percentiles {p10, p25, p50, p75, p90}.
3. For every feature, computed the one-way ANOVA F-statistic across all
   six corpora and pairwise two-sample Kolmogorov–Smirnov statistics for
   all C(6, 2) = 15 corpus pairs. Ranked features by **max pairwise KS**.
4. Plotted overlaid per-corpus density histograms for the top-5 suspects
   with shared bins (`hist_*.png`).
5. Cross-checked the (corpus × ground_truth) contingency table to
   contextualize what "leakage" means structurally for this dataset.

## Corpora present

| Corpus           |    n | Label coverage                                                   |
| ---------------- | ---: | ---------------------------------------------------------------- |
| `synthetic`      | 3720 | 24 entity types (no `CREDENTIAL`, no `NEGATIVE`)                 |
| `nemotron`       | 1950 | 13 PII entity types + `CREDENTIAL` (150)                         |
| `ai4privacy`     | 1200 | 8 PII entity types + `CREDENTIAL` (150)                          |
| `gitleaks`       |  300 | **only** `CREDENTIAL` (150) and `NEGATIVE` (150)                 |
| `secretbench`    |  300 | **only** `CREDENTIAL` (150) and `NEGATIVE` (150)                 |
| `detect_secrets` |  300 | **only** `CREDENTIAL` (150) and `NEGATIVE` (150)                 |

The three credential-source corpora are 100% pure on `{CREDENTIAL,
NEGATIVE}`. This matters for the verdict — see §Verdict below.

## Feature ranking by inter-corpus divergence

Ranked descending by max pairwise KS (KS ∈ [0, 1]; KS = 1 ⇒ disjoint
empirical CDFs in the worst pair). F-statistic comes from one-way ANOVA
across all six corpora.

| Rank | Feature                       |  max KS | worst pair                       |    F-stat |  ANOVA p   |
| ---: | ----------------------------- | ------: | -------------------------------- | --------: | :--------- |
|    1 | `secret_scanner_confidence`   |   1.000 | ai4privacy vs secretbench        |    9892.99 | < 1e-300   |
|    2 | `heuristic_distinct_ratio`    |   1.000 | ai4privacy vs detect_secrets     |     905.08 | < 1e-300   |
|    3 | `heuristic_avg_length`        |   1.000 | ai4privacy vs gitleaks           |    3333.94 | < 1e-300   |
|    4 | `has_secret_indicators`       |   1.000 | ai4privacy vs secretbench        |   10157.94 | < 1e-300   |
|    5 | `primary_is_credential`       |   0.960 | secretbench vs synthetic         |    1880.69 | < 1e-300   |
|    6 | `confidence_gap`              |   0.814 | detect_secrets vs synthetic      |     152.16 |   1.2e-154 |
|    7 | `primary_is_pii`              |   0.787 | ai4privacy vs secretbench        |     391.06 | < 1e-300   |
|    8 | `regex_match_ratio`           |   0.685 | secretbench vs synthetic         |     278.23 |   1.4e-274 |
|    9 | `top_overall_confidence`      |   0.676 | ai4privacy vs secretbench        |     210.14 |   7.8e-211 |
|   10 | `engines_fired`               |   0.567 | ai4privacy vs secretbench        |     195.08 |   2.1e-196 |
|   11 | `regex_confidence`            |   0.500 | detect_secrets vs secretbench    |     188.57 |   3.9e-190 |
|   12 | `engines_agreed`              |   0.500 | detect_secrets vs gitleaks       |      44.87 |   8.1e-46  |
|   13 | `column_name_confidence`      |   0.250 | ai4privacy vs detect_secrets     |      33.38 |   7.9e-34  |
|   14 | `has_column_name_hit`         |   0.250 | ai4privacy vs detect_secrets     |      40.94 |   1.0e-41  |
|   15 | `heuristic_confidence`        |   0.024 | ai4privacy vs nemotron           |       9.10 |   1.2e-08  |

The KS = 1.0 cluster (ranks 1–4) is the headline. These four features each
have at least one pair of corpora whose feature values **do not overlap at
all** — not at the tails, not anywhere. A logistic regression with these
inputs has lossless access to "is this row from a credential corpus"
through any one of them.

`heuristic_confidence` (rank 15) is essentially identical across corpora
(KS = 0.024) and is the only feature that does *not* leak corpus identity
in any meaningful way.

## Top-5 suspects — per-corpus distributions

Histograms with shared bins are saved as PNG in this directory. The
percentile tables below are the textual fallback the spec asks for.

### 1. `secret_scanner_confidence` (max KS = 1.000)

| corpus           |    n |  mean |   std |   p10 |   p25 |   p50 |   p75 |   p90 |
| :--------------- | ---: | ----: | ----: | ----: | ----: | ----: | ----: | ----: |
| `ai4privacy`     | 1200 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| `nemotron`       | 1950 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| `synthetic`      | 3720 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| `detect_secrets` |  300 | 0.448 | 0.450 | 0.000 | 0.000 | 0.345 | 0.903 | 0.903 |
| `gitleaks`       |  300 | 0.830 | 0.193 | 0.855 | 0.855 | 0.855 | 0.903 | 0.903 |
| `secretbench`    |  300 | 0.903 | 0.000 | 0.903 | 0.903 | 0.903 | 0.903 | 0.903 |

By construction the secret scanner only fires on credential-shaped values.
PII corpora are pinned at exactly 0; credential corpora live at >0.34. This
is a perfect proxy for "credential vs. non-credential corpus." See
`hist_secret_scanner_confidence.png`.

### 2. `heuristic_distinct_ratio` (max KS = 1.000)

| corpus           |    n |  mean |   std |   p10 |   p25 |   p50 |   p75 |   p90 |
| :--------------- | ---: | ----: | ----: | ----: | ----: | ----: | ----: | ----: |
| `ai4privacy`     | 1200 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| `nemotron`       | 1950 | 0.988 | 0.020 | 0.961 | 0.981 | 1.000 | 1.000 | 1.000 |
| `secretbench`    |  300 | 0.934 | 0.052 | 0.859 | 0.893 | 0.937 | 0.982 | 1.000 |
| `synthetic`      | 3720 | 0.792 | 0.340 | 0.022 | 0.861 | 0.941 | 0.971 | 1.000 |
| `gitleaks`       |  300 | 0.581 | 0.241 | 0.224 | 0.352 | 0.611 | 0.786 | 0.876 |
| `detect_secrets` |  300 | 0.112 | 0.077 | 0.037 | 0.055 | 0.087 | 0.143 | 0.227 |

`ai4privacy` is *exactly* 1.0 on every row (the upstream corpus emits one
unique value per column). `detect_secrets` lives in [0.04, 0.35] (the
detected-secrets dataset has heavy duplication of stub credentials). The
two are fully disjoint.

### 3. `heuristic_avg_length` (max KS = 1.000) — the coefficient-flagged feature

| corpus           |    n |  mean |   std |   p10 |   p25 |   p50 |   p75 |   p90 |
| :--------------- | ---: | ----: | ----: | ----: | ----: | ----: | ----: | ----: |
| `ai4privacy`     | 1200 | 0.150 | 0.058 | 0.077 | 0.114 | 0.139 | 0.178 | 0.252 |
| `nemotron`       | 1950 | 0.178 | 0.122 | 0.090 | 0.106 | 0.166 | 0.187 | 0.257 |
| `synthetic`      | 3720 | 0.178 | 0.110 | 0.095 | 0.100 | 0.110 | 0.232 | 0.373 |
| `detect_secrets` |  300 | 0.331 | 0.157 | 0.165 | 0.178 | 0.292 | 0.488 | 0.514 |
| `secretbench`    |  300 | 0.469 | 0.046 | 0.415 | 0.439 | 0.465 | 0.491 | 0.525 |
| `gitleaks`       |  300 | 0.935 | 0.102 | 0.754 | 0.912 | 0.990 | 1.000 | 1.000 |

`gitleaks` (long token-style API keys) and `ai4privacy` (short PII text)
have non-overlapping IQRs and a 6.2× mean ratio. The coefficient hypothesis
nails this one. See `hist_heuristic_avg_length.png`.

### 4. `has_secret_indicators` (max KS = 1.000)

Binary feature.

| corpus           | mean (= P(=1)) |
| :--------------- | -------------: |
| `ai4privacy`     |          0.000 |
| `nemotron`       |          0.000 |
| `synthetic`      |          0.000 |
| `detect_secrets` |          0.500 |
| `gitleaks`       |          0.953 |
| `secretbench`    |          1.000 |

A second perfect "is this a credential corpus" indicator. Together with
`secret_scanner_confidence` it carries redundant corpus-identity signal —
the LR may have spread its weight across both, which is consistent with
neither being individually flagged as a 2× outlier coefficient.

### 5. `primary_is_credential` (max KS = 0.960)

| corpus           |    n |  mean (= P(=1)) |
| :--------------- | ---: | --------------: |
| `synthetic`      | 3720 |           0.000 |
| `ai4privacy`     | 1200 |           0.059 |
| `nemotron`       | 1950 |           0.069 |
| `detect_secrets` |  300 |           0.413 |
| `gitleaks`       |  300 |           0.720 |
| `secretbench`    |  300 |           0.960 |

Same story. Note that `synthetic` is exactly 0 — synthetic data was
generated *without* the CREDENTIAL category, so this feature is also a
synthetic-vs-not indicator, not just a credential-corpus indicator.

## Binning proposals — top 3 suspects

The brief asks for binning proposals as the proposed mitigation. These are
post-processing transforms applied during training; **no production code is
modified by this experiment**. A separate sprint backlog item would
promote whichever the next training run validates.

### 1. `secret_scanner_confidence`

The raw values cluster on a small set of points: `{0, 0.345, 0.855, 0.903}`.
The 0.855 vs. 0.903 split is gitleaks vs. secretbench corpus identity, not
information about whether the value is a credential.

**Proposal:** 3 bins.
- bin 0 (`none`): value == 0.0
- bin 1 (`weak`): 0.0 < value ≤ 0.7
- bin 2 (`strong`): value > 0.7

**Cut points:** {0.0, 0.7}.
**What breaks:** the model can no longer distinguish gitleaks from
secretbench by hairsplitting 0.855 vs 0.903.
**What's preserved:** PII corpora (pinned at 0) remain perfectly separated
from any fired secret-scanner result; partial-confidence detect_secrets
rows still get a distinct bin from full-confidence credential rows.

### 2. `heuristic_distinct_ratio`

Continuous in [0, 1] but bimodal on the corpus axis: PII corpora are
plastered against 1.0, detect_secrets is plastered near 0.1, gitleaks
sits in the middle.

**Proposal:** 4 bins.
- bin 0 (`heavy_dup`): < 0.30
- bin 1 (`some_dup`): 0.30 ≤ x < 0.70
- bin 2 (`mostly_distinct`): 0.70 ≤ x < 0.95
- bin 3 (`all_distinct`): x ≥ 0.95

**Cut points:** {0.30, 0.70, 0.95}.
**What breaks:** `ai4privacy` and `nemotron` collapse into the same bin
(both ≥ 0.95) — but they were already nearly identical on this feature
and the model has other features to distinguish them.
**What's preserved:** the high-duplication signature typical of
`detect_secrets`-style stub credential dumps stays separated from PII text.

### 3. `heuristic_avg_length`

Continuous in [0, 1]. The coefficient hypothesis flagged this. The
distribution is essentially monotone with corpus type: synthetic/nemotron/
ai4privacy in [0.10, 0.25], detect_secrets/secretbench in [0.30, 0.55],
gitleaks in [0.75, 1.00].

**Proposal:** 4 bins.
- bin 0 (`short`): < 0.20
- bin 1 (`medium`): 0.20 ≤ x < 0.45
- bin 2 (`long`): 0.45 ≤ x < 0.75
- bin 3 (`very_long`): x ≥ 0.75

**Cut points:** {0.20, 0.45, 0.75}.
**What breaks:** within-PII length distinctions disappear — first names
(short) get pooled with phone numbers (also short). That fine-grained
signal is per-corpus anyway and doesn't generalize.
**What's preserved:** long-token credentials (`gitleaks`-style API keys)
still get separated from short PII fields, which is the *one*
generalizable signal length actually provides.

## Verdict

**Coefficient hypothesis:** the LR model's `heuristic_avg_length`
coefficient (magnitude 488, ~2× the runner-up) flagged it as the dominant
leaker.

**Descriptive-stats finding:** confirmed for `heuristic_avg_length` —
max KS = 1.000, F-stat = 3334, IQRs disjoint between gitleaks and
ai4privacy. The coefficient was a true signal.

**But:** three other features are *equally* divergent at the data level
(`secret_scanner_confidence`, `heuristic_distinct_ratio`,
`has_secret_indicators` all hit max KS = 1.000). The model-side analysis
didn't surface them as outliers because the LR loss can spread
correlated corpus-identity signal across multiple coefficients, leaving
`heuristic_avg_length` as the only continuous feature large enough to be
visually obvious in a coefficient bar chart. The data-side analysis is
agnostic to that distribution and surfaces the full leak surface.

**The deeper structural problem (out of scope for binning alone):** three
of the six corpora — `gitleaks`, `secretbench`, `detect_secrets` — contain
*only* `CREDENTIAL` and `NEGATIVE` rows. Under leave-one-corpus-out, when
a label-pure corpus is held out, the model loses examples for that label
class entirely. Any feature that even imperfectly tracks corpus identity
becomes a perfect proxy for label class on the held-out fold, because
within-corpus label diversity does not exist. This explains why the LOCO
gap (CV 0.916 → LOCO 0.27–0.36) is so large: it isn't only that
`heuristic_avg_length` leaks; it's that the data partition makes any
corpus signal *equivalent to* a label signal.

**Implications for next experiments:**

1. **Bin all four KS = 1.0 features**, not just `heuristic_avg_length`
   alone. Q3's model-based ablation should validate which combination
   actually moves LOCO. Expect partial improvement from binning alone —
   the structural label/corpus correlation cannot be removed by feature
   engineering, only by data collection.
2. **Consider dropping `has_secret_indicators` entirely** — it is fully
   redundant with the binned `secret_scanner_confidence` and exists only
   to give the LR a faster shortcut to corpus identity.
3. **Suggest a sprint backlog item** to either (a) source PII-labelled
   rows from the credential corpora (e.g., extract `EMAIL`/`URL` lines
   from gitleaks repositories) or (b) source credential-labelled rows
   from PII corpora (e.g., synthesise API keys with the same noise
   distribution as nemotron rows). Either would let LOCO test
   genuine within-corpus generalization rather than the current
   "predict label = predict corpus" shortcut.
4. **`heuristic_confidence` (max KS = 0.024) is the only clean feature.**
   It survives every pair comparison and carries genuine signal. Whatever
   that engine is doing is the right thing — its design should be the
   model template for future heuristic features.

## Cross-reference with Q3

Q3 (model-based feature ablation) is running in parallel to this
experiment. The two should converge: if Q3's LOCO improvement is largest
when *any* of the four KS = 1.0 features is dropped, the diagnoses agree.
If Q3 shows that dropping `heuristic_avg_length` alone closes most of the
gap, then the LR is using it as its single dominant shortcut despite the
other three being available — which would be a useful piece of
information about LR convergence on collinear leak features. Either way,
the recommendation (bin the top group, do not drop alone) holds.

## Files in this run

```
analyze.py                              — reproducible analysis script
feature_ranking.csv                     — 15 features × {max_ks, pair, F, p}
per_corpus_stats.csv                    — feature × corpus → mean/std/percentiles
pairwise_ks.csv                         — feature × C(6,2) pair → KS, p_value
summary.json                            — programmatic snapshot of headline numbers
hist_secret_scanner_confidence.png      — top-1 suspect overlay
hist_heuristic_distinct_ratio.png       — top-2 suspect overlay
hist_heuristic_avg_length.png           — top-3 suspect (coefficient-flagged) overlay
hist_has_secret_indicators.png          — top-4 suspect overlay
hist_primary_is_credential.png          — top-5 suspect overlay
result.md                               — this document
```
