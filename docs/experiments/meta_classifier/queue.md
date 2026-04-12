# Meta-Classifier Experiment Queue

> **Purpose:** A backlog of training/evaluation experiments to run in **parallel
> sessions** outside the main sprint thread. Each entry is self-contained,
> scoped to a single training run, and produces a measurable result that
> informs whether to promote a new model artifact.
>
> **Workflow:**
> 1. Open a new terminal
> 2. `git worktree add ../data_classifier-experiments research/meta-classifier`
> 3. `cd ../data_classifier-experiments && claude`
> 4. Pick the highest-priority unstarted entry below and paste it as the prompt
> 5. When the experiment completes, the session writes its result to
>    `docs/experiments/meta_classifier/runs/<timestamp>-<slug>/` and updates
>    this file's status column

## Research Workflow Contract

Read this before dispatching any experiment. This contract exists so
parallel research sessions can run without blocking sprint development
and without corrupting production state.

### Branch model

All research runs on the long-lived **`research/meta-classifier`** branch
off main. Individual experiments do NOT get their own branches — they
commit directly to the research branch. Multiple parallel sessions each
use their own git worktree pointed at this branch.

The main sprint branch (`sprintN/main`) is always based on `main`, never
on the research branch. They never cross-contaminate.

### File ownership — research sessions MAY write

- `docs/experiments/**` (append-only results; never edit existing files)
- `data_classifier/models/meta_classifier_v*_*.pkl` with a non-`v1`
  suffix (e.g. `meta_classifier_v1_q3.pkl`)
- `data_classifier/models/meta_classifier_v*_*.metadata.json` matching
- `tests/benchmarks/meta_classifier/**`
- `scripts/train_meta_classifier.py` (backward-compatible changes only)
- `tests/benchmarks/corpus_loader.py` (append-only loader functions;
  never edit existing loader functions, only add new ones)

### File ownership — research sessions MUST NOT write

- `data_classifier/orchestrator/**` (including `meta_classifier.py`
  — the shared `extract_features` function lives there and any change
  is a production API change)
- `data_classifier/__init__.py` or anything else in the public API
- `data_classifier/models/meta_classifier_v1.pkl`
  (production artifact — frozen once shipped)
- `data_classifier/models/meta_classifier_v1.metadata.json`
- `data_classifier/profiles/**`, `data_classifier/patterns/**`
- `data_classifier/engines/**`
- Non-experiment tests under `tests/test_*.py`
- `pyproject.toml` (except `[project.optional-dependencies.meta]` for
  new training-time deps)

If an experiment needs to propose a feature engineering change (e.g.
"bin `heuristic_avg_length` into 5 buckets"), it applies the change as
a post-processing step in the training pipeline (not inside
`extract_features`) and writes the finding to `result.md`. A **separate
sprint backlog item** then promotes the change to production code
through normal sprint review.

### Coordination signal

The **status column** in this file is the only lock. A session:

1. Flips its chosen entry to 🟢 **and commits** as its very first
   action — before any other work
2. Does the experiment
3. Writes the result file
4. Flips to ✅ and commits

If two sessions race on step 1, the second one hits a merge conflict
on pull and picks a different entry. No coordination beyond this.

### Promotion to production

Research never auto-promotes. Every experiment ends with:

- A `result.md` under `docs/experiments/meta_classifier/runs/`
- Optionally a candidate pkl with a unique suffix
- A status flip to ✅

When a finding warrants production uptake, a **separate Sprint backlog
item** ("Promote meta-classifier v2 — Q3 feature fix") does the actual
production edit: rename candidate pkl → versioned production path,
update `_DEFAULT_MODEL_RESOURCE` in the orchestrator, run full CI,
merge through normal sprint review.

### Parallelism ceiling

M-series Mac comfortably runs 2-3 simultaneous training jobs. Downloads
and descriptive-stats analyses can run at much higher concurrency.
If an experiment needs the full corpus download (E7), kick it off first
— while it downloads, run ablations on existing training data in
another session.

### Merging research back to main

Findings memos under `docs/experiments/` are merged to main at natural
cadences (sprint end is the default) so project history captures
learnings even when nothing promoted to production. Candidate pkls stay
on the research branch until a promotion sprint item ships them.

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

### Q5 — Feature distribution audit (descriptive stats, no retraining)

**Status:** 🟡 queued
**Priority:** P1
**Estimated time:** 15-30 min
**Complements:** Q3 (pair them — same question, different angle)
**Why it matters:** Q3 diagnoses feature leakage by retraining the model
13+ times and watching LOCO scores move. That's the *model-based* answer
to "which features leak." The complementary *data-based* answer is
simply to compute per-corpus distribution statistics for every feature
and rank them by inter-corpus divergence. If both methods flag the same
feature(s), the diagnosis is triple-confirmed. If they disagree, we
learn something — maybe the model isn't using the feature we think it
is. Bonus: no training required, so this runs to completion in 15 min
while Q3 is still retraining.

**Task prompt for parallel session:**
```
Working in /Users/guyguzner/Projects/data_classifier-experiments on
branch research/meta-classifier (worktree).

Phase 2 of the meta-classifier (commit a0ebe3d on main, merged via
PR #5) trained a logistic regression model with CV macro F1 = 0.916
and LOCO macro F1 = 0.27-0.36 — a 0.55 gap indicating corpus-specific
feature leakage.

Primary suspect is heuristic_avg_length (coefficient magnitude 488,
2x the runner-up). But this is a hypothesis, not a diagnosis.

This experiment is the data-based diagnostic complement to Q3
(model-based feature ablation). It runs descriptive statistics only
— NO model retraining.

Steps:

1. Read tests/benchmarks/meta_classifier/training_data.jsonl — each
   row has `corpus`, `features` (15-dim), `ground_truth`. Load into
   a pandas DataFrame (install pandas/numpy/scipy in the worktree
   venv if needed via pip install pandas scipy).

2. For every feature in the 15-feature vector:
   - Compute per-corpus mean, std, min, max, median
   - Compute the ratio of inter-corpus variance to within-corpus
     variance (F-statistic)
   - For each pair of corpora (e.g. Nemotron vs Ai4Privacy, Nemotron
     vs SecretBench), compute the two-sample Kolmogorov-Smirnov
     statistic and its p-value

3. Rank features by the maximum KS statistic across any pair of
   corpora. Features with max KS > 0.3 are suspects.

4. For each top-5 suspect feature, produce a histogram showing the
   per-corpus distributions overlaid. Save as PNG under
   `docs/experiments/meta_classifier/runs/<ts>-q5-feature-dist/`.
   Use matplotlib. If matplotlib is a pain to install, a text-based
   per-corpus percentile table (10th/25th/50th/75th/90th) is an
   acceptable fallback.

5. For each top-3 suspect feature, propose a binning strategy:
   - Suggested number of bins (3-7)
   - Suggested cut points that collapse the per-corpus peaks
   - A plain-language prediction of what breaks under binning
     ("names get lumped with short addresses") and what's preserved
     ("addresses still get separated from emails by avg_length")

6. Write the result to docs/experiments/meta_classifier/runs/
   <timestamp>-q5-feature-distribution-audit/result.md. The result
   must include:
   - A table: feature × (per-corpus mean, std, max-KS-vs-any-corpus)
   - A ranked list of leaky feature suspects
   - Overlaid histograms for top-5 suspects (or percentile tables)
   - Binning proposals for top-3 suspects
   - A verdict section: which features look leaky and which don't,
     and how this aligns with or contradicts the coefficient-based
     hypothesis (avg_length is 2x runner-up)

7. Update this queue.md: flip Q5 status from 🟡 to ✅

BEFORE starting work, flip Q5 from 🟡 to 🟢 and commit (single commit,
just the status change). This is the coordination lock — if you hit a
merge conflict on pull, someone else is already on it; pick a
different entry.

Do NOT retrain any model. Do NOT touch
data_classifier/orchestrator/**, data_classifier/__init__.py, or any
production path. Do NOT edit existing loader functions in corpus_loader.py.
```

**Success criteria:** Concrete ranking of features by inter-corpus
divergence. If `heuristic_avg_length` is in the top 3 by KS statistic,
the coefficient-based hypothesis is corroborated and E4 (binning) is
the right next experiment. If it isn't, we've just saved someone 2
hours chasing the wrong feature.

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

### E9 — New-corpus diversity expansion (distinct from E7)

**Status:** 🔴 blocked (depends on Q3 ruling "systemic" not "one feature")
**Priority:** P2
**Estimated time:** 1-3 days per new corpus

**How this differs from E7:** E7 pulls *more rows* from corpora we
already have (full Nemotron, full Ai4Privacy, full SecretBench). E9
pulls *new independent sources* entirely.

The distinction matters for LOCO. LOCO's outer loop iterates over
corpora, not over rows. More rows from Nemotron gives the model more
training data within the Nemotron distribution — it doesn't give LOCO
more domains to hold out. The gap from 5 corpora to 10 corpora is what
actually shrinks distribution-shift failure, not 7770 rows to 20000
rows.

**When to run:** Only if Q3 + Q5 conclude the LOCO collapse is
systemic (case C — no single feature drop improves LOCO by more than
~0.05, and no binning strategy recovers more than 50% of the gap).
If Q3 identifies one or two leaky features and a fix closes the gap,
skip E9 entirely — it's expensive and the problem is already solved.

**Candidate sources (ranked by effort vs diversity gain):**

1. **Presidio sample data** — already on the machine (comparator
   venv is set up for Sprint 6 carryover). Has its own labeling
   conventions. ~30 min to wire.
2. **BQ vague column corpus** — synthetic test corpus with generic
   column names flagged as a Sprint 5 carryover. Adds low-signal
   "generic" domain. ~1 hour to build.
3. **StarPII (20K annotated secrets in code, gated access)** — real
   code fragments with inline secrets. Different labeling convention
   from both Ai4Privacy and SecretBench. ~4 hours to integrate if
   access is granted.
4. **Nightfall sample datasets** — PII + credential + negative
   lookalikes. Explicit FP-heavy content. ~4 hours to integrate.
5. **MIMIC-III de-identified clinical notes** — gated. Health-domain
   PII distribution completely unlike anything we have. High
   diversity, high access friction (credentialing required). ~2 weeks
   if gated access is pursued.
6. **Own synthetic corpus with deliberately orthogonal conventions**
   — write a new generator that samples different value-length
   distributions than any existing corpus. ~1 day. Cheap and
   controllable.

**Task prompt for parallel session:**
```
Working in /Users/guyguzner/Projects/data_classifier-experiments on
branch research/meta-classifier (worktree).

PREREQUISITE CHECK: Before running this, verify Q3 and Q5 results
under docs/experiments/meta_classifier/runs/. If either says the
LOCO gap is explained by a single feature that can be binned or
dropped, STOP and skip this experiment — the problem is already
solved and adding corpora is wasted effort.

If both Q3 and Q5 concluded the leak is systemic (no single feature
drop closes >50% of the LOCO gap), proceed.

Steps:

1. Read docs/research/meta_classifier/corpus_diversity.md for the
   existing corpus inventory.

2. Pick the cheapest 2 sources from this list that add a genuinely
   new labeling convention:
   - Presidio sample data (already on machine)
   - Synthetic corpus with orthogonal length distributions (write
     a new generator)

3. For each new source:
   - Add a new loader function to tests/benchmarks/corpus_loader.py
     (append-only — do not touch existing functions)
   - Add a new shard type to shard_builder.py
   - Rebuild training_data.jsonl from scratch with the new sources
     included (save as training_data_v2.jsonl, do NOT overwrite v1)

4. Retrain using scripts/train_meta_classifier.py against the new
   training data. Save as data_classifier/models/meta_classifier_
   v1_e9.pkl.

5. Run LOCO eval on the new model (should now have 7+ corpora in
   the outer loop, up from 5).

6. Report:
   - Old CV / LOCO from v1: 0.916 / 0.27-0.36
   - New CV / LOCO from v1_e9
   - Delta
   - Verdict: did more diversity close the gap?

7. Write the result to docs/experiments/meta_classifier/runs/
   <timestamp>-e9-new-corpus-diversity/result.md

BEFORE starting, flip E9 from 🔴 to 🟢 and commit.

Do NOT retrain v1.pkl. Do NOT touch the orchestrator. Do NOT edit
existing loader functions.
```

**Success criteria:** LOCO macro F1 improves by ≥0.10 with 2 new
corpora. If it does, the problem WAS corpus scarcity and the path
forward is "pull more sources." If it doesn't, feature engineering
(Q3/E4) is the right direction after all.

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
