# Meta-Classifier Experiment Queue

> **Purpose:** A backlog of training/evaluation experiments to run in **parallel
> sessions** outside the main sprint thread. Each entry is self-contained,
> scoped to a single training run, and produces a measurable result that
> informs whether to promote a new model artifact.
>
> **Workflow:**
> 1. Open a new terminal
> 2. `git worktree add ../data_classifier-experiments experiments/meta_classifier`
> 3. `cd ../data_classifier-experiments && claude`
> 4. Pick the highest-priority unstarted entry below and paste it as the prompt
> 5. When the experiment completes, the session writes its result to
>    `docs/experiments/meta_classifier/runs/<timestamp>-<slug>/` and updates
>    this file's status column
>
> **What "in parallel" means:** these experiments touch only training-side files
> (`tests/benchmarks/meta_classifier/`, `scripts/train_meta_classifier.py`,
> `data_classifier/models/meta_classifier_v*.{pkl,metadata.json}`,
> `tests/benchmarks/corpus_loader.py` loader functions, and `docs/experiments/`).
> They never modify orchestrator code, library API, or production paths.
> Multiple parallel sessions can run simultaneously as long as each is in its
> own worktree.

## Status legend

- 🔴 **blocked** — depends on something else
- 🟡 **queued** — ready to pick up
- 🟢 **in progress** — being worked on
- ✅ **complete** — result captured in `runs/`
- ⏸ **deferred** — paused, see notes

## Phase 2 carryover — open questions from `a0ebe3d`

### Q2 — Resampled-row exclusion impact on bootstrap CI

**Status:** 🟡 queued
**Priority:** P1
**Estimated time:** 30-60 min
**Why it matters:** Phase 2 included ~67% resampled rows (CREDENTIAL/NEGATIVE
pools were too small for 75 unique shards). Session A's research doc
[`sharding_strategy.md` §6.3] said to exclude them from CI calculations.
Phase 2 included them. The current 95% BCa CI width of 0.0577 might be
optimistic. We don't know whether the model still passes the tight ship gate
when resampled rows are excluded.

**Task prompt for parallel session:**
```
Working in /Users/guyguzner/Projects/data_classifier on branch
experiments/meta_classifier (worktree).

Phase 2 of the meta-classifier (commit a0ebe3d) trained a model with 7,770
training rows, of which ~67% are tagged "sampling=resampled" because the
CREDENTIAL/NEGATIVE shard pools were smaller than 75 unique shards.

Session A's research doc docs/research/meta_classifier/sharding_strategy.md §6.3
recommends excluding resampled rows from bootstrap CI calculations because
they inflate inter-shard correlation artificially.

Phase 2 INCLUDED them. You will RE-RUN the bootstrap CI calculation EXCLUDING
resampled rows and report the new CI width. Steps:

1. Read tests/benchmarks/meta_classifier/training_data.jsonl — confirm rows
   carry sampling=resampled metadata
2. Read scripts/train_meta_classifier.py and tests/benchmarks/meta_classifier/
   evaluate.py to find where the bootstrap is computed
3. Re-run the evaluation against the existing pkl
   data_classifier/models/meta_classifier_v1.pkl, but with a filter that
   drops resampled rows from the test set
4. Report (a) new test set size, (b) new BCa 95% CI on macro-F1 delta vs
   live baseline, (c) whether the tight ship gate (delta ≥ +0.02 AND
   CI width ≤ ±0.03) still passes
5. Write the result to docs/experiments/meta_classifier/runs/<timestamp>-q2-
   resampled-exclusion/result.md

Do NOT retrain the model. Do NOT modify orchestrator code. Do NOT touch
data_classifier/__init__.py or anything outside training-side files.
```

**Success criteria:** Either confirms the +0.25 / 0.058 numbers hold under
exclusion (in which case Phase 2's ship verdict stands), or surfaces the
real number (in which case we know how much room we actually have).

### Q3 — LOCO collapse investigation

**Status:** 🟡 queued
**Priority:** P1
**Estimated time:** 1-2 hours
**Why it matters:** Phase 2 reported macro F1 = 0.92 on standard CV but only
0.27-0.36 on leave-one-corpus-out (LOCO) eval. An 0.55 gap is alarming —
it suggests the model has learned per-corpus fingerprints (annotator style,
value length distribution, generator artifacts) rather than universal
entity-type rules. Before relying on the +0.25 number for production
decisions, we need to know whether the LOCO weakness is (a) inherent to
training on a small number of corpora, (b) a feature engineering problem
where one or two features are doing all the corpus-leaking, or (c) a
generator-level i.i.d. violation we can't fix without more sources.

**Task prompt for parallel session:**
```
Working in /Users/guyguzner/Projects/data_classifier on branch
experiments/meta_classifier (worktree).

Phase 2 of the meta-classifier (commit a0ebe3d) reported a 0.55 macro-F1
gap between standard CV (0.92) and leave-one-corpus-out (0.27-0.36). This
is a known weakness flagged in research doc docs/research/meta_classifier/
sharding_strategy.md §5.3 but the magnitude is bigger than the doc
implied.

Investigate which features cause the LOCO collapse. Steps:

1. Read scripts/train_meta_classifier.py and evaluate.py for the LOCO
   computation
2. Run feature ablation: for each feature in the 13 effective dimensions,
   train a model WITHOUT that feature, run LOCO eval, record the LOCO
   F1. Identify the feature(s) whose removal IMPROVES LOCO scores
   (counter-intuitive: a feature is corpus-leaking if dropping it helps
   generalization)
3. Run inverse ablation: train a model with ONLY one feature at a time
   (intercept + 1 feature). Identify which features have the highest
   LOCO F1 on their own — those are the most generalizable
4. Hypothesis to test: heuristic_avg_length is the corpus-leaking
   feature. Coefficient magnitude is 488 (2x runner-up), and average
   value lengths differ across corpora due to annotator conventions
5. Bonus: try training with heuristic_avg_length BINNED (short / medium
   / long instead of continuous) and see if LOCO improves
6. Write findings to docs/experiments/meta_classifier/runs/<timestamp>-q3-
   loco-investigation/result.md

Do NOT retrain a final production model. This is diagnostic work, not
model promotion. Save any candidate models to data_classifier/models/
meta_classifier_v1_q3.pkl etc, NOT replacing v1.
```

**Success criteria:** Concrete identification of which features are
corpus-leaking + a candidate model that closes >50% of the LOCO gap (i.e.,
LOCO F1 ≥ 0.55 vs current 0.27-0.36).

### Q4 — DOB / DOB-EU merge experiment

**Status:** 🟡 queued
**Priority:** P2
**Estimated time:** 30-60 min
**Why it matters:** Phase 2's worst per-class F1 is `DATE_OF_BIRTH = 0.527`
and `DATE_OF_BIRTH_EU = 0.828`. These two labels were intentionally split in
Sprint 6 item 5 (commit `d22d6cb`) for downstream region disambiguation,
but the meta-classifier is showing they're the most confused pair in the
output space. Session A's research doc §9 explicitly flagged this as a
profile-hygiene issue. We want to know whether collapsing the two labels
back into a single `DATE_OF_BIRTH` improves overall macro F1, and by how
much.

**Task prompt for parallel session:**
```
Working in /Users/guyguzner/Projects/data_classifier on branch
experiments/meta_classifier (worktree).

Phase 2 of the meta-classifier (commit a0ebe3d) shows DATE_OF_BIRTH
(F1 = 0.527) and DATE_OF_BIRTH_EU (F1 = 0.828) as the worst-classified
pair on the held-out test set. They were intentionally split in Sprint 6
item 5 (commit d22d6cb) but the meta-classifier shows they confuse each
other.

Run a relabel-and-retrain experiment to see if merging the two classes
improves macro F1.

Steps:

1. Read tests/benchmarks/meta_classifier/training_data.jsonl — count
   DATE_OF_BIRTH and DATE_OF_BIRTH_EU rows
2. Create a relabeled copy: every DATE_OF_BIRTH_EU row gets ground_truth
   rewritten to DATE_OF_BIRTH. Save to /tmp/relabeled_training_data.jsonl
3. Re-run scripts/train_meta_classifier.py against the relabeled file.
   Save the resulting model to data_classifier/models/meta_classifier_
   v1_q4_merged.pkl (NOT replacing v1.pkl)
4. Report:
   - Old per-class F1 for DATE_OF_BIRTH: 0.527
   - Old per-class F1 for DATE_OF_BIRTH_EU: 0.828
   - New combined per-class F1 for DATE_OF_BIRTH (after merge)
   - Old overall macro F1: 0.9185 (Phase 2 number)
   - New overall macro F1 with the merged label
   - Verdict: should the merge be promoted to the live profile?
5. Write the result to docs/experiments/meta_classifier/runs/<timestamp>-q4-
   dob-merge/result.md

Do NOT modify data_classifier/profiles/standard.yaml in this experiment.
This is a measurement-only task. The profile change happens in a separate
sprint item if the merge proves beneficial.
```

**Success criteria:** Concrete delta in macro F1 with the merged label,
plus a clear ship/no-ship recommendation. If the merged label improves
macro F1 by ≥0.01, file a Sprint 7 backlog item to drop DATE_OF_BIRTH_EU
from the profile (reversing Sprint 6 item 5).

## Future experiments — seeded for after Sprint 6 close

### E1 — Hyperparameter sweep on L2 strength

**Status:** 🟡 queued
**Priority:** P3
**Estimated time:** 30 min

Phase 2 picked `C=100.0` as the best L2 strength from a coarse grid
`{0.01, 0.1, 1.0, 10.0, 100.0}`. Run a finer grid `{50, 75, 100, 150, 200,
300, 500}` and compare 5-fold CV scores. Hypothesis: the model is mildly
over-regularized and a slightly weaker L2 (higher C) might add 0.01-0.02
to F1. Save the result to `runs/<ts>-e1-c-sweep/result.md`. If a better C
is found, save the new model to `meta_classifier_v1_e1.pkl` for review.

### E2 — Feature ablation: drop one at a time

**Status:** 🟡 queued
**Priority:** P3
**Estimated time:** 1 hour

Train 13 models, each with one feature removed. Report the per-class F1
delta for each ablation. Identify the 2 most-important and 2
least-important features. Cross-reference with Q3's LOCO ablation results
if both are run. Saves to `runs/<ts>-e2-ablation/result.md`.

### E3 — Class collapse: 4-class meta-classifier

**Status:** 🟡 queued
**Priority:** P3
**Estimated time:** 30-45 min

Train a meta-classifier that predicts only 4 classes (PII / Credential /
Health / Financial / NEGATIVE) instead of the current 24. The training
data already has `category` info on each ColumnInput's profile. Hypothesis:
a 4-class problem is dramatically easier and might give us a stable
baseline classifier even if the 24-class one struggles. Compare macro F1
+ LOCO + per-class. Saves to `runs/<ts>-e3-class-collapse/result.md`.

### E4 — Distribution-invariant features (binning)

**Status:** 🟡 queued (depends on Q3)
**Priority:** P3
**Estimated time:** 1-2 hours

If Q3 confirms `heuristic_avg_length` is the main corpus-leaking feature,
this experiment retrains with that feature **binned** into discrete
buckets (e.g., very-short, short, medium, long, very-long) instead of
continuous. The hypothesis: bucketing reduces the model's ability to
fingerprint corpus-specific distributions while preserving the gross
"long values look like addresses, short values look like names" signal.
Saves to `runs/<ts>-e4-binning/result.md`.

### E5 — Pull SecretBench full vs sample

**Status:** 🟡 queued
**Priority:** P3
**Estimated time:** 1 hour

Phase 2 used `secretbench_sample.json` (1,068 rows). The full SecretBench
has ~4,200 annotated lines per Session B's research doc §5.1. Pull the
full version via `python scripts/download_corpora.py --corpus secretbench
--max-per-type 9999`, rebuild training data, retrain. Hypothesis: 4×
more KV-structured credential rows lifts the meta-classifier's
`secret_scanner_confidence` non-zero rate from 9.5% to ~30%+, which is
where Session B's research said it would become a strong signal. Saves
to `runs/<ts>-e5-secretbench-full/result.md`.

### E6 — XGBoost replacement for LogReg

**Status:** 🟡 queued
**Priority:** P3
**Estimated time:** 1-2 hours

LogReg is the conservative starting point. Try `XGBoostClassifier` (or
`HistGradientBoostingClassifier` if XGBoost isn't in the optional extras)
on the same training data, same features, same train/test split, same
bootstrap CI. Hypothesis: tree models might handle non-linear feature
interactions better, especially the "is this column long enough to be
an address" type discriminations. Saves to `runs/<ts>-e6-xgboost/result.md`.
**Be careful not to overfit** — XGBoost is much higher capacity than
LogReg on a 7K dataset.

### E7 — Pull Nemotron full + Ai4Privacy full

**Status:** 🟡 queued (depends on Q3 ruling LOCO is data-not-feature)
**Priority:** P2

If Q3 concludes the LOCO collapse is a data scarcity problem (not just
feature engineering), this experiment pulls the full HuggingFace versions
of Nemotron (~621K spans) and Ai4Privacy (~1.75M spans), reshards to
N=300 per type, retrains, and re-runs LOCO eval. Hypothesis: more raw
volume per generator narrows the gap by giving each shard more
within-corpus variance. **Big download (~800MB combined).** Saves to
`runs/<ts>-e7-full-corpora/result.md`.

### E8 — Add structural features

**Status:** 🟡 queued
**Priority:** P3
**Estimated time:** 1-2 hours

Phase 2's 15-feature vector ignores `column_id`-derived signals (length
of column name, separator chars, casing, presence of digits in name).
Add 5-10 structural features derived from the column name (when
present), retrain, measure F1 delta. **Note:** these features only help
in named mode, not blind mode — but blind mode is where the meta-
classifier is already winning. This experiment specifically targets
the few named-mode failures we have. Saves to `runs/<ts>-e8-structural/
result.md`.

## Workflow for completed experiments

When a parallel session finishes an experiment:

1. Result file lives at `docs/experiments/meta_classifier/runs/<ts>-<slug>/result.md`
2. Update this file's status column from 🟡 to ✅
3. If a new model is promoted:
   - Save it as `data_classifier/models/meta_classifier_v<N>.pkl` (incrementing version)
   - Cherry-pick the model commit into main when sprint cycle allows
4. If no model is promoted:
   - Note the result and any follow-up experiments in this file
   - Add new entries below `Future experiments` if the result surfaces new questions
