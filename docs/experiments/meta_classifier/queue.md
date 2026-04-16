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

### Exception: feature-schema experiments

There is one narrow exception to "research does not touch
`data_classifier/orchestrator/meta_classifier.py`": experiments whose
entire purpose is to **widen the feature schema** (add new engine
signals as features) are permitted to modify
`meta_classifier.py`'s `FEATURE_NAMES`, `FEATURE_DIM`, and
`extract_features` function, subject to these constraints:

1. **Additive only.** New features may be appended to the end of
   `FEATURE_NAMES`. Existing feature order and names may not change.
   This preserves `_compute_dropped_indices` compatibility with the
   shipped `meta_classifier_v1.pkl` — the old model's 13 feature
   names remain a subset of the widened `FEATURE_NAMES`, so
   `predict_shadow` still works for v1 by treating new slots as
   "dropped by this model."
2. **Signature-compatible.** `extract_features` may take new keyword
   arguments (defaulted to sensible zeros) but may not remove or
   rename existing parameters.
3. **Production test suite must pass.** After the schema change,
   `pytest tests/test_meta_classifier_*.py` must still be green. The
   existing shadow-inference tests exercise v1.pkl loading and
   prediction — they cannot fail.
4. **Kill switch preserved.** The shadow path must still degrade
   gracefully when the optional dependency is missing (e.g.
   `DATA_CLASSIFIER_DISABLE_ML=1` must still work, `[meta]` extra
   still optional).

E10 (below) is the first experiment to exercise this exception. If it
succeeds, the code change ships as part of the sprint backlog item
that promotes the new model. If it fails, the session reverts the
production edits before finishing.

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

### Merging main into research

Main absorbs production changes continuously — schema widening, gate
architectures, new features, new family taxonomies. The research branch
must periodically pull those changes back in, or experiments start
measuring a schema that no longer exists in production. In the Sprint 9
→ Sprint 11 window this branch fell 117 commits behind main; the E11
ablation was run against a 15-feature layout that main had already
replaced with 46 features, and its "yellow verdict on gating" findings
were an under-estimate of work that had already shipped as Sprint 11
item 11-F. That drift is the failure mode this subsection prevents.

**Trigger.** Once per sprint, after **both**:
1. The sprint-end commit has landed on `origin/main`, and
2. The GitHub Actions CI workflow (`ci.yaml`) is green for that commit.

Both conditions are required. Never sync mid-sprint (main is unstable).
Never sync on yellow/red CI (main is broken or in-flight).

**Operation.** Merge, never rebase. `research/meta-classifier` is a
pushed remote branch and parallel agent worktrees cut from it; a rebase
would force every active worktree to reset. The existing research log
is already braided — Q3/Q5/Q6 sub-experiments landed via merge commits
— so a sprint-boundary `git merge origin/main` fits the shape of the
history.

**Conflict policy.** `docs/experiments/meta_classifier/queue.md` is
research-authoritative: on any conflict, keep `ours`. As a safety check,
**before the merge**, diff `origin/main:queue.md` against
`research:queue.md`; if main has any lines research does not, that is
a workflow bug (main's queue.md should only ever be a snapshot from the
previous sprint-end merge-back) and the sync stops until the drift is
understood. All other files: standard three-way merge. Unexpected
conflicts in `data_classifier/**` mean research has been editing
production code paths, which violates the ownership contract above —
stop and investigate.

**Rollback.** The runbook's first step is tagging
`research/pre-sprintN-sync` as a local-only anchor. If post-sync
validation fails, `git reset --hard` to that tag and file a blocker.

**Detailed runbook.** See
[`docs/process/research_branch_sync_runbook.md`](../../process/research_branch_sync_runbook.md)
for exact commands, pre-flight checks, post-sync validation, the stale
training-data caveat, and the rollback procedure.

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

> **Sprint 11 post-mortem (2026-04-15):** Methodology question remains
> valid, but the motivating CI width (0.0577) is stale. Under the v3
> feature schema (46 features, shipped Sprint 11) the bootstrap CI
> number is different and must be re-measured against the current
> `meta_classifier_v3.pkl` before deciding whether the resampled-row
> exclusion materially changes the ship verdict. Re-snap first, then
> decide if this experiment is worth running.

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

**Status:** ✅ complete — see `runs/20260412-q3-loco-investigation/result.md`
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

**Status:** ⏸ SUPERSEDED — validated by Sprint 11 Phase 10 A/B; DATE_OF_BIRTH_EU being retired in Sprint 12
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

> **Sprint 11 post-mortem (2026-04-15):** Hypothesis validated and in
> the process of shipping. Sprint 11 Phase 10 cross-family A/B analysis
> confirmed the DOB/DOB-EU split is a classification mistake: DATE
> family F1 = 1.000 under v3, and the 150 within-family confusions are
> pure tie-breaking noise with identical confidences on both sides.
> Sprint 12 is retiring `DATE_OF_BIRTH_EU` entirely via the
> `sprint12-retire-date-of-birth-eu-subtype` backlog item (currently
> `status: doing`). Do not run this experiment — the answer is already
> production-bound. Once Sprint 12 delivers and the sync ritual runs,
> the label collapses to `DATE_OF_BIRTH` on its own.

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

**Status:** ✅ complete (see `runs/2026-04-12-q5-feature-distribution-audit/result.md`)
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

**Status:** ⏸ superseded by M1 — spec is stale
**Priority:** P3
**Estimated time:** 30 min

Phase 2 picked `C=100.0` as the best L2 strength from a coarse grid
`{0.01, 0.1, 1.0, 10.0, 100.0}`. Run a finer grid `{50, 75, 100, 150, 200,
300, 500}` and compare 5-fold CV scores. Hypothesis: the model is mildly
over-regularized and a slightly weaker L2 (higher C) might add 0.01-0.02
to F1. Save the result to `runs/<ts>-e1-c-sweep/result.md`. If a better C
is found, save the new model to `meta_classifier_v1_e1.pkl` for review.

> **M1 postscript (2026-04-13):** After M1 replaced StratifiedKFold with
> StratifiedGroupKFold, `best_c` collapsed from 100 → **1.0**. The
> premise of this experiment — "sweep *around* C=100" — is wrong under
> honest CV. If we still want a finer C grid, it should be centered on
> 1.0 (e.g. `{0.1, 0.3, 1.0, 3.0, 10.0}`) and evaluated under
> StratifiedGroupKFold. Leaving paused rather than deleting in case a
> future architectural change (gated classifier, feature-schema fix)
> makes fine-grained C-tuning valuable again.

### E2 — Feature ablation: drop one at a time

**Status:** ⏸ STALE — schema mismatch (premise is 13 features; v3 has 46)
**Priority:** P3
**Estimated time:** 1 hour

Train 13 models, each with one feature removed. Report the per-class F1
delta for each ablation. Identify the 2 most-important and 2
least-important features. Cross-reference with Q3's LOCO ablation results
if both are run. Saves to `runs/<ts>-e2-ablation/result.md`.

> **Sprint 11 post-mortem (2026-04-15):** The "train 13 models" premise
> is obsolete — Sprint 11 widened the feature schema to 46 slots
> (`_BASE_FEATURE_NAMES` + `primary_entity_type` one-hot + Chao-1 +
> dict-word-ratio in `_EXTRA_FEATURE_NAMES`). A 46-way drop-one-at-a-time
> ablation is a different experiment: (a) the per-entity-type one-hot
> slots can't be meaningfully ablated individually — dropping one slot
> just reroutes its samples to the `UNKNOWN` bucket; (b) many v3
> features are near-zero-coefficient on the current model and their
> ablation delta is expected noise. If this experiment is rewritten
> against v3, the useful framing is probably "ablate feature groups"
> (all engine-confidence slots / the one-hot block / the Chao-1 +
> dict-word-ratio extras) rather than individual features. File as a
> new entry with a v3-aware scope instead of resurrecting this one.

### E3 — Class collapse: 4-class meta-classifier

**Status:** ✅ SUPERSEDED — Sprint 11 FAMILY taxonomy (13 families, items 11-H/11-I)
**Priority:** P3
**Estimated time:** 30-45 min

Train a meta-classifier that predicts only 4 classes (PII / Credential /
Health / Financial / NEGATIVE) instead of the current 24. The training
data already has `category` info on each ColumnInput's profile. Hypothesis:
a 4-class problem is dramatically easier and might give us a stable
baseline classifier even if the 24-class one struggles. Compare macro F1
+ LOCO + per-class. Saves to `runs/<ts>-e3-class-collapse/result.md`.

> **Sprint 11 post-mortem (2026-04-15):** Hypothesis validated at a
> different granularity. Sprint 11 shipped the FAMILY taxonomy with
> 13 families (DATE / CREDENTIAL / PII_PERSON / FINANCIAL_ACCOUNT /
> HEALTH / etc. — see `ClassificationFinding.family` on main, items
> 11-H and 11-I). The canonical family accuracy benchmark
> (`tests/benchmarks/family_accuracy_benchmark.py`) is now the new
> quality gate with `family_macro_f1 = 0.9286` and `cross_family_rate
> = 5.85%` (from MEMORY `project_sprint11_complete`). The 4-class
> collapse proposed here would be strictly coarser than the 13-family
> taxonomy and throw away useful within-super-category structure —
> Sprint 11 already found the right granularity. Do not run.

### E4 — Distribution-invariant features (binning)

**Status:** ⏸ EFFECTIVELY DEAD — problem solved differently in Sprint 9-11
**Priority:** P3
**Estimated time:** 1-2 hours

If Q3 confirms `heuristic_avg_length` is the main corpus-leaking feature,
this experiment retrains with that feature **binned** into discrete
buckets (e.g., very-short, short, medium, long, very-long) instead of
continuous. The hypothesis: bucketing reduces the model's ability to
fingerprint corpus-specific distributions while preserving the gross
"long values look like addresses, short values look like names" signal.
Saves to `runs/<ts>-e4-binning/result.md`.

> **Sprint 11 post-mortem (2026-04-15):** Q3 did confirm the leak
> (`heuristic_avg_length` coefficient was 2x runner-up pre-M1), but
> the distributional-shortcut problem was addressed through different
> mechanisms: (a) Gretel-EN ingest in Sprint 9 reduced the
> `heuristic_avg_length` coefficient 252→131 (48% drop) by adding a
> mixed-label corpus that breaks the label-corpus purity pathology;
> (b) Sprint 11 shipped Chao-1 bias-corrected cardinality (item 11-E,
> commit `987194c`) and dictionary-word-ratio (item 11-D, commit
> `d3d29d8`) as *additive* distribution-invariant features rather
> than a binning transformation on `heuristic_avg_length`. Binning
> per se remains untested, but it's now a retrospective
> "would-X-have-been-better-than-what-shipped" question, not a
> forward research direction. Not load-bearing for any current
> thread. Do not run unless a specific reason emerges to compare
> binning against the additive-features approach.

### E5 — Pull SecretBench full vs sample

**Status:** 🟡 queued — confirmed live post Sprint 11
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

> **Sprint 11 post-mortem (2026-04-15):** Still live. Sprint 10's
> secret-dict harvest (88→178 patterns from Kingfisher/gitleaks/Nosey
> Parker) was orthogonal — that was about the pattern library (the
> *what* the scanner detects), not the corpus volume (the *where*
> the meta-classifier measures scanner agreement). The hypothesis
> "4× more KV-structured credential rows lifts `secret_scanner_confidence`
> non-zero rate to ~30%+" is unchanged by Sprint 11 and can run
> against the v3 feature schema as-is. Low priority (P3) because the
> v3 classifier is already passing the canonical family benchmark —
> this is incremental signal improvement, not a gap fix.

### E6 — XGBoost replacement for LogReg

**Status:** ⏸ deferred — promoted to Sprint 10 sprint item
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

> **Sprint 10 cross-ref (2026-04-13):** This experiment is the research-
> branch twin of the Sprint 10 backlog item
> `meta-classifier-model-ablation-logreg-vs-xgboost-vs-lightgbm-on-honest-loco-metric`.
> The sprint item's scope (honest LOCO metric + tree-root inspection as
> a diagnostic for the shortcut-feature hypothesis) is strictly wider
> than E6's original "try XGBoost" framing. Run as the sprint item, not
> here — unless a research session wants to do a quick diagnostic pass
> ahead of the sprint start. If it runs here, the result still goes
> under `runs/<ts>-e6-xgboost/` and the sprint item becomes a
> promotion step rather than a discovery step.

### E7 — Pull Nemotron full + Ai4Privacy full

**Status:** ✅ obsolete — Ai4Privacy retired, Gretel-EN replaced that volume
**Priority:** P2

If Q3 concludes the LOCO collapse is a data scarcity problem (not just
feature engineering), this experiment pulls the full HuggingFace versions
of Nemotron (~621K spans) and Ai4Privacy (~1.75M spans), reshards to
N=300 per type, retrains, and re-runs LOCO eval. Hypothesis: more raw
volume per generator narrows the gap by giving each shard more
within-corpus variance. **Big download (~800MB combined).** Saves to
`runs/<ts>-e7-full-corpora/result.md`.

> **Sprint 9 obsolescence note (2026-04-13):** Ai4Privacy was retired in
> Sprint 9 for a non-OSI license (`project_sprint9_complete` memory +
> `docs/process/LICENSE_AUDIT.md`). Sprint 9 simultaneously ingested
> Gretel-EN (~60k mixed-label rows), which replaced the Ai4Privacy volume
> with a label-mixed source that actively disrupts the
> `heuristic_avg_length → corpus` shortcut (coefficient 252 → 131). The
> "pull more Ai4Privacy rows" half of E7 is dead. The "pull more Nemotron
> rows" half is still technically runnable, but Q3/Q5/Q6/M1 established
> that LOCO collapse is structural (label-purity + shortcut), not
> within-corpus data-scarcity — so more Nemotron rows would not move
> LOCO materially. Closing.

### E8 — Add structural features

**Status:** 🟡 queued — confirmed live post Sprint 11; targets a real gap
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

> **Sprint 11 post-mortem (2026-04-15):** Still live, unchanged by the
> v3 rebuild. `column_name_engine` exists and contributes a feature to
> v3, but it provides *entity-match* confidence via the column name,
> not *structural properties* of the name itself. The v3
> `_EXTRA_FEATURE_NAMES` tuple (Chao-1, dictionary-word-ratio) is
> content-based, not name-structural. The column-name structural
> features proposed here (length of name, separator chars, casing,
> digit presence) target a gap that production has not addressed.
> One schema-compatibility note: this experiment qualifies for the
> feature-schema exception, so the additive column-name-structural
> features would be appended to `_EXTRA_FEATURE_NAMES` under an
> incremented `FEATURE_SCHEMA_VERSION` per the contract.

### E9 — New-corpus diversity expansion (distinct from E7)

**Status:** ✅ de facto run in Sprint 9 (Gretel-EN ingest) — partial win
**Priority:** P2
**Estimated time:** 1-3 days per new corpus

> **Sprint 9 outcome (2026-04-13):** The "add a new independent corpus"
> half of E9 was executed in Sprint 9 via the Gretel-EN ingest
> (`tests/benchmarks/corpus_loader.py::load_gretel_en`, commit
> `e49e1d8`). Gretel-EN is a *mixed-label* source (PII + health +
> credential in the same documents), which is even better than
> "single-label new corpus" for breaking the label-corpus purity
> pathology Q5 identified.
>
> **What we learned:** Gretel-EN alone reduced the
> `heuristic_avg_length` coefficient from 252 to **131** (a 48%
> reduction) and lifted the honest tertiary blind delta to
> **+0.2432** (from E10's +0.191 under the old training corpus).
> LOCO mean moved to **~0.17** under M1's StratifiedGroupKFold — still
> low, but now an *honest* number rather than the inflated 0.27-0.36
> range the pre-M1 LOCO harness was reporting.
>
> **The implication for E9's hypothesis:** "more corpus diversity
> closes the LOCO gap" was only half right. Gretel-EN disrupted the
> shortcut partially but did not eliminate it. The conclusion the
> learning memo lands on is that data-level fixes + metric-level
> fixes are **complementary but neither is sufficient**; the
> structural cure is architectural (gated classifier with a shape-
> first stage 1). E9's second half — "pull 2-5 more independent
> sources beyond Gretel" — is still open as a follow-on but the
> priority has dropped because the architectural direction is the
> higher-leverage next move.
>
> Closing E9 as partially satisfied. If a future session wants to
> chase the "more corpora" direction, file a fresh entry
> (e.g. `E11 — third independent corpus after Gretel`) rather than
> reopening this one.

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

### E10 — Add GLiNER features to the meta-classifier

**Status:** ✅ complete (see `runs/20260412-230000-e10-gliner-features/result.md`) — **Outcome B′** — do NOT promote `v1_e10.pkl`
**Priority:** P0 — the single biggest unanswered question about the
meta-classifier's production value
**Estimated time:** 3-4 hours wall clock (mostly unattended GLiNER
inference + retraining)
**Exercises the "feature-schema experiment" contract exception**
(see above)

> **Sprint 9 verdict (2026-04-13):** E10 ran in Session C on
> `research/e10-gliner-features` and landed a full result memo at
> `runs/20260412-230000-e10-gliner-features/result.md`. Headline:
> GLiNER features produced **modest in-distribution gains**
> (+0.0104 primary F1, +0.0162 tertiary blind F1) but **regressed
> LOCO on ai4privacy by -0.077** and narrowed the honest tertiary
> blind delta from +0.2574 (4-engine framing) to **+0.1907
> (5-engine framing)** — a meaningful re-framing drop rather than a
> genuine performance change. The BCa CI excludes zero and McNemar
> p ≈ 0 on both primary and tertiary, so the meta-classifier still
> beats the honest 5-engine baseline at statistical significance,
> but the LOCO regression and class-level re-shuffling make
> v1_e10 a weaker-than-Phase-2 case. **Recommendation: do NOT
> auto-promote v1_e10.pkl.** Pursue E4 (bin `heuristic_avg_length`)
> and the structural fixes (M1 CV methodology, Q6 class-purity
> split, gated architecture) before another promotion attempt.
>
> **How E10's outcome updated the honest number:** the Sprint 6
> "+0.257 blind delta" was measured against a 4-engine live baseline
> (GLiNER disabled in `evaluate.py`). E10's 5-engine re-measurement
> moved the honest number to **+0.191** — a pure framing correction,
> not a model regression. That's the E10 contribution to the
> "Sprint 6 → honest baseline" narrative in the Sprint 9 learning
> memo. The current (post-M1 + post-Gretel) honest tertiary blind
> delta is **+0.2432**, cited everywhere.

**Why it matters:** Phase 2 deliberately excluded GLiNER2 from the
meta-classifier's feature set for scope-discipline reasons — the
non-ML story had to work first. Both
`tests/benchmarks/meta_classifier/build_training_data.py:29` and
`tests/benchmarks/meta_classifier/evaluate.py:49` set
`DATA_CLASSIFIER_DISABLE_ML=1` at the module entrypoint. The
consequence: the shipped meta-classifier has no access to GLiNER's
predictions, AND the "+0.25 F1 delta over live baseline" framing is
measured against a **4-engine baseline**, not the real 5-engine
production pipeline (which has blind Nemotron macro F1 = 0.872 with
GLiNER enabled).

This experiment answers the deferred question: does the
meta-classifier have any production value if it can see GLiNER?
There are three plausible outcomes:

- **(E10-A) GLiNER closes LOCO massively.** Adding GLiNER features
  gives the meta-classifier a corpus-invariant signal (pretrained
  transformer) that the heuristic engines lack. LOCO jumps to 0.7+,
  held-out stays ~0.92. This would make the meta-classifier a real
  production improvement against the honest 5-engine baseline.
- **(E10-B) GLiNER helps but is not enough.** LOCO improves to 0.5
  but not 0.7. The meta-classifier is mostly a GLiNER parrot with
  some additional arbitration value. Narrower production win, if
  any.
- **(E10-C) GLiNER doesn't help.** LOCO stays at 0.27-0.36 even
  with GLiNER features. This would mean the meta-classifier can't
  extract additional value from GLiNER's output beyond what the
  live orchestrator already does. Meta-classifier should probably
  be abandoned.

**Prescribed feature set (pin these, do not design-by-trial):**

Append exactly five features after the existing 15 in
`FEATURE_NAMES` (not replacing — appending):

```
"gliner_top_confidence",        # float [0,1]: max confidence of GLiNER findings
"gliner_top_entity_is_pii",     # bool: is the top GLiNER entity in the PII category
"gliner_agrees_with_regex",     # bool: does top GLiNER entity == top regex entity
"gliner_agrees_with_column",    # bool: does top GLiNER entity == top column_name entity
"gliner_confidence_gap",        # float [0,1]: top - second-best GLiNER confidence
```

Five features keeps the schema at 20 total (up from 15), well within
the Peduzzi EPV budget for 7770 rows × 24 classes. A richer 24-class
probability vector would widen the schema too aggressively for this
dataset size — don't do it.

**Task prompt for parallel session:**
```
You are Session C (E10) of a parallel research investigation into
the data_classifier meta-classifier. You are in worktree
../data_classifier-e10 on branch research/e10-gliner-features (off
research/meta-classifier off main).

CONTEXT

The meta-classifier shipped in Sprint 6 (shadow-only) was trained
without any GLiNER features. Both build_training_data.py and
evaluate.py set DATA_CLASSIFIER_DISABLE_ML=1 at the module
entrypoint. This was a scope-discipline decision for Phase 1/2 but
it means:
1. The training data never saw GLiNER findings
2. The "+0.25 F1 delta over live baseline" ship claim was measured
   against a 4-engine baseline, not the real 5-engine production
   pipeline
3. The meta-classifier has no access to what is empirically the
   highest-signal PII detector we ship (GLiNER blind macro F1 =
   0.872 on Nemotron, 0.667 on Ai4Privacy)

Your job is to widen the feature schema to include five GLiNER-
derived features, rebuild the training data with GLiNER enabled,
retrain, and run the HONEST evaluation against a 5-engine baseline.

READ FIRST

- docs/experiments/meta_classifier/queue.md — the "Research Workflow
  Contract" section, especially the "Exception: feature-schema
  experiments" carve-out. You are the first experiment to exercise
  this exception, so read the constraints carefully.
- docs/experiments/meta_classifier/queue.md — the full E10 entry
  below for the prescribed feature set and success criteria.
- data_classifier/orchestrator/meta_classifier.py — understand
  FEATURE_NAMES, FEATURE_DIM, extract_features, _compute_dropped_
  indices. You will modify FEATURE_NAMES, FEATURE_DIM, and
  extract_features. Do NOT modify predict_shadow or _ensure_loaded.
- tests/benchmarks/meta_classifier/extract_features.py — the
  offline training-side extract_features wrapper. You will modify
  it to take GLiNER findings as input alongside the non-ML findings.
- tests/benchmarks/meta_classifier/build_training_data.py — has
  DATA_CLASSIFIER_DISABLE_ML=1 at line 29. You will remove this
  and update the feature extraction call to pass GLiNER findings.
- tests/benchmarks/meta_classifier/evaluate.py — has
  DATA_CLASSIFIER_DISABLE_ML=1 at line 49. You will remove this so
  the live baseline is the real 5-engine orchestrator.
- data_classifier/models/meta_classifier_v1.metadata.json — for
  context on the current 13-feature schema and the F1 numbers the
  new model must beat.

COORDINATION

Before starting real work, flip E10 status in queue.md from 🟡 to
🟢 and commit (single commit, just the status flip).

WORK

1. VERIFY GLINER LOADS BEFORE YOU DO ANYTHING ELSE. In an isolated
   python shell, try:
      from data_classifier.engines.gliner_engine import GLiNEREngine
      engine = GLiNEREngine()
      engine.startup()
   If this fails (missing ONNX model, missing onnxruntime, missing
   HF_TOKEN, etc.), STOP and write a short result.md explaining the
   blocker. Do NOT proceed to step 2 unless GLiNER loads cleanly.

2. Widen the feature schema in
   data_classifier/orchestrator/meta_classifier.py:
   - Append these five names to FEATURE_NAMES (after the existing
     15, in this exact order):
       "gliner_top_confidence",
       "gliner_top_entity_is_pii",
       "gliner_agrees_with_regex",
       "gliner_agrees_with_column",
       "gliner_confidence_gap",
   - Update FEATURE_DIM from 15 to 20
   - Update extract_features to accept gliner_findings as a new
     optional parameter (default None). When None, the five GLiNER
     features default to zero — this keeps backward compatibility
     with the Phase 3 shadow inference path that currently calls
     extract_features without GLiNER input.

3. Update the training-side wrapper in
   tests/benchmarks/meta_classifier/extract_features.py to run
   GLiNER in addition to the four non-ML engines and pass its
   findings into the widened extract_features call.

4. Update build_training_data.py: REMOVE the
   os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1") line so
   GLiNER runs. Save the resulting training data to a new file:
   tests/benchmarks/meta_classifier/training_data_e10.jsonl
   (do NOT overwrite training_data.jsonl — preserve v1's data).

5. Run the training data rebuild. This takes ~30 minutes of GLiNER
   inference. You can walk away.

6. Verify existing shadow-inference tests still pass with the
   widened schema:
      pytest tests/test_meta_classifier_*.py -v
   All 60+ tests must be green. If any fail, diagnose and fix BEFORE
   proceeding. The schema-widening must be backward-compatible with
   v1.pkl loading (predict_shadow must still work on the existing
   model).

7. Retrain via scripts/train_meta_classifier.py pointing at the new
   training_data_e10.jsonl file. Save the resulting model to
   data_classifier/models/meta_classifier_v1_e10.pkl (NOT replacing
   v1.pkl). The metadata sidecar goes alongside.

8. Update evaluate.py: REMOVE the DATA_CLASSIFIER_DISABLE_ML=1
   line so the live baseline is the real 5-engine orchestrator.

9. Run evaluation on the new model against the honest 5-engine
   baseline. Compute:
   - New CV macro F1 (5-fold stratified, same as v1)
   - New held-out test macro F1
   - New BCa 95% CI on the delta
   - New LOCO macro F1 (leave-one-corpus-out)
   - Per-class F1 breakdown

10. Write the result to docs/experiments/meta_classifier/runs/
    <timestamp>-e10-gliner-features/result.md with:
    - Old (v1) vs new (v1_e10) CV macro F1
    - Old held-out vs new held-out
    - Old LOCO vs new LOCO — the money number
    - Per-class F1 changes — which classes benefited most
    - Feature importance ranking of the 5 new GLiNER features
    - Verdict: A / B / C (see the three outcomes in queue.md E10
      entry)
    - If A: recommendation to promote v1_e10 to production as v2
      via a Sprint 7 backlog item
    - If B: narrower recommendation, suggest further experiments
    - If C: recommend abandoning the meta-classifier direction

11. Flip E10 status in queue.md from 🟢 to ✅ and commit.

CONSTRAINTS (from the "feature-schema experiments" exception)

- Additive only. Do not reorder or rename existing features in
  FEATURE_NAMES.
- extract_features signature must stay backward compatible. New
  parameter must have a default that preserves current behavior.
- All tests in tests/test_meta_classifier_*.py must pass after the
  schema change. Do NOT modify any test to make it pass — if a
  test fails, fix the implementation.
- The DATA_CLASSIFIER_DISABLE_ML kill switch must still work. If
  someone sets it, the build should still complete (with GLiNER
  features all zero) — don't add a hard dependency on GLiNER being
  available.
- Do NOT overwrite meta_classifier_v1.pkl or training_data.jsonl.
  Both are production artifacts frozen in place.
- Do NOT touch anything else in data_classifier/engines/** or
  data_classifier/profiles/** or patterns/**.

IF THINGS GO WRONG

- If tests fail after the schema change and you can't fix them in
  30 minutes, revert the production file edits and write a result
  memo explaining the blocker.
- If GLiNER training data rebuild fails part-way (OOM, crash),
  resume from the last saved partial output or restart cleanly —
  do not corrupt the existing training_data.jsonl.
- If the LOCO number is worse than v1 (0.27-0.36), still write a
  full result memo. A negative result is a deliverable.

TIME BUDGET

Target: 3-4 hours wall clock. Most of that is GLiNER inference
during training data rebuild. If you're past 6 hours without having
finished step 10, stop and write a partial result memo.
```

**Success criteria:** A definitive answer to "does GLiNER as a
feature change the meta-classifier's LOCO story?" — positive or
negative. If outcome A (LOCO closes substantially) a Sprint 7
backlog item promotes v1_e10 to production. If outcome C
(GLiNER doesn't help) the meta-classifier direction is likely done.

### E11 — Gated architecture — tier-1 pattern-hit routing × model class ablation

**Status:** ✅ complete (see `runs/20260414-e11-gated-tier1-ablation/result.md`) — **Yellow** verdict: gate+LR beats flat LR by +0.067 CV / +0.035 LOCO; gate+HGB is strictly worse than flat LR on both metrics
**Priority:** P0 — answers whether the architectural axis has more leverage than the feature-engineering axis on the gated-classifier direction (learning memo §5)
**Estimated time:** 4-6 research hours (~30 min gate preliminary + ~1 hour per model training + 1 hour writeup)
**Contract note:** does NOT exercise the feature-schema exception — no changes to `orchestrator/meta_classifier.py` FEATURE_NAMES or `extract_features`. Uses the existing 15-feature schema unchanged.

**Why it matters:** Q6 (inverted stage 1, PII-only classifier) verdict was Q6-C: LOCO improved by only +0.016 after filtering CREDENTIAL+NEGATIVE rows from training. That result ruled out class-level filtering as a fix — but it did NOT rule out **architectural gating**. The difference: Q6 treated regex/secret-scanner signals as *features blended into a 13-dim weighted sum*; a real tier-1 gate uses those same signals as a *routing decision* that splits the problem into separable sub-problems before any learned model runs.

This experiment tests whether the gated direction is worth the Sprint 10+ architectural investment implied by the learning memo §5 and the filed Sprint 10 item `gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation`. Positive result → architectural direction has leverage, worth building out. Negative result → stick with the feature-engineering axis (cardinality bias fix, dictionary-word features, binning `heuristic_avg_length`).

**Feature schema interpretation (no changes):**

Index 14 (`primary_is_credential`, boolean) is already computed by the existing 15-feature extractor. Combined with indices 1 (`regex_confidence`), 4 (`secret_scanner_confidence`), 8 (`regex_match_ratio`), and 14, the tier-1 gate can be built *entirely from existing features with zero schema changes*. This is what Q6 missed — the signals were already in the feature vector, just used wrong.

**Gate rule (tier 1 only for this experiment):**

```python
def route_to_credential_stage(features):
    primary_is_credential = features[14] > 0.5
    regex_conf              = features[1]
    secret_scanner_conf     = features[4]
    regex_match_ratio       = features[8]

    # Route if primary engine claimed credential with high confidence and match density
    if primary_is_credential and regex_conf >= 0.85 and regex_match_ratio >= 0.30:
        return True
    # OR secret scanner alone flagged it strongly
    if secret_scanner_conf >= 0.50:
        return True
    return False
```

Tier 2 (shape-based OPAQUE_SECRET residual catcher) is **deferred** to a follow-up — this experiment tests whether tier 1 alone is sufficient.

**2×2 comparison:**

| Model | Tier-1 gate | Stage 2 classifier |
|---|---|---|
| **A** (flat baseline) | ❌ | LogReg on all 15 features, 24 classes |
| **B** (flat tree) | ❌ | HistGradientBoostingClassifier on all 15 features, 24 classes |
| **C** (gated + LR)   | ✅ | LogReg on PII-stage rows with `stage_2_features` (13 features, drops credential-related) |
| **D** (gated + HGB)  | ✅ | HGB on PII-stage rows with `stage_2_features` (13 features) |

`stage_2_features` excludes indices 4 (`secret_scanner_confidence`) and 14 (`primary_is_credential`) — the stage-2 classifier never sees credential rows, so these features would be near-constant zero and shouldn't inflate the feature vector.

**Training data:** `tests/benchmarks/meta_classifier/training_data.jsonl` as-is (Phase 2 / pre-Gretel-EN, 7770 rows, 15 features). **Caveat explicitly logged:** this is NOT the post-Sprint-9 training corpus — it's the pre-Gretel version that the v1 model was originally trained on. The experiment measures architecture-vs-feature-engineering **slope on the old data**; if slope is positive, we can rebuild on post-Gretel data for confirmation. If slope is negative/flat, the architectural direction probably isn't worth pursuing regardless of data freshness.

**Eval harness:**
- 5-fold **StratifiedGroupKFold** (M1 methodology) with `groups = [row.corpus for row in rows]`
- Held-out 20% test slice with the shard-twin-leak caveat (primary_split's known limitation; acceptable as a relative metric across A/B/C/D)
- Per-class F1 breakdown
- LOCO (leave-one-corpus-out) for each of the 4 models
- Tree root-split feature for B and D (diagnostic: if root is `heuristic_avg_length`, the shortcut survived)

**Success criteria:**
- A/B comparison tells us "does the tree help at all on the flat baseline?"
- A/C comparison tells us "does gating alone help, holding model class fixed?"
- A/D comparison tells us "does the whole stack beat the flat LR?"
- **Green light for Sprint 10+ gated-architecture investment** if A/D LOCO delta ≥ +0.05 macro F1 with CI excluding zero
- **Red light (stick with feature engineering)** if A/D LOCO delta is within ±0.02

**Deliverable:** `docs/experiments/meta_classifier/runs/<ts>-e11-gated-tier1-ablation/result.md` with the 2×2 table, per-class breakdown, tree root-split diagnostic, gate precision/recall on training data, and a verdict mapping.

### E12 — Production-shape validation corpora survey (BQ public datasets)

**Status:** ✅ complete (2026-04-16, see `dataset_landscape.md` §Tier 7) — 10 candidates characterized across 4 shape classes; 3 🟢 staging picks (SO users / austin_311 / crypto_ethereum.logs); surprise finding: queue-shortlist was wrong about Austin/NYC/Chicago "description" fields being freeform (they're category enums); GH commits is only BQ source with TRUE_LOG density; $0.40 BQ cost against $5 budget
**Priority:** P1 — validates the heterogeneous-column path in the gated architecture design and fills a corpus gap that synthetic/crowdsourced datasets cannot close
**Estimated time:** ~30-45 min subagent survey + ~15 min review
**Contract note:** append-only to `docs/experiments/meta_classifier/dataset_landscape.md` (research-owned file) — no writes to `data_classifier/**` or main-owned files

**Why it matters:**

Every training/eval corpus we currently use (PII-43k, Gretel-EN, Gretel-finance, openpii-1m, Nemotron, gitleaks/secretbench/detect_secrets) is either synthetic or crowdsourced. None represent production-shape tables with log-shaped columns or mixed-content freeform fields. BigQuery — the only consumer of this library — has customer tables that include exactly these shapes (audit logs, application message fields, complaint-description fields, JSON columns).

The gated architecture backlog item (`gated-meta-classifier-architecture-*-q8-continuation`) designs `HeterogeneousColumnFinding` output for log-shaped columns and a stage-1 gate that routes `HOMOGENEOUS_CREDENTIAL` / `HOMOGENEOUS_PII` / `HETEROGENEOUS`. That design has **no validation data** today. This survey closes that gap by characterizing BQ public datasets against those three shape categories.

Companion to the `cd3a5cc` landscape survey (2026-04-13) which catalogued **labeled training corpora**. This survey catalogues **production-shape validation data** — orthogonal axis.

**Scope:**

1. Enumerate `bigquery-public-data` datasets with log-shaped or mixed-content columns
2. Candidate shortlist (starting points — subagent may add/drop based on discovery):
   - Mixed-content freeform: `austin_311.311_service_requests`, `new_york_311`, `chicago_crime.crime`
   - User-generated text: `stackoverflow.posts_questions`, `github_repos.commits`, `hacker_news.comments`
   - Structured baseline (for contrast): `usa_names.usa_1910_current`, `google_analytics_sample`
3. Per candidate:
   - Schema (column names, types, nullability)
   - Row count and byte-length distribution per text column
   - 100-row sample (values redacted/truncated in memo if PII-dense)
   - License review (BQ public datasets vary: Stack Exchange CC-BY-SA, GitHub per-repo, Austin 311 public domain)
   - Shape classification: `TRUE_LOG` (key=value/structured events) / `MIXED_CONTENT_FREEFORM` (NL with embedded entities) / `JSON_TYPED` / `HOMOGENEOUS_STRUCTURED` (for contrast)
4. Staging recommendation: top 2-3 for actual corpus pull (separate follow-up entry)

**Methodology:**

- General-purpose research subagent with `bq` CLI access
- Billing project: `dag-bigquery-dev` (user's gcloud default)
- Query budget: < $5 (schema + 100-row samples across ~10 candidates)
- Follows the 2026-04-13 survey subagent pattern (~30-45 min wall, ~60k tokens)

**Success criteria:**

- ≥ 5 candidates characterized across ≥ 3 shape classes
- License risk flagged per candidate (green/yellow/red)
- Clear "stage this / skip this" recommendation
- Explicit map: which candidate validates which gated-architecture stage (stage-1 gate shape accuracy / stage-2c heterogeneous NER / stage-2a+b homogeneous baseline)

**Deliverable:**

- New section "Tier 7 — Production-shape validation (BQ public)" appended to `docs/experiments/meta_classifier/dataset_landscape.md`
- Single commit on `research/meta-classifier`
- Status flip to ✅ when survey completes

**Out of scope:**

- Actual corpus staging (downloading samples into `corpora/`) — separate follow-up entry
- Private BQ datasets (customer-owned, not applicable to public survey)
- Running the gated architecture on any of these datasets — that's a training/eval experiment downstream of this one

### E12b — Real-PII free-text BQ survey (follow-up to E12 with reframe)

**Status:** ✅ complete (2026-04-16, see `dataset_landscape.md` §Tier 7b) — 6 candidates characterized + 5 dropped; 4 🟢 staging picks (CFPB narratives HIGH-redacted / FEC 195M donors HIGH / NPPES 9M providers HIGH / IRS 990 1.96M orgs HIGH); reproducible finding that every surveyed municipal incident dataset is enum-shaped or address-scrubbed (Austin 311 + Chicago crime + SFPD + Austin crime + SFFD + London Fire Brigade + NY MV collisions — 7/7); $0.20 BQ cost against $2 budget
**Priority:** P1 — the reframed version of the question E12 answered. E12 focused on the gated-architecture shape taxonomy (TRUE_LOG / HETEROGENEOUS / HOMOGENEOUS). User reframe: what matters more is real BQ tables with **real embedded PII** in free-text columns, because that's the actual production scenario — a BQ customer loads a messy table with a `complaint_narrative` / `incident_description` / `bio` field and the library has to get it right.
**Estimated time:** ~30-45 min subagent survey + ~15 min review
**Contract note:** append-only to `docs/experiments/meta_classifier/dataset_landscape.md` (research-owned file) — no writes to `data_classifier/**`

**Why it matters:**

The E12 memo (Tier 7) optimized for the gated-architecture shape taxonomy and identified top picks accordingly (SO users for 3-outcome coverage, austin_311 for clean address, crypto_ethereum for structured negative control). Under the reframed question — "what real BQ data looks like production tables with free-text PII columns?" — the priority order shifts:

- Synthetic datasets (fhir_synthea) drop in priority because they lack real PII.
- Customer-voice narrative columns rise in priority because they're the closest open-data analogue of "actual BQ customer data the library will encounter."
- Public-domain datasets of real named individuals (FEC, NPPES, IRS 990) are uniquely valuable — they provide **real** PII-at-scale that neither synthetic generators nor training corpora can match.

This survey fills that gap. Tier 7b covers the 5-7 highest-signal "real PII in real text" candidates.

**Scope:**

Candidate shortlist (subagent may add/drop based on discovery):

1. **`cfpb_complaints.consumer_complaint_narrative`** — consumer financial complaints. Free-text customer voice with embedded account IDs, dates, employee names, company interactions. Public domain (CFPB federal agency). Probably #1 candidate for this framing.
2. **`fec.individual_contributions`** — campaign donors: name + address + employer + occupation + freeform memo fields. Legally public.
3. **`nppes.npi_raw`** — National Provider Identifier directory: names + addresses + phones + specialties. Legally public, ~7M real providers.
4. **`irs_990`** — nonprofit tax filings: org names + officer names + compensation + addresses + mission text. Legally public.
5. **Emergency/incident narratives:**
   - `san_francisco_sfpd_incidents` (SF police)
   - `san_francisco_sffd_service_calls` (SF fire)
   - `london_fire_brigade`
   - `new_york_mv_collisions`
   - `austin_crime` / `austin_incidents` (not surveyed in E12 — austin_311 was, and was enum-shaped; austin_crime may have narrative content)

Per candidate:
- Schema (column names, types, nullability)
- Row count + byte-length stats per interesting text column
- 100-row sample for shape inspection (do NOT transcribe raw PII values — characterize shape and entity density only)
- License review (most are public-domain federal/municipal but confirm per dataset)
- **Entity density estimate** per entity type: PERSON, LOCATION, EMAIL, PHONE, SSN, ACCOUNT_ID, DATE_OF_BIRTH, ORG, FINANCIAL (CREDIT_CARD/IBAN/ROUTING), HEALTH (DIAGNOSIS/MEDICATION) — qualitative (dense / sparse / absent)
- **PII-realism score**: high (real named individuals, typical production shape), medium (real PII but sparse/atypical), low (mostly structured with occasional PII)
- Staging recommendation: 🟢 / 🟡 / 🔴

**Methodology:**

- General-purpose research subagent, `bq` CLI access
- Billing project: `dag-bigquery-dev`
- Query budget: <$2 (~5-7 candidates × schema/count/stats/sample)
- Follows the 2026-04-16 E12 subagent pattern

**Success criteria:**

- ≥ 5 candidates characterized
- Each with entity-density estimate + PII-realism score
- License risk flagged per candidate
- Clear "stage this / skip this" recommendation
- Explicit map: which candidate is the closest analogue of which BQ customer scenario (customer support ticket / incident report / provider directory / donor CRM / nonprofit compliance)

**Deliverable:**

- New section "Tier 7b — Real-PII free-text validation (BQ public)" appended to `dataset_landscape.md`, immediately after Tier 7 and before the license+effort matrix
- Matrix extended with Tier 7b rows
- Single commit on `research/meta-classifier` after review

**Out of scope:**

- Actual corpus staging (separate follow-up)
- Re-surveying E12 candidates — Tier 7 stays as-is; Tier 7b is additive
- Synthetic candidates (fhir_synthea is covered in E12 discussion, not needed here)

**Ethical / discipline note:**

All these datasets are *legally* public. That does not mean row-level content should be transcribed into the memo or pulled into the repo casually. Shape characterization only. Staging (if any) must sample, hash, or redact — never store raw customer complaint narratives or real donor/provider rows in the test fixtures directory. This discipline matches the Tier 7 memo's stance on HN spam posts and StackOverflow bios.

### Q6 — Inverted stage 1 / PII-only meta-classifier

**Status:** ✅ complete (see `runs/20260412-q6-inverted-stage1/result.md`) — **Q6-C** verdict, LOCO +0.016 only, pivot to E10/E4
**Priority:** P0 — probably the cheapest fix that addresses Q5's
structural finding, should be tried BEFORE promoting E10's changes
**Estimated time:** 30-60 min (pure data filter + retrain, no
production code changes, no new engines)

**Why it matters:** Q5 (feature distribution audit, see
`runs/2026-04-12-q5-feature-distribution-audit/result.md`) found
that the LOCO collapse is only *partially* a feature-leakage
problem. The deeper issue is **structural label-corpus
correlation**: three of the six training corpora (gitleaks,
secretbench, detect_secrets) contain **only** `CREDENTIAL` and
`NEGATIVE` rows. Under leave-one-corpus-out, holding out a
credential-pure corpus makes "predict label" mathematically
equivalent to "predict corpus" for credential rows, because
within-corpus label diversity does not exist.

No amount of feature engineering on the current 15-feature vector
can remove this — you cannot learn within-corpus discrimination
for a label that exists in only one corpus in the training fold.

**The insight:** don't ask the meta-classifier to answer
"is this a credential or PII?" at all. Invert the question to
"is this PII?" using positive PII evidence (regex hits, column
name matches, heuristic confidence — the features Q5 flagged as
**corpus-invariant**, max KS ≤ 0.500). If yes, route to a
PII-type classifier trained on PII-only rows. If no, default
to the existing orchestrator's credential/noise handling (secret

**Q3 independently validates the stage-1 routing signal.** Q3's
forward ablation (see `runs/20260412-q3-loco-investigation/
result.md`) found that `primary_is_pii` is **the most
load-bearing feature for LOCO generalization** — dropping it
costs Δ = −0.044 mean LOCO, by far the biggest single-feature
loss. This is exactly the signal Q6 proposes to use as its
stage-1 routing gate. The LR was already leaning on
`primary_is_pii` as its most important feature; Q6 just makes
that reliance explicit at the architectural level rather than
burying it inside a 13-feature weighted sum.
scanner already answers this well).

The meta-classifier becomes a **pure PII-type arbitrator**, which
is what it should have been from the start given that the
orchestrator already has a well-functioning secret scanner engine.

**Training data scope:** 6,870 rows (synthetic 3720 + nemotron
1950 + ai4privacy 1200), 23 PII classes (the 24 original classes
minus CREDENTIAL and NEGATIVE). Three corpora, all label-diverse
(no label-purity problem).

**Task prompt for parallel session:**
```
You are running Q6 — the inverted stage 1 / PII-only
meta-classifier experiment — in a worktree off
research/meta-classifier.

CONTEXT

Q5 (see docs/experiments/meta_classifier/runs/2026-04-12-q5-
feature-distribution-audit/result.md) found that the Sprint 6
meta-classifier LOCO collapse is not fully fixable by feature
engineering because three of the six training corpora
(gitleaks, secretbench, detect_secrets) are label-pure on
{CREDENTIAL, NEGATIVE}. The LR is forced to use "which corpus"
as a proxy for "which label class" whenever a credential-pure
corpus is held out in LOCO.

The Q6 hypothesis: don't ask the meta-classifier to decide
credential vs PII at all. Filter the training data to PII-only
rows and retrain. The meta-classifier becomes a PII-type
arbitrator, which matches how the orchestrator's engines
actually work — the secret scanner already answers
"is this a credential" with high confidence via its own engine.

READ FIRST

- docs/experiments/meta_classifier/queue.md — the Research
  Workflow Contract section and the Q6 entry for the full
  task spec and constraints.
- docs/experiments/meta_classifier/runs/2026-04-12-q5-feature-
  distribution-audit/result.md — Q5's verdict. Understand why
  Q6 exists and what label purity means in this context.
- data_classifier/models/meta_classifier_v1.metadata.json —
  current baseline numbers (CV 0.916, LOCO 0.27-0.36).
- tests/benchmarks/meta_classifier/training_data.jsonl — the
  full training data you will filter.

COORDINATION

Flip Q6 status from 🟡 to 🟢 and commit as the first action.

WORK

1. Build a filtered training data file:
   - Read training_data.jsonl
   - Keep only rows where ground_truth is NOT in
     {"CREDENTIAL", "NEGATIVE"}
   - Write to tests/benchmarks/meta_classifier/
     training_data_q6.jsonl
   - Expected row count: ~6,870 (7,770 minus 750 CREDENTIAL
     minus 450 NEGATIVE = 6,570; confirm the actual number)
   - Expected class count: 22 (24 classes minus CREDENTIAL
     minus NEGATIVE)

2. Retrain the meta-classifier against the filtered data via
   scripts/train_meta_classifier.py, pointing at the new
   filename. Save the model as
   data_classifier/models/meta_classifier_v1_q6.pkl
   (do NOT overwrite v1.pkl).

3. Run the standard three-tier evaluation against the live
   baseline (DATA_CLASSIFIER_DISABLE_ML=1 is fine — Q6 is
   comparing against the same baseline as Phase 2, isolating
   the effect of filtering the training data):
   - 5-fold stratified CV macro F1
   - Held-out test macro F1 with BCa 95% CI
   - LOCO macro F1 (now with only 3 corpora in the outer loop)
   - Per-class F1 breakdown
   - McNemar's paired test vs Phase 2's v1.pkl on the
     intersection of predictable rows (PII rows only)

4. Compare against Phase 2's numbers:
   - Old CV: 0.916 | New CV: ?
   - Old held-out: 0.918 | New held-out: ?
   - Old LOCO: 0.27-0.36 | New LOCO: ? (this is the money
     number — target is ≥ 0.60)
   - Old per-class F1 on the 22 retained classes vs new

5. Classify outcome:
   - (Q6-A) LOCO ≥ 0.60: label purity was the whole story.
     Recommend promoting v1_q6 to production as v2, with a
     Sprint 7 backlog item that also adds orchestrator-side
     routing (send credential-confident columns away from
     the meta-classifier entirely, let the secret scanner
     handle them).
   - (Q6-B) LOCO improves to 0.45-0.60: partial fix.
     Recommend hybrid Q6+E10 (add GLiNER features on top of
     the filtered training data).
   - (Q6-C) LOCO barely moves: label purity was NOT the
     dominant issue. Recommend pursuing E10 (GLiNER
     features) or E9 (new corpora) instead.

6. Write the result to docs/experiments/meta_classifier/runs/
   <timestamp>-q6-inverted-stage1/result.md with:
   - The training data row/class count after filtering
   - The three-tier evaluation numbers
   - Per-class F1 comparison vs Phase 2 (on shared classes)
   - LOCO breakdown per corpus fold
   - Verdict classification (A / B / C) with the recommended
     next experiment
   - Explicit comparison table: v1 vs v1_q6 on CV, held-out,
     LOCO

7. Flip Q6 status to ✅ and commit.

CONSTRAINTS

- Same research workflow contract as Q3/Q5. You may not
  touch data_classifier/orchestrator/**,
  data_classifier/__init__.py, production tests, or
  existing loader functions. This is a data-filter + retrain
  experiment, not a schema-widening one.
- Do NOT overwrite training_data.jsonl or
  meta_classifier_v1.pkl. Both are production artifacts.
- Q6 is the PII-only experiment. Do not also add GLiNER
  features in this run — that would confound the result.
  If Q6 shows outcome B (partial fix) a followup session
  can layer GLiNER features on top.

TIME BUDGET

Target: 30-60 min. Training is fast (LogReg on 6,870 rows
with 22 classes is seconds). Most of the time is in LOCO
evaluation + result writeup.
```

**Success criteria:** A concrete LOCO macro F1 number for the
PII-only retrain. The outcome classification (A/B/C) drives the
next decision:
- A → ship v1_q6 as v2 via a Sprint 7 backlog item
- B → queue a hybrid experiment (Q6+GLiNER)
- C → label purity was not the dominant issue; pivot to E10 or
  new corpora

**Relationship to other experiments:**
- Q6 is cheaper and more targeted than E10. Run Q6 first; E10
  is either redundant (if Q6-A) or complementary (if Q6-B) or
  the right answer (if Q6-C).
- Q6 obsoletes E3 (class collapse to 4 classes): Q6 is a
  targeted class restriction that matches the orchestrator's
  existing engine split, whereas E3 was a blind aggregation.

### Q8 — Opaque-secret specialized meta-classifier

**Status:** 🟡 queued — Sprint 8 prerequisite satisfied; scope partially subsumed by Sprint 10 gated-architecture item
**Priority:** P2
**Estimated time:** 2-3 hours
**Depends on:** Sprint 8 production candidate A (CREDENTIAL split) — ✅ landed

> **Unblocked (2026-04-13):** Sprint 8 shipped the CREDENTIAL split
> (API_KEY, PRIVATE_KEY, PASSWORD_HASH, OPAQUE_SECRET — verified in
> `data_classifier/profiles/standard.yaml` on `main`, item A of the
> Sprint 8 production candidates below). The OPAQUE_SECRET label
> now exists and Q8's data filter (rows where the post-Sprint-8
> OPAQUE_SECRET heuristic would fire) is well-defined.
>
> **But the Sprint 10 gated-architecture item partially subsumes
> Q8's scope.** Q8's original framing — "does meta-classification
> have value in a scoped opaque-secret-only role?" — is a narrow
> version of the broader question the Sprint 10 backlog item
> `gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation`
> asks, which is "what should meta-classification look like
> structurally, given Q3/Q5/Q6/M1/E10 all established the flat
> classifier has a ceiling?"
>
> **Recommendation:** leave Q8 queued as a cheap diagnostic that
> could run *ahead of* the Sprint 10 sprint item to inform its
> design. If Q8-A (specialized meta ≥ 0.80 LOCO on the opaque-
> secret subset, rule-based ≤ 0.70), the Sprint 10 item's stage-2
> credential classifier has an empirical precedent. If Q8-C (rule-
> based wins), the gated architecture skips the stage-2 ML
> classifier for credentials entirely and uses pure heuristics at
> that node. Either result is load-bearing for the Sprint 10
> design, so running Q8 before Sprint 10 starts is high-leverage
> for ~2-3 hours of work.

> **Sprint 11 post-mortem (2026-04-15) — scope tightened:** Sprint 11
> item 11-F (tier-1 credential pattern-hit gate, commit `bb1644f`)
> is effectively the Q8-C outcome applied at the *gate* layer:
> rule-based credential routing shipped as the default v3 path and
> it works — pattern-hit routing has 100% precision on shape with
> 100% engine-detected credential recall per the E11 diagnostic.
> That closes the original Q8 question ("does meta-classification
> have value at all on opaque secrets"). The *reframed* Q8 for
> post-Sprint-11 is narrower: "on rows that PASS the tier-1
> credential gate (are routed into the credential stage) but
> v3's default stage-2 classifier still mis-predicts within the
> credential family, does a specialized stage-2 ML classifier
> beat it?" This is a smaller, more actionable question because
> the subset is now well-defined (rows that trigger the gate) and
> the baseline is now well-defined (v3's within-family accuracy
> on that subset). Scope-tighten this entry before running; the
> old task prompt below is pre-gate and will need rewriting.

**Why it matters:** Q3, Q5, and Q6 established that a general-purpose
meta-classifier over 24 classes fails LOCO because of structural
label purity and per-corpus feature fingerprinting. But neither
pathology applies cleanly to the *opaque-secret subset* — rows
where the engines agree something looks credential-shaped but
cannot pin down a specific type.

The hypothesis: learned arbitration has real value **only** on
ambiguous cases, not as a general classifier. This experiment tests
that by training a specialized classifier on the opaque-secret
subset alone and comparing it against the Sprint 8 rule-based
OPAQUE_SECRET heuristic.

**Outcomes:**

- **Q8-A (specialized meta wins):** binary "is it actually a
  credential" LOCO ≥ 0.80, rule-based is ≤ 0.70. Ship the
  specialized classifier as an opt-in meta-arbitrator for opaque
  secrets only.
- **Q8-B (marginal):** specialized 0.70-0.80, rule-based 0.60-0.70.
  Consider shipping as optional boost.
- **Q8-C (rule-based wins or ties):** skip meta entirely, rule-based
  approach is simpler and more maintainable.

**Task prompt for parallel session (queued until Sprint 8 lands):**

```
You are running Q8 — specialized opaque-secret meta-classifier —
on a worktree off research/meta-classifier.

PREREQUISITE: Sprint 8 CREDENTIAL split MUST be landed on main.
Verify by checking data_classifier/profiles/standard.yaml for the
OPAQUE_SECRET rule. If it is missing, STOP and report that
Sprint 8 hasn't landed yet.

READ FIRST:
- docs/experiments/meta_classifier/queue.md — Research Workflow
  Contract section + Q8 entry
- Q5, Q3, Q6 result.md files — context on why general
  meta-classification failed and why scoping to opaque secrets
  might work

WORK:
1. Build a filtered training set from training_data.jsonl (or
   the post-Sprint-8 retrained version):
   - Include ONLY rows where at least one of:
     (a) top engine confidence < 0.7 (ambiguous)
     (b) multiple engines disagreed on entity type
     (c) the post-Sprint-8 OPAQUE_SECRET heuristic would fire
   - Re-label each row with its true entity type (may now be
     OPAQUE_SECRET or a PII class if the original was right)
   - Save as training_data_q8.jsonl
   - Expected row count: 500-1500 (hypothesis — ambiguous
     subset is small)
2. Train a binary classifier: is this ambiguous row actually a
   credential (any of the 4 new credential subtypes) or
   something else (PII or NEGATIVE)?
   - LogReg with the existing 13-feature schema first
   - XGBoost as comparison if LogReg is weak
3. Evaluate:
   - Standard 5-fold CV using M1's StratifiedGroupKFold
   - LOCO over the corpora that contribute opaque-secret
     candidates
   - Compare against rule-based baseline: the Sprint 8
     OPAQUE_SECRET heuristic alone applied to the same rows
4. Classify outcome Q8-A / Q8-B / Q8-C
5. Write result.md, flip status, commit

CONSTRAINTS: same research workflow contract as Q3/Q5/Q6. Q8 is
NOT a feature-schema exception; do not modify production code.
```

**Success criteria:** a clear verdict on whether the
meta-classifier direction has any value in a scoped opaque-secret
role, independent of the general-classifier LOCO failures. Answers
the question "should meta-classification live on in some reduced
form or be abandoned entirely."

**Relationship to other experiments:**
- Q8 is the natural successor to Q3/Q5/Q6 once the Sprint 8
  taxonomy work has landed. It tests the ONE remaining
  meta-classifier hypothesis worth testing.
- Q8 is independent of E10. If E10 succeeds, we'd have two
  candidate meta-classifiers (general + specialized); they can
  coexist if each adds value in its scope.
- Q8 is the alternative hypothesis to "pattern expansion alone
  solves the credential problem." If Sprint 8 production
  candidate B (pattern import) closes most of the credential
  detection gap, Q8 becomes less important.

## Methodology corrections (Sprint 7 backlog candidates, not experiments)

These are code fixes discovered during research, not experiments.
They belong in a regular sprint under code review, not in parallel
research sessions. Landing them is **prerequisite to trusting any
future meta-classifier number** — including Q6, E10, and any
promoted v2 model — because the current CV methodology is
systematically optimistic.

### M1 — CV strategy: StratifiedKFold → StratifiedGroupKFold

**Status:** ✅ shipped Sprint 9 — research run `runs/m1-2026-04-13/result.md`; promoted via sprint commits `6b74da7` + `b331ab1` on sprint9/main
**Discovered by:** Q3 (`runs/20260412-q3-loco-investigation/
result.md` §6)
**Priority:** P0 — blocking correctness on every meta-classifier
metric, including the shipped v1 model
**Effort:** S (one-line code change + retrain + metadata refresh)

> **Sprint 9 outcome (2026-04-13):** M1 shipped. Actual measured
> impact on the retrained `meta_classifier_v1.pkl`:
> - `best_c`: 100 → **1.0** (Q3's prediction of "≤10" confirmed to
>   the decimal)
> - CV mean macro F1: 0.9160 → **0.1940 ± 0.0848**
> - Held-out macro F1: 0.9185 → **0.8511**
> - LOCO mean: ~0.30 → **~0.17**
> - Tertiary blind delta (meta − live, 5-engine framing):
>   **+0.2432** (post-Gretel ingest + M1)
>
> The 0.66-point CV drop is the shortcut finally becoming visible,
> not the model regressing — a point the Sprint 9 learning memo
> makes at length (`docs/learning/sprint9-cv-shortcut-and-gated-architecture.md`
> on main).
>
> A follow-on wrinkle — the StratifiedGroupKFold promotion initially
> broke on the Q6-filtered PII-only dataset because the 3-corpus
> training data doesn't always satisfy `n_groups ≥ n_splits`; commit
> `b331ab1` added an adaptive fallback that degrades to `n_splits
> = min(n_splits, n_groups)` when the group count is too low. The
> v1 production model is unaffected by this fallback (it trains on
> the full 6-corpus dataset where `n_groups=6 ≥ n_splits=5`), but
> any future research experiment that filters the training data
> should expect to hit the low-group path.

**The bug:** `scripts/train_meta_classifier.py` uses
`sklearn.model_selection.StratifiedKFold(n_splits=5)` for the
cross-validation that drives best-`C` selection. Because folds
are built row-wise across *all* corpora, every training fold
contains rows from every corpus, which lets the model learn
corpus-specific feature fingerprints and reuse them at evaluation
time. The "CV macro F1 = 0.916" number is not measuring
generalization; it's measuring how well the model memorizes
in-distribution corpus signatures.

**The fix:** use
`sklearn.model_selection.StratifiedGroupKFold(n_splits=5,
shuffle=True, random_state=42)` with `groups=[row.corpus for row
in dataset]`. This gives folds where groups (corpora) don't leak
across train/test while still preserving class-label stratification.
With 6 corpora and 5 splits, the split is natural: four folds
hold out one corpus each, one fold holds out two corpora.

**Expected impact:**
- Best-`C` selection drops from 100 to 1–10 (Q3 §5a showed C=1
  was the LOCO-optimal single-knob setting on the current 13
  features).
- Reported CV macro F1 drops from ~0.92 to ~0.40–0.50.
- The CV and LOCO numbers converge — reported CV becomes an
  honest estimate of generalization.
- Phase 2's "+0.25 vs live baseline" claim on the 80/20 held-out
  test set is NOT affected (that split is independent of the
  CV strategy).

**Sprint item spec:**

- **File:** `scripts/train_meta_classifier.py`
- **Change:** swap the CV splitter; thread `groups` through
  `cross_val_score` / `GridSearchCV` calls
- **Rebuild:** re-run training against
  `training_data.jsonl`, regenerate the
  `meta_classifier_v1` artifacts under
  `data_classifier/models/`
- **Re-evaluate:** rerun the three-tier eval
  (`evaluate.py`) and compare v1 (pre-fix) vs v1 (post-fix)
  numbers
- **Update docs:**
  - `docs/sprints/SPRINT6_HANDOVER.md` — add a methodology
    correction note; cite the corrected CV macro F1
  - `docs/research/meta_classifier/sharding_strategy.md` —
    update §6 to recommend StratifiedGroupKFold
- **Tests:**
  - `tests/test_meta_classifier_training.py` — add a unit test
    that the training script uses a group-aware CV splitter
  - `tests/test_meta_classifier_shadow.py` — existing shadow
    tests should still pass (feature schema unchanged;
    different weights but same interface)

**Acceptance criteria:**
- `grep -q "StratifiedGroupKFold\|GroupKFold"
  scripts/train_meta_classifier.py`
- New `meta_classifier_v1.metadata.json` has `best_c ≤ 50`
  (was 100)
- New `cv_mean_macro_f1` is within 0.10 of
  `loco_mean_macro_f1` (convergence check — was 0.92 vs 0.30)
- All existing meta-classifier tests pass
- Phase 2's delta claim is re-verified in the new metadata or
  explicitly corrected if it changed materially

### M2 — LOCO harness uses model's actual `C`

**Discovered by:** Q3 §6
**Priority:** P1 — correctness, but lower leverage than M1
**Effort:** XS (two-line fix)

**The bug:** `tests/benchmarks/meta_classifier/evaluate.py::
_loco_fit_predict` hardcodes
`LogisticRegression(C=100.0, class_weight="balanced", ...)` when
refitting on LOCO folds, regardless of what `C` the shipped
model actually uses. The hardcoded `C=100` also happens to be
the LOCO-pessimal value (Q3 §5a showed `C=1` gives +0.034 LOCO
for free). Every LOCO number Phase 2 reported under-represents
the model's real LOCO performance by ~0.03.

**The fix:** read `C` from the loaded model's metadata sidecar
and pass it through to the LOCO refit.

**Sprint item spec:**
- **File:** `tests/benchmarks/meta_classifier/evaluate.py`
- **Change:** read `best_c` from metadata, pass to the LR
  constructor in `_loco_fit_predict`
- **Add CLI flag:** `--c-override` for diagnostic runs
- **Re-evaluate:** rerun LOCO on v1 with the correct `C`,
  compare numbers, update metadata

**Acceptance criteria:**
- LOCO harness does not contain any hardcoded C value
- Rerunning LOCO on v1 with the fixed harness gives
  numbers at least 0.01 better than the Phase 2 report
- The diagnostic `--c-override` flag works for ad-hoc
  experimentation

### M3 (optional) — Report LOCO per-holdout, not just mean

**Discovered by:** Q3 §5c
**Priority:** P3 — observability improvement
**Effort:** XS

**The observation:** Q3's extended LOCO table shows that
per-corpus holdout F1 varies wildly (ai4privacy 0.26, nemotron
0.36, synthetic 0.13, gitleaks 0.08, detect_secrets 0.06,
secretbench 0.33). Reporting only the mean of ai4privacy and
nemotron hides that the synthetic corpus is load-bearing in a
way no real corpus is and that the credential corpora are not
interchangeable at the feature level.

**The fix:** extend `metadata.json` to include
`loco_per_holdout` as a dict, and make the evaluate.py output
a per-corpus breakdown table.

Purely informational — doesn't change how models are selected
or shipped, but makes future research visible in one glance.

## Sprint 8 production candidates (drafted from research discussion)

These are **production backlog items**, not research experiments.
They are drafted here because they emerged from the research thread
and are prerequisites to several queued research experiments (Q8
specifically depends on Item A). When Sprint 7 closes and Sprint 8
planning begins, hand these specs to the Sprint 8 session — they
are self-contained and ready to turn into `agile-backlog add` /
YAML backlog files.

### Item A — Split CREDENTIAL into API_KEY, PRIVATE_KEY, PASSWORD_HASH, OPAQUE_SECRET

**Complexity:** M (1-2 days)
**Priority:** P1
**Category:** refactor
**Dependencies:** none
**Blocks:** Item B (pattern expansion), Q8 research experiment

**Goal:** Replace the single CREDENTIAL entity type with 4
deterministic subtypes. Retain CREDENTIAL as a category rollup
for consumers. Add an OPAQUE_SECRET heuristic for credential-shaped
values that don't match any specific pattern.

**Rationale:** The current single-class CREDENTIAL label conflates
six distinct credential subtypes (API keys, passwords, JWTs,
private keys, hashes, generic secrets) that each have different
detection profiles, risk profiles, and downstream handling
requirements. This makes the classification schema wrong at the
taxonomic level, produces muddled training data, and limits
downstream routing precision. Splitting into 4 deterministic
types + a rule-based catch-all heuristic aligns the schema with
how the engines actually detect each subtype.

**Acceptance criteria:**

- `data_classifier/profiles/standard.yaml` has 4 new credential-
  category rules (`API_KEY`, `PRIVATE_KEY`, `PASSWORD_HASH`,
  `OPAQUE_SECRET`); no `CREDENTIAL` rule
- All 4 rules declare `category: credential` for rollup support
- `data_classifier/patterns/default_patterns.json`: existing
  shape-identifiable credential patterns retargeted to their
  correct subtype (AWS/GitHub/Slack/OpenAI/Stripe etc → API_KEY,
  PEM markers → PRIVATE_KEY, `$2[aby]$`/`$argon2[id]$`/`$scrypt$`
  prefixes → PASSWORD_HASH)
- **PASSWORD_HASH fires ONLY on values with algorithm prefix.** Raw
  hex strings (unprefixed SHA-256/SHA-1/MD5) are NOT classified as
  PASSWORD_HASH — they go to OPAQUE_SECRET or stay unclassified,
  because raw hex collides with ETHEREUM_ADDRESS, transaction
  hashes, file hashes, and git SHAs.
- New OPAQUE_SECRET heuristic in
  `data_classifier/engines/heuristic_engine.py`: detection rule is
  (entropy > threshold) AND (non-language character frequency) AND
  (length in range 20-200) AND (high per-column distinct ratio)
  AND (no other engine claimed the row)
- `data_classifier/engines/secret_scanner.py` emits the correct
  subtype based on the matched key name in
  `secret_key_names.json`, not the generic `CREDENTIAL` label
- `data_classifier/patterns/column_names.json` credential-related
  column names split across the 4 subtypes based on semantic intent
- All existing 1009+ tests pass with fixture updates where
  CREDENTIAL was asserted
- New `tests/test_opaque_secret.py` covers positive cases
  (high-entropy opaque strings) and negative cases (bitcoin
  addresses, UUIDs, long IDs that are NOT secrets)
- Benchmark F1 on gitleaks/secretbench/detect_secrets corpora is
  within 0.02 of pre-split baseline (non-regression gate)

**Technical specs:**

- File: `data_classifier/profiles/standard.yaml` — replace
  CREDENTIAL rule with 4 new rules, each with `category: credential`
- File: `data_classifier/patterns/default_patterns.json` —
  retarget ~10-15 existing credential patterns by `entity_type`
- File: `data_classifier/patterns/column_names.json` — split
  credential-related column names
- File: `data_classifier/patterns/secret_key_names.json` — add
  subtype field per entry
- File: `data_classifier/engines/secret_scanner.py` — replace
  hardcoded CREDENTIAL with subtype emission based on key name
- File: `data_classifier/engines/heuristic_engine.py` — new
  `opaque_secret_detection()` function
- File: `tests/test_opaque_secret.py` — new test module
- File: `tests/fixtures/` — update golden expectations

**Test plan:**

- Unit: each new entity type has ≥5 positive + ≥5 negative fixtures
- Integration: end-to-end classification on 3 credential corpora
  (gitleaks, secretbench, detect_secrets) produces correct subtype
- Golden fixtures: existing CREDENTIAL expectations remapped
- Regression: full test suite green
- Benchmark: pre/post split F1 comparison on credential corpora
- OPAQUE_SECRET edge cases: bitcoin address NOT classified as
  OPAQUE_SECRET (BITCOIN_ADDRESS rule should fire first)

**Deliberate scope exclusions:**

- **No PASSWORD entity type.** Passwords need column-name context
  exclusively (value alone is undetectable). The existing column
  name engine already handles them via `password`/`pwd` dictionary.
  They continue to roll up to the credential category via
  column-name-only detection.
- **No JWT entity type.** Folded into API_KEY (or OPAQUE_SECRET
  for non-standard JWT-like strings). PII extraction from JWT
  payloads is deferred indefinitely.
- **No ENCRYPTED_BLOB entity type.** Indistinguishable from random
  high-entropy data without decryption context; falls through to
  OPAQUE_SECRET or stays unclassified.
- **No meta-classifier changes in this item.** The existing v1
  meta-classifier stays shadow-only with its old CREDENTIAL label.
  Research experiment Q8 handles the specialized opaque-secret
  meta-classifier direction independently once this item lands.

### Item B — Harvest Kingfisher + gitleaks + detect-secrets + Nosey Parker patterns into API_KEY

**Complexity:** **L (3-5 days)** (upgraded from M after landscape survey)
**Priority:** P1
**Category:** feature
**Dependencies:** Item A must land first (API_KEY entity type
must exist)
**Blocks:** nothing — enables immediate credential detection
improvement
**Reference:** See `docs/experiments/meta_classifier/pattern_source_landscape.md`
for the full landscape survey this spec is built on.

**Goal:** Bulk-import 200-500 credential detection regex patterns
from license-compatible sources into
`data_classifier/patterns/default_patterns.json`, all targeting
the new `API_KEY` entity type that Item A introduces.

**Rationale:** Service-prefixed API keys are the cleanest possible
credential signal — regex detection gives near-zero false positive
risk and zero training data requirement. Our current pattern
library has a single-digit number of service-specific credential
patterns. A landscape survey (2026-04-13) identified **MongoDB
Kingfisher** (Apache 2.0, 800+ rules, released 2025) as the single
highest-value source beyond gitleaks — it covers the
SaaS/observability/ITSM ecosystem (Datadog, New Relic, Sentry,
PagerDuty, Auth0, Okta, Jira, Confluence, Salesforce, Shopify,
Vercel, Cloudflare, and ~30 other categories) that gitleaks
misses entirely.

Combined with gitleaks, detect-secrets, and Praetorian Nosey
Parker, the license-compatible harvest can yield an estimated
**525-660 net-new patterns after deduplication**. This expansion
improves blind-mode credential detection accuracy more than any
amount of meta-classifier work could, and ships immediately
without training concerns. It also supersedes the old backlog
item "Cloud service token expansion: 20+ services from trufflehog
reference" at dramatically larger scope.

**Acceptance criteria:**

- `data_classifier/patterns/default_patterns.json` grows by
  **≥ 200 credential patterns** (net-new, after deduplication
  with existing patterns and cross-source dedup)
- Each new pattern has:
  - Unique `id` including the service name
    (e.g., `aws_access_key_id`, `stripe_live_secret_key`,
    `datadog_api_key`, `pagerduty_integration_key`)
  - Regex pattern (RE2-compatible)
  - `entity_type: API_KEY` (Item A must be landed first)
  - `category: credential`
  - Confidence value appropriate to the specificity of the regex
    (high for prefix-anchored, lower for pure entropy)
  - Positive and negative test fixtures in
    `tests/test_pattern_library.py` or equivalent
  - Attribution field pointing to the source repo + license
- Gitleaks benchmark corpus detection F1 improves from current
  baseline (Sprint 5: macro F1 0.897) by **≥ 0.05**
- SecretBench detection rate improves by **≥ 0.03**
- No regression in non-credential benchmark F1 (Nemotron,
  Ai4Privacy)
- New `docs/LICENSE_AUDIT_credential_patterns.md` file documents
  the source of each imported pattern and its license. Structure:
  one table section per source, with (pattern_id, upstream_name,
  upstream_license, upstream_url, our_confidence) per row.
- CI check fails if any pattern references trufflehog directly,
  semgrep-rules, atlassian-sast-ruleset, or secrets-patterns-db
  (all excluded due to license incompatibility or mixing risk)

**Technical specs — harvest sources (ranked by yield):**

1. **MongoDB Kingfisher (PRIMARY):**
   `https://github.com/mongodb/kingfisher`
   - **License: Apache 2.0** (verified)
   - ~800 YAML rules
   - **Expected net-new yield: 400-500 patterns** after dedup
   - Covers unique services: Datadog, New Relic, Sentry, Dynatrace,
     Honeycomb, Sumo Logic, PagerDuty, OpsGenie, Auth0, Okta, Clerk,
     LaunchDarkly, 1Password, JFrog, SonarCloud, Salesforce,
     HubSpot, Jira, Confluence, Asana, Linear, Monday, Zendesk,
     Intercom, Shopify, Cloudflare, Doppler, Mapbox, Twitch,
     Vercel, and more
   - Port approach: YAML → our JSON schema via ingestion script

2. **gitleaks:**
   `https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml`
   - **License: MIT** (verified)
   - ~100 TOML rules
   - **Expected net-new after Kingfisher dedup: 80-90 patterns**
   - Use as validation baseline — gitleaks rules are
     production-hardened for years

3. **Praetorian Nosey Parker (PRECISION SUPPLEMENT):**
   `https://github.com/praetorian-inc/noseyparker`
   - **License: Apache 2.0** (verified)
   - 188 YAML rules, precision-curated for low FPR
   - **Expected net-new after Kingfisher + gitleaks: 20-30**
   - Use as a **second-opinion filter**: patterns that exist in
     both Kingfisher and Nosey Parker are high-confidence.
     Patterns that exist only in Kingfisher should be manually
     reviewed before import.

4. **detect-secrets:**
   `https://github.com/Yelp/detect-secrets/tree/master/detect_secrets/plugins`
   - **License: Apache 2.0**
   - ~30 Python-embedded regex plugins
   - **Expected net-new: 10-15 patterns**

5. **LeakTK patterns (OPTIONAL):**
   `https://github.com/leaktk/patterns`
   - **License: MIT** (verified)
   - ~100 rules across tool-version folders
   - Red Hat curation. **Expected net-new: 10-15 patterns**

6. **ripsecrets (OPTIONAL SANITY BASELINE):**
   `https://github.com/sirwart/ripsecrets`
   - **License: MIT**
   - ~40 rules, near-zero-FP curation
   - Use as a gap detector: every ripsecrets pattern should
     have a match in our library. If one doesn't, that's a
     high-confidence missing service.

7. **GitHub secret scanning partner list (INSPIRATION):**
   `https://docs.github.com/en/code-security/secret-scanning/introduction/supported-secret-scanning-patterns`
   - License: CC-BY-4.0 (docs)
   - 200+ partner services with published token formats
   - Use as a CROSS-CHECK: after harvest, verify our pattern
     list covers every service in the partner list. For
     services in the partner list that we don't cover, follow
     the vendor's own documentation link and re-derive the
     pattern from the vendor's native docs (not from GitHub's
     page). Attribution goes to the vendor.

**Technical specs — EXCLUDED sources:**

- **trufflehog** (`https://github.com/trufflesecurity/trufflehog`)
  — **AGPL-3.0**, cannot copy source. Use ONLY the DETECTOR LIST
  (file names in `pkg/detectors/`) as a gap indicator. Never
  read or copy their regex code.
- **Semgrep secrets rules** — Semgrep Rules License v1.0
  (non-OSI, restrictive). Skip.
- **Atlassian SAST ruleset** — LGPL-2.1, incompatible with
  static copy. For Atlassian-specific patterns (Jira, Confluence,
  Bitbucket, Trello), re-derive from Atlassian's own developer
  documentation, not from this repo.
- **mazen160/secrets-patterns-db** — 1,600+ rules but contains
  AGPL-derived trufflehog subset mixed with CC-BY-4.0 main
  content. Provenance filtering is nontrivial. **Skip for now.**
  Reconsider only if specific gaps emerge after the Tier 1
  harvest.
- **shhgit** — MIT but author-declared unmaintained. Skip.
- **Rusty-Hog (New Relic)** — trufflehog-derived, dormant. Skip.

**Technical specs — ingestion script:**

- **New file:** `scripts/ingest_credential_patterns.py`
- **Input:** per-source YAML/TOML/Python files checked out to
  a temporary directory (the script fetches each repo at a
  pinned revision, NOT HEAD, so imports are reproducible)
- **Output:** a patch-format file that updates
  `data_classifier/patterns/default_patterns.json`
- **Deduplication:** across sources, identify patterns that
  match the same service and pick the one with:
  1. Tightest regex (smallest character class surface)
  2. Most specific prefix anchoring
  3. Best attribution (known upstream > derived)
- **Cross-source precedence order when dedup collapses a
  match:** Kingfisher → gitleaks → Nosey Parker →
  detect-secrets → LeakTK → ripsecrets
- **Attribution metadata:** each imported pattern gets a new
  `sources` field listing ALL upstreams that had this pattern
  with their respective licenses
- **Reproducibility:** script is re-runnable when sources
  update; diffs are reviewed as normal code changes

**Test plan:**

- Unit: every new pattern has at least one positive fixture (a
  known valid token example — use the service's own
  documentation for examples, NEVER real credentials) and one
  negative fixture (a lookalike that should NOT match)
- Pattern library regression test: iterate over the full
  pattern list, confirm each compiles and each example matches
- Benchmark delta report: run accuracy_benchmark before and
  after the import; confirm ≥ 0.05 improvement on gitleaks
  corpus and ≥ 0.03 on SecretBench
- License audit test: CI check confirms every pattern in
  `default_patterns.json` has either an attribution field or is
  documented in `docs/LICENSE_AUDIT_credential_patterns.md`
- License exclusion check: grep for "trufflehog", "semgrep-rules",
  "atlassian-sast-ruleset", "secrets-patterns-db" in pattern
  metadata; CI fail if found
- Cross-check against GitHub partner list: automated or manual
  verification that every service in the partner list is either
  covered or has a tracked gap

**Notes:**

- This item is blocked on Item A because the new patterns need
  `entity_type: API_KEY` to exist.
- The bulk ingestion script work can start earlier than Item
  A's schema changes — it only depends on understanding the
  target JSON format, which is already defined.
- **Complexity upgraded from M to L** because of the larger
  source count (4-6 sources instead of 2), the license audit
  work, and the 200+ patterns needing fixtures.
- **The landscape survey document**
  (`docs/experiments/meta_classifier/pattern_source_landscape.md`)
  is the authoritative reference for this item. Do not
  re-survey — update that file if sources change.
- The gap categories identified in the landscape survey
  (financial/payments credentials, LLM/AI provider keys beyond
  OpenAI, infrastructure tokens, regional cloud providers,
  observability stack, enterprise SSO) are NOT covered by any
  existing license-compatible source and are tracked as
  Sprint 9+ custom-pattern candidates. Sprint 8 Item B imports
  everything Tier 1 provides; Sprint 9 writes the custom
  patterns for the remaining gaps.

### Relationship between Items A and B

These two items are deliberately separated so Item A can ship
without waiting for the full pattern harvest, but they are
naturally paired:

| Sequence | Week 1 | Week 2 | Week 3 |
|---|---|---|---|
| A then B | Item A ships, new taxonomy live | Item B begins, patterns imported | Benchmark delta, license audit |
| B then A | (impossible — B depends on A's taxonomy) | | |
| Combined | Items A + B in one large item | | |

**Recommended:** ship A and B as two separate PRs in the same
sprint, with A landing first. This gives the sprint a visible
milestone (new taxonomy is live) mid-sprint before the larger
pattern import finishes.

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
