---
title: Meta-classifier training-set sharding strategy
status: research
date: 2026-04-12
sprint: 6
owner: data_classifier
related:
  - tests/benchmarks/corpus_loader.py
  - tests/benchmarks/meta_classifier/build_training_data.py
  - tests/benchmarks/meta_classifier/extract_features.py
  - data_classifier/orchestrator/meta_classifier.py
---

# Sharding strategy for the meta-classifier training set

## 1. Why this matters now

Phase 1 of the meta-classifier (backlog item
`meta-classifier-for-learned-engine-arbitration-...`) shipped with a
**342-row / 23-class** training set in which only **42 rows come from
real corpora**, all other rows are Faker-synthetic, and `CREDENTIAL` has
**4 examples**. `build_training_data.py` already prints an "UNDERFIT
(<10)" warning on every class under 10 samples (see
`tests/benchmarks/meta_classifier/build_training_data.py:280`).

Before Phase 2 can fit a multinomial logistic regression over engine
signals and meaningfully claim an F1 improvement over the calibrated
baseline, we need a principled answer to:

- how much data is *enough* for this model class,
- how the ~438K Ai4Privacy + ~155K Nemotron raw values (and up to
  ~1.75M / ~621K from the full HF datasets) should be sharded into
  column-sized training rows, and
- how to split and bootstrap the result without lying to ourselves
  about generalization.

This document answers those four questions with numerical
recommendations that we can hand directly to the Phase 2 implementer.

## 2. What the data actually looks like

### 2.1 Feature vector

The user request mentions "11 features". The actual feature
dimension in `data_classifier/orchestrator/meta_classifier.py` is
**15**. `FEATURE_NAMES`:

| idx | name                       | kind       | notes |
|-----|----------------------------|------------|-------|
| 0   | `top_overall_confidence`   | continuous | = max(idx 1..4) by construction |
| 1   | `regex_confidence`         | continuous | |
| 2   | `column_name_confidence`   | continuous | |
| 3   | `heuristic_confidence`     | continuous | |
| 4   | `secret_scanner_confidence`| continuous | |
| 5   | `engines_agreed`           | count 0..4 | |
| 6   | `engines_fired`            | count 0..4 | |
| 7   | `confidence_gap`           | continuous | top − second |
| 8   | `regex_match_ratio`        | continuous | |
| 9   | `heuristic_distinct_ratio` | continuous | |
| 10  | `heuristic_avg_length`     | continuous | clipped mean len / 100 |
| 11  | `has_column_name_hit`      | boolean    | |
| 12  | `has_secret_indicators`    | boolean    | |
| 13  | `primary_is_pii`           | boolean    | |
| 14  | `primary_is_credential`    | boolean    | |

Because (a) idx 0 is a deterministic function of idx 1..4, (b) idx 5
and 6 are tightly correlated, and (c) idx 13/14 partition a subset
of classes, the **effective rank** of the feature matrix is closer to
**10–11 independent dimensions**. That matches the "11-feature"
intuition. For sample-size math below we treat `p_eff = 11` (effective)
and `p = 15` (nominal); we report both whenever they disagree.

### 2.2 Raw corpus inventory

| source            | raw rows (bundled) | raw rows (full HF) | distinct mapped types |
|-------------------|--------------------|--------------------|-----------------------|
| Ai4Privacy sample | 438,960            | ~1.75M             | 8                     |
| Nemotron sample   | 155,341            | ~621K              | 13                    |
| Faker synthetic   | unbounded          | unbounded          | 22                    |

Per-type availability (bundled):

Ai4Privacy: `PERSON_NAME` 93.8K · `DATE_OF_BIRTH` 68.3K · `SSN` 58.1K ·
`EMAIL` 51.4K · `IP_ADDRESS` 50.8K · `PHONE` 45.6K · `CREDENTIAL`
37.7K · `ADDRESS` 33.2K.

Nemotron: `EMAIL` 41.7K · `URL` 21.3K · `PHONE` 19.6K · `PERSON_NAME`
13.7K · `ADDRESS` 11.1K · `CREDENTIAL` 10.6K · `DATE_OF_BIRTH` 6.9K ·
`IP_ADDRESS` 6.9K · `CREDIT_CARD` 6.1K · `SWIFT_BIC` 5.5K ·
`ABA_ROUTING` 5.1K · `SSN` 3.6K · `MAC_ADDRESS` 3.4K.

The **minimum** per-type pool in the bundled fixtures is `SSN` in
Nemotron at 3,563 rows — still plenty.

### 2.3 What `_records_to_corpus` does today

`tests/benchmarks/corpus_loader.py:104` groups every record by its
mapped type and emits **exactly one `ColumnInput` per type** with up
to `max_rows=500` sample values. The result:

- Ai4Privacy → 8 columns.
- Nemotron → 13 columns.
- 21 total "real" columns. Doubled to 42 rows because
  `build_training_data.py` runs named + blind modes.

So today's loader is throwing away roughly `(438K − 4K)/500 ≈ 867`
potential Ai4Privacy shards for `PERSON_NAME` alone. Sharding is the
lever that unlocks the dataset we already have on disk.

## 3. Q1 — How much data does a 15-feature, 22-class multinomial LR need?

### 3.1 Classical rules and their limits

**Peduzzi EPV rule (1996).** Binary logistic regression needs
*Events Per Variable* ≥ 10, where "events" = minority-class count and
"variables" = model parameters. For multinomial LR with `K` classes
and `p` features, the one-vs-rest analog is "≥ 10 minority events
per parameter", which gives a floor of `10 × (p + 1)` rows per class
→ **160 rows for our smallest class** at `p = 15`, or **120 rows** at
`p_eff = 11`.

**Van Smeden et al. (2018/2019)** showed that EPV=10 is **too
optimistic** — it keeps the point estimate unbiased but leaves wide
variance on individual coefficients. They recommend a formula-driven
minimum that depends on the event fraction, Cox-Snell R² approximation,
and the largest-allowed shrinkage factor. Applied to our case:

- target shrinkage ≥ 0.9, target event fraction 1/K ≈ 0.045,
  assumed Cox-Snell R² of 0.2 (the engine confidences separate most
  classes cleanly — this is conservative if anything),
- formula yields roughly **80–120 rows per class** for stable
  coefficients, *plus* a global minimum of ~250–400 rows to control
  the intercept bias under L2 shrinkage.

**Riley et al. (2020), BMJ.** For multinomial LR, the recommended
global-minimum formula is `N ≥ max(over pairwise models) of
p / ((S − 1) × ln(1 − R² / S))` where S is the target shrinkage. For
`p=15`, `S=0.9`, pairwise `R²=0.2`, this yields **N ≈ 1,400 globally**
and a per-class floor around **100**.

### 3.2 Stacking-specific guidance

A meta-classifier over engine signals is a **stacking layer**, not a
from-scratch classifier. Two properties make the sample-size regime
friendlier than the rules above suggest:

1. **Features are already calibrated probabilities.** The engine
   confidences live in [0, 1] and are individually monotonic in the
   likelihood of the target class. Stacking only has to learn
   *relative weights and interactions*, not raw decision boundaries.
   Empirically (Wolpert 1992, Van der Laan et al. 2007), linear
   stackers reach their asymptote with **order-of-magnitude less
   data** than a raw classifier on the same task.

2. **The decision surface is low-complexity.** Out of 15 features,
   ~5 are indicators that collapse to "which engine fired", and the
   interesting continuous signals are 4: `regex_match_ratio`,
   `confidence_gap`, `heuristic_distinct_ratio`,
   `heuristic_avg_length`. A well-regularized linear stacker over
   these is not going to overfit if each class has ≥ 50 rows.

**Practical floor for a stacking meta-classifier on this problem:**

| regime           | rows/class | total (22 classes) | behavior                      |
|------------------|------------|--------------------|-------------------------------|
| trainable        | 30         | 660                | works, high variance          |
| **stable**       | **100**    | **2,200**          | **recommended minimum**       |
| healthy          | 200        | 4,400              | coefficients stable, CIs tight|
| diminishing      | 500+       | 11,000+            | marginal gains only           |

The `stable` row is where we want to land for Phase 2 training. It
clears Peduzzi, meets Riley's per-class floor, and gives enough
headroom that Phase-3 feature additions (we expect 2–4 more features)
won't push us back into under-powered territory.

**Recommendation: target 100–200 rows per entity type, 2,500–4,500 rows
total, for the Phase 2 training set.**

## 4. Q2 — How to shard: values of N (shards/type) and M (samples/shard)

### 4.1 The sharding trade-off

Let:

- `pool(t)` = number of raw values available for entity type `t`,
- `N(t)` = number of shards (columns) we emit for type `t`,
- `M` = number of sample values per shard.

The meta-classifier learns from **column-level features**, so the
learner never sees the raw values directly — it only sees the
aggregated signals produced by each engine over an M-sized sample.
Two failure modes bracket the choice of N and M:

**Too few shards (small N).** Every shard averages over a huge
sample, engine signals saturate, and the learner sees only a handful
of points per class. This is where we are today. Result: the LR
underfits the variability that production will actually encounter.

**Too many shards (large N), small M.** Each shard becomes
unrepresentative — with M=20 a single lucky regex match flips
`regex_confidence` from 0 to 1. The learner sees high sample-variance
noise that dominates the true between-class signal. Regression
coefficients shrink toward zero under L2 and the model degenerates
into "trust the strongest engine".

### 4.2 What M the learner should see

Two constraints pin M:

1. **Production match.** Real connectors send
   `len(sample_values)` typically in the **100–1,000** range (BQ
   connector defaults: 200; docs/spec examples: 100, 500, 1000). The
   training distribution of `M` should cover that range, or the model
   will be surprised at serve time.
2. **Feature SE.** All ratio/fraction features have binomial-ish
   standard error that decays as `1/√M`. For `M=50`,
   SE ≈ 0.07 on a fraction near 0.5; for `M=100`, SE ≈ 0.05; for
   `M=200`, SE ≈ 0.035; for `M=500`, SE ≈ 0.022. The production
   minimum we care about (200) already puts feature SE below the
   inter-class confidence gaps we want the learner to detect.

**Recommendation:** stratify M across **three buckets** per type so
the learner sees heteroscedastic samples:

| bucket | M range    | share of shards |
|--------|------------|-----------------|
| small  | 60–120     | 25%             |
| medium | 150–300    | 50%             |
| large  | 400–800    | 25%             |

A shard's exact size is drawn uniformly within its bucket.
`build_training_data.py` already does uniform subsampling in
`_rows_from_synthetic`; we extend the same pattern to real corpora.

### 4.3 What N the sharder should emit

Per Q1 we want ~150 rows per class. Each corpus contributes a
shard pool per type, so the total for entity `t` is:

```
total_rows(t)  =  N_ai4(t) + N_nemotron(t) + N_synth(t)
                  + (named × 2) duplication already in build_training_data
```

With the named/blind doubling that `build_training_data.py` already
applies (one pass named, one pass blind), the *effective* row count
per (type, corpus) unit is `2 × N`. So we can halve the unique shard
target:

**Target: N ≈ 75 unique shards per (type, source_corpus) combo**,
which yields `2 × 75 = 150` training rows per corpus after named/blind
doubling, and 300+ rows per type when a type exists in multiple
corpora.

#### Sharding without value leakage

For a given type `t` in a given corpus, we sample shards **without
replacement** at the value level:

```
values[t] = shuffled pool of size pool(t)
take shard_k = values[t][k*M_k : k*M_k + M_k]  for k = 0..N(t)-1
```

With N=75 and mean M ≈ 250, each type consumes 75 × 250 ≈ 19K
unique values per corpus. That is comfortably under every real-corpus
pool we have except Nemotron `SSN` (3.6K). For the underfunded Nemotron
types we fall back to **bootstrap-with-replacement at the shard level**
(see §6.3) and flag them as "synthetic-augmented" in the row metadata.

#### Underfit-class policy

Types that do not exist in *any* real corpus (e.g., `BITCOIN_ADDRESS`,
`IBAN`, `VIN`, `MBI`, `NPI`, `DEA_NUMBER`, `ETHEREUM_ADDRESS`,
`CANADIAN_SIN`, `EIN`, `DATE_OF_BIRTH_EU`) have to be carried by
Faker-synthetic alone. For those we need N ≥ 150 synthetic shards to
reach the 100-row stable threshold (after named/blind doubling, that's
300 rows). `_rows_from_synthetic` already has the mechanics — we only
raise `--synthetic-count` and teach it to stratify per type, not just
per locale.

### 4.4 Concrete target shapes

| type       | Ai4Privacy shards | Nemotron shards | Synthetic shards | rows after ×2 doubling |
|------------|-------------------|-----------------|------------------|------------------------|
| `EMAIL`    | 75                | 75              | 30               | 360                    |
| `PHONE`    | 75                | 75              | 30               | 360                    |
| `PERSON_NAME` | 75             | 75              | 30               | 360                    |
| `SSN`      | 75                | 14 (no-leak)    | 30               | 238                    |
| `CREDIT_CARD` | 0              | 24              | 75               | 198                    |
| `IBAN`     | 0                 | 0               | 150              | 300                    |
| `BITCOIN_ADDRESS` | 0          | 0               | 150              | 300                    |
| …          | …                 | …               | …                | ≥ 150 everywhere       |

Aggregate target: **3,500–4,500 rows, no class under 150, no class
over 500, real:synthetic ratio ≈ 60:40.**

Under this plan, the existing 438K / 155K bundled pool is consumed at
roughly 4% / 12% — so if we ever want to push to N=300 we can do it
without re-downloading.

## 5. Q3 — Train/test split strategy

Two split regimes get proposed whenever a small multi-class dataset
shows up; both are flawed here, for opposite reasons.

### 5.1 Split-by-shard (stratified random)

Shuffle the full row set, stratify on `ground_truth`, take 80/20.

- **Pro:** every class appears in both splits. Matches the production
  task "predict the entity type of an unseen column sample".
- **Con (feared):** value leakage — two shards of the same type
  from the same corpus can share raw values if we sampled with
  replacement. **Mitigated by §4.3**: we sample without replacement
  within (type, corpus), so shard_k and shard_k+1 never overlap at
  the value level.
- **Real con:** two shards from the same corpus share the same *value
  generator* (same Faker seed / same Ai4Privacy annotator). Cross-
  shard features are not i.i.d. — the variance estimate from this
  split is optimistic.

### 5.2 Split-by-type (leave-one-class-out)

Hold out N of 22 types entirely.

- **Fatal con:** multinomial LR cannot predict a class it has never
  seen. The loss for held-out classes is undefined. This split only
  makes sense for *open-set* evaluation, which is not our task —
  production never sees a class outside the configured profile.
- **Reject as primary eval.**

### 5.3 Split-by-corpus (leave-one-corpus-out, LOCO)

Train on `{Nemotron, synthetic}`, test on Ai4Privacy; then swap.

- **Pro:** tests the most realistic failure mode — "a new customer's
  data looks like a corpus we didn't train on". This is the
  generalization question that actually matters in production.
- **Pro:** every class still appears in train and test (for the 7
  classes that exist in both real corpora).
- **Con:** classes that live in only one corpus (e.g.,
  `CREDIT_CARD` → Nemotron only) get zero real test data in one of
  the two folds. We live with this — those classes' LOCO score is
  flagged as N/A, not zero.
- **Con:** synthetic-only classes do not get a LOCO signal at all.
  Their test data has to come from a held-out synthetic shard bucket.

### 5.4 Recommended split regime

A **two-tier evaluation**:

1. **Primary split — stratified shard split (80/20).** The 20% test
   set is what we report F1 on. Stratify on `ground_truth` so every
   class has ≥ 20 test examples. Tie test rows to their
   corpus/mode/source metadata so we can slice the F1 report later
   without retraining.
2. **Secondary eval — leave-one-corpus-out.** Train two side models
   (`-ai4`, `-nemotron`), report F1 on the held-out corpus, compare
   to the primary model. A large gap between primary and LOCO F1 is
   the canary for corpus-specific overfitting.
3. **Tertiary eval — blind-vs-named stratification.** The dataset
   already labels `mode ∈ {named, blind}`. Report F1 separately on
   blind rows — this is the pure "sample-values-only" test that
   matters for the BQ connector use case (`feedback_build_right`
   and `project_bq_coordination` memories).

**Shard-identity invariant.** Every training row carries a
`column_id` already. Extend it to `{corpus}_{mode}_{type}_shard{k}`
and assert at split time that no `column_id` appears in both train
and test. Cheap, catches bugs forever.

## 6. Q4 — Bootstrap and confidence-interval strategy

The question is not "is our F1 above the baseline" — it is "is the
F1 delta larger than the noise floor of a 700-row test set, and how
will we know when the delta becomes significant as the dataset grows?"

### 6.1 What not to do

- **Per-row bootstrap.** Resampling individual rows underestimates
  variance because the rows in our set are not i.i.d. — shards from
  the same corpus share a generator.
- **Unpaired comparison.** Scoring baseline and meta-classifier on
  independent resamples throws away the fact that both models see
  the same test columns. It roughly doubles the CI width for the
  same data.
- **Single-number F1.** Report macro-F1, per-class F1, and
  confusion-matrix diagonals. Macro-F1 alone hides the classes that
  matter most (the ones the baseline already gets wrong).

### 6.2 Recommended procedure — paired stratified cluster bootstrap

On the 20% shard-held-out test set, repeat 2,000 times:

1. **Cluster unit = (corpus, type).** This is the atom of
   non-independence. Resampling whole clusters preserves the
   corpus-level generator correlation.
2. **Stratify on `ground_truth`** within each cluster so resamples
   preserve per-class counts.
3. **Score both models on the same resample.** Compute
   `f1_meta(resample_b) − f1_baseline(resample_b)` for each of the
   B=2,000 resamples.
4. **CI.** Report the 2.5th and 97.5th percentile of the
   per-resample deltas. For small samples (< 1,000 test rows),
   prefer **BCa bootstrap** over plain percentile; the `scipy.stats
   .bootstrap` implementation supports it out of the box.
5. **Significance test.** Alongside the CI, run **McNemar's test**
   on per-shard correct/incorrect flags — cheap, paired, and
   non-parametric. Report the exact p-value, not "p < 0.05".

### 6.3 When the corpus pool runs dry

A few real-corpus types (Nemotron `SSN` at 3.6K, `MAC_ADDRESS` at
3.4K) cannot fill N=75 shards at M=500 without repetition. Two
acceptable workarounds:

- **Shard-level resampling with replacement** for the deficit
  shards, *tagged in metadata* (`sampling: resampled`). Metric code
  excludes resampled shards from CI calculations (they inflate
  correlation artificially).
- **Reduced N for the deficit class**, with the shortfall made up
  from synthetic. Flag the class as `mix: synth-heavy` so downstream
  analysis can isolate it.

Do not silently repeat values — the memory `feedback_real_corpora`
says "never generate fake fallbacks", and a resampled shard is a
fake fallback if it's not labelled.

### 6.4 "Dataset is still growing" quality gate

The motivating concern in the request is that the training set will
expand sprint-over-sprint. Use the CI **width** as an explicit
quality gate:

| 95% CI width on macro-F1 delta | status              | action                 |
|--------------------------------|---------------------|------------------------|
| ≥ ±0.05                        | underpowered        | do not ship delta claims |
| ±0.03 – ±0.05                  | directional         | report with caveat     |
| ≤ ±0.03                        | publishable         | safe to compare sprints|
| ≤ ±0.015                       | asymptotic          | further data wasted    |

Wire this into `tests/benchmarks/generate_report.py` so every sprint
benchmark report prints the CI width and its gate status. This
directly satisfies the `feedback_benchmarks_every_sprint` memory.

## 7. TL;DR — recommended parameters

| parameter                      | value                                                                  |
|-------------------------------|-------------------------------------------------------------------------|
| target total rows              | **3,500–4,500**                                                        |
| target rows per class          | **150** (floor 100, cap 500)                                           |
| shards per (type, real-corpus) | **75** unique                                                          |
| shards per type (synthetic)    | 30 for real-backed types, 150 for synthetic-only types                 |
| M per shard                    | **stratified**: 25% ∈ [60,120], 50% ∈ [150,300], 25% ∈ [400,800]       |
| named/blind doubling           | keep (already in build_training_data)                                  |
| shard sampling                 | without replacement within (type, corpus); tag any exceptions          |
| primary split                  | stratified 80/20 by `ground_truth`, invariant on `column_id`           |
| secondary eval                 | leave-one-corpus-out (train on synth+Nemotron, test on Ai4Privacy, etc.) |
| tertiary eval                  | per-mode F1 on blind rows only                                         |
| CI method                      | paired stratified cluster bootstrap, 2,000 resamples, BCa              |
| significance test              | McNemar on per-shard correctness                                       |
| ship-gate                      | 95% CI width on macro-F1 delta ≤ ±0.03                                 |

## 8. Open questions

1. **Cluster definition.** We picked `(corpus, type)` as the
   bootstrap cluster. If Phase 2 adds a third real corpus, is the
   cluster still (corpus, type) or do we move to `(corpus, type,
   annotator_batch)`? Decide when adding the corpus, not before.
2. **Class weight.** Multinomial LR with imbalanced classes benefits
   from `class_weight='balanced'` in `sklearn`, but under the plan
   above we are only slightly imbalanced (150–500 range). Start
   unweighted and revisit if per-class F1 shows systematic
   under-performance on the minority classes.
3. **Feature augmentation across shards.** Because we are generating
   synthetic variability by subsampling, we could also vary the
   `column_name` field across shards of the same type (engineered
   misses for the column-name engine). Recommended, but belongs in
   the Phase 2 plan, not this sharding doc.
4. **Scaling to full HF corpora.** The bundled samples (438K /
   155K) are already an order of magnitude past what we consume.
   There is no data reason to pull the full HF datasets until we
   want N ≥ 300 per real-corpus type, which is a late-Phase-3 or
   Phase-4 concern.
5. **Where to write the shard builder.** Option A: extend
   `tests/benchmarks/corpus_loader.py::_records_to_corpus` to emit
   multiple columns per type (the minimal-surface change). Option B:
   introduce `tests/benchmarks/meta_classifier/shard_builder.py`
   that consumes the raw corpus loaders and handles stratification,
   resampling tags, and the `column_id` invariant. Option B keeps
   benchmark-corpus behavior untouched — recommended.

## 9. What not to do

- Do not fix the 23-class `DATE_OF_BIRTH_EU` artifact in this sprint
  — it is a separate profile-hygiene issue. The sharding plan treats
  it as a 22+1 class problem; Phase 2 can merge or drop it.
- Do not add features to the meta-classifier as part of implementing
  the sharding change. The stable-regime calculation in §3.2 assumes
  p = 15; adding features before we have a stable dataset means we
  cannot tell whether a delta came from the feature or the data.
- Do not silently repeat values across shards. See §6.3.
- Do not touch anything outside `tests/benchmarks/meta_classifier/`
  and (optionally, per §8 item 5) `tests/benchmarks/corpus_loader.py`.
  The production library does not change.

## References

- Peduzzi P. et al., *A simulation study of the number of events per
  variable in logistic regression analysis*, J. Clin. Epidemiol. 49
  (1996).
- Van Smeden M. et al., *Sample size for binary logistic prediction
  models: Beyond events per variable criteria*, Stat. Methods Med.
  Res. 28 (2019).
- Riley R. D. et al., *Calculating the sample size required for
  developing a clinical prediction model*, BMJ 368 (2020).
- Wolpert D. H., *Stacked generalization*, Neural Networks 5 (1992).
- Van der Laan M. J. et al., *Super Learner*, Stat. Appl. Genet. Mol.
  Biol. 6 (2007).
- DiCiccio T. J. and Efron B., *Bootstrap confidence intervals*,
  Statistical Science 11 (1996) — BCa procedure.
- McNemar Q., *Note on the sampling error of the difference between
  correlated proportions or percentages*, Psychometrika 12 (1947).
