# Research Branch Sync Runbook

**Purpose.** Bring `research/meta-classifier` up to date with `origin/main`
at the end of each sprint, so research experiments run against the
feature schema and training infrastructure that main has actually
shipped.

**Contract reference.** This runbook is the operational companion to
the *Merging main into research* subsection in
[`docs/experiments/meta_classifier/queue.md`](../experiments/meta_classifier/queue.md)
under the Research Workflow Contract. If this runbook and the contract
disagree, **the contract wins** — update the runbook, not the contract.

**When to run.** Once per sprint, after all three:
1. The sprint-end commit has landed on `origin/main`.
2. GitHub Actions CI (`ci.yaml`) is green for that commit.
3. The sprint handover doc exists at `docs/sprints/SPRINT{N}_HANDOVER.md`.

Never run mid-sprint. Never run on yellow/red CI. The first two checks
are gates; the third is an ordering guarantee — the handover doc is
the input to the queue.md annotation pass in Step 5.

**Who runs it.** A deliberate human (or agent) session, not automation.
The ritual is ~15 minutes of commands plus 5-30 minutes of conflict
resolution and validation, depending on drift. Mixing it with any other
work is a bad idea.

**Ownership contract recap.** Research writes to `docs/experiments/**`,
`tests/benchmarks/meta_classifier/**`, non-v1 suffixed meta-classifier
pkls, and additively to `scripts/train_meta_classifier.py` and
`tests/benchmarks/corpus_loader.py`. It does not write to
`data_classifier/orchestrator/**` (except the feature-schema exception
additive-only carve-out), `data_classifier/__init__.py`, production
patterns, engines, or profiles. A merge of main into research should
therefore have zero conflicts outside a small set of shared touchpoints;
conflicts outside that set mean a prior research session violated the
contract and need investigation.

---

## Pre-flight checks

Run all of these before executing any ritual step. All must pass.

### 1. Sprint is actually delivered

```bash
gh api repos/:owner/:repo/commits/main --jq '.commit.message' | head -3
```

The top commit on main should be the sprint-end bump. Recent shape:
`chore(sprint${N}): sprint-end — handover, benchmarks, PROJECT_CONTEXT`
or equivalent.

### 2. CI green on the sprint-end commit

```bash
gh run list --workflow=ci.yaml --branch=main --limit 3
```

Expected: the top entry is a green checkmark against the sprint-end
commit. If the top entry is yellow (in progress), **wait** — do not
sync against in-flight CI. If red, stop and escalate; the sync target
is broken.

### 3. Research worktree is clean

```bash
git status
```

Must show "nothing to commit, working tree clean". If there are
untracked or modified files, triage them (commit, delete, or stash)
*before* syncing. The sync ritual must not be mixed with any other
research work in the same commit.

### 4. No other sessions on research/meta-classifier

```bash
git worktree list
```

Only the worktree you are in should be on `research/meta-classifier`.
Other worktrees on other branches are fine. If another worktree has
this branch checked out, pause any agent session running there before
proceeding.

### 5. Fetch fresh state

```bash
git fetch origin --prune
```

Must exit 0. Any fetch error stops the ritual.

---

## The ritual

Execute in order. Each step is a single command or a single verified
change. `${N}` is the sprint number that just ended.

### Step 1 — Tag the pre-sync state

```bash
git tag research/pre-sprint${N}-sync
```

Local-only rollback anchor. Do not push. Step 6 deletes it after the
sync has survived one subsequent research experiment.

### Step 2 — Queue.md drift check

```bash
git diff origin/main:docs/experiments/meta_classifier/queue.md \
         research/meta-classifier:docs/experiments/meta_classifier/queue.md \
  | grep -E '^(\+|-)[^+-]' | head -30
```

Expected shape: every non-header line is a `+` (research has added
entries, made annotations, appended results). **Zero `-` lines.** Any
`-` line means main has a version of queue.md that research does not —
which means someone edited queue.md directly on main, bypassing the
research → main merge-back path. **Stop the sync**, investigate, and
only proceed once the drift is reconciled.

### Step 3 — Merge

```bash
git merge origin/main --no-ff \
  -m "sync(research): merge main for Sprint ${N} — <1-line summary of what main shipped>"
```

The `--no-ff` forces a merge commit even in the unlikely case that
research is a direct ancestor. The 1-line summary should reference the
sprint number and the highest-impact thing that shipped (e.g.,
"v4 schema + new FAMILY taxonomy" or "credential pattern harvest +
shard-twin leak fix").

**Expected conflicts and resolutions:**

| File | Action |
|---|---|
| `docs/experiments/meta_classifier/queue.md` | `git checkout --ours <path> && git add <path>` — research is authoritative |
| `scripts/train_meta_classifier.py` | Standard three-way merge. Preserve research's additive changes where they don't conflict with main's pipeline changes. If main rewrote the training loop and research's edits no longer apply cleanly, take `theirs` and file a research-side follow-up. |
| `tests/benchmarks/corpus_loader.py` | Append-only on both sides. Should auto-merge. If conflict, take `theirs` + manually re-apply research's appended functions at the end of the file. |
| `data_classifier/orchestrator/meta_classifier.py` | Only if the feature-schema exception is currently active (research has widened `FEATURE_NAMES`). Standard three-way merge; preserve main's order of base features and append research's extras at the end. |
| Anything else in `data_classifier/**` | **Unexpected.** Stop the sync, `git merge --abort`, investigate why research has edited a production file, file a cleanup item, and restart the sync only after the contract violation is removed. |

Finalize:

```bash
git commit  # only if conflicts were resolved; --no-ff merges without conflicts commit automatically
```

### Step 4 — Post-sync validation

All four checks must pass. If any fails, go to **Rollback** below.

#### 4a. Schema version pickup

```bash
python -c "from data_classifier.orchestrator.meta_classifier import FEATURE_SCHEMA_VERSION, FEATURE_DIM; print(f'schema v{FEATURE_SCHEMA_VERSION}, dim={FEATURE_DIM}')"
```

Expected output format: `schema v{N}, dim={M}`. As of Sprint 13 the
values are `schema v5, dim=49` (bumped from v3/46 in Sprint 11 via
Sprint 12 v4 and Sprint 13's Option A train/serve-skew fix). Bump the
expected values in this runbook whenever main ships a new
`FEATURE_SCHEMA_VERSION`.

Failure here means research's Python path has not picked up main's
schema changes — usually a stale `.pyc` or an editable install pointing
at the wrong tree. Do not proceed.

#### 4b. Import sanity

```bash
python -c "from data_classifier import classify_columns, ColumnInput, ClassificationFinding; print('ok')"
```

Any ImportError means the merge broke the public API surface.

#### 4c. Unit tests

```bash
pytest tests/ -v -x --ignore=tests/benchmarks/
```

Expected: all green. Benchmark suites are excluded here because they
depend on corpus files that may not be present in every worktree; they
get smoked in 4d.

#### 4d. Family benchmark smoke run

```bash
python -m tests.benchmarks.family_accuracy_benchmark --limit 50 \
    --out /tmp/sync-bench.jsonl --summary /tmp/sync-bench.json
```

(As of Sprint 13, `--out` and `--summary` are required positional-ish
args. The `/tmp/` paths are throwaway — the sync validation only cares
that the benchmark runs without errors.)

Expected: completes without errors. We do **not** gate on the accuracy
number at this stage — that's the experiment designer's job. We gate
on the benchmark being *runnable* against the new schema. A numeric
regression here is a research finding, not a sync failure.

If all four pass, push:

```bash
git push origin research/meta-classifier
```

### Step 5 — Queue.md annotation pass

The sync picked up main's production code, but the queue.md still
describes experiments as "future research" even for directions whose
findings shipped during the sprint window. For each queue entry whose
research direction was promoted to a sprint item, add an annotation:

```
**Status:** ✅ SHIPPED — Sprint ${N} item ${backlog_id}. <1-line summary
of what shipped, with commit hash.>
```

**How to find the mapping:** read `docs/sprints/SPRINT${N}_HANDOVER.md`,
look at the "Delivered" section, cross-reference against experiment
entries in queue.md by topic. A rough heuristic: if a sprint item's
title mentions a feature, metric, or mechanism that appears in an
experiment entry's motivation, that's a candidate for annotation.

Examples of what this looks like in practice (from Sprint 11):
- E11 → "✅ SHIPPED — Sprint 11 item 11-F, tier-1 credential
  pattern-hit gate (commit `bb1644f`). Yellow verdict was an
  under-estimate; gating is now the default v3 path."
- (hypothetical) E4 binning → "✅ SHIPPED — Sprint 11 item 11-E,
  Chao-1 bias-corrected cardinality (commit `987194c`). E4's binning
  proposal was superseded by Chao-1 as the distribution-invariant
  feature."

This is a manual 5-15 minute pass per sprint. Budget for it.

Commit and push:

```bash
git add docs/experiments/meta_classifier/queue.md
git commit -m "docs(research): annotate queue.md with Sprint ${N} shipped items"
git push origin research/meta-classifier
```

### Step 6 — Delete the rollback tag (after validation window)

Keep the rollback tag until the sync has survived **at least one**
subsequent research experiment run on the new schema — that's the real
test. Then:

```bash
git tag -d research/pre-sprint${N}-sync
```

Do not push tag deletion (tags were local-only). If no experiment is
planned within a week of the sync, delete the tag anyway — its purpose
is short-term rollback safety, not permanent history.

---

## Stale training data caveat

The sync updates **code** — feature extractors, model definitions,
training pipeline, engine cascades. It does **not** update **data** —
`tests/benchmarks/meta_classifier/training_data.jsonl` still contains
feature vectors extracted against the old schema.

If you plan to run any training experiment after the sync, regenerate
training data first:

```bash
python -m tests.benchmarks.meta_classifier.build_training_data \
    --output tests/benchmarks/meta_classifier/training_data.jsonl
```

(Exact invocation may drift — check `build_training_data.py --help` for
current flags.)

Regeneration is **separate** from the sync because:
1. It requires the corpus downloads which may not be available in every
   worktree.
2. It is slow (~minutes to hours depending on corpus size).
3. Non-training experiments (descriptive stats, Q-series investigations)
   don't need fresh training data.

A feature-engineering experiment that forgets this step will train on
mis-dimensioned vectors and silently fail or produce garbage metrics.
Put a note in the experiment's result memo stating when the training
data was regenerated, against which `FEATURE_SCHEMA_VERSION`, and
against which corpus commit.

---

## Rollback

If post-sync validation fails at any of Steps 4a-4d, or a subsequent
research experiment reveals the sync broke something non-obvious:

```bash
git reset --hard research/pre-sprint${N}-sync
git push origin research/meta-classifier --force-with-lease
```

`--force-with-lease` is safer than `--force`: it refuses if another
session pushed in the meantime, avoiding accidental overwrites.

After rolling back, file a blocker with:
- The sprint number that failed to sync
- Which validation step failed (4a / 4b / 4c / 4d / post-hoc)
- Full error output
- Current `FEATURE_SCHEMA_VERSION` on research vs main

**Do not retry the sync until the root cause is identified.** Research
experiments can continue on the pre-sync state — the stale schema is
fine for investigations that do not touch feature engineering (Q-series
methodology work, corpus diversity analysis, descriptive statistics).

---

## First-time execution

The first run of this runbook is the one-time Sprint 9→12 recovery.
That run has additional steps — see
[`docs/process/research_sync_sprint12_recovery.md`](research_sync_sprint12_recovery.md)
for the extras (stale E11 file cleanup, queue.md corrections for
multiple sprints' worth of shipped work, and a pointer to the
next research thread).

After Sprint 12 recovery, delete that file. Every subsequent sprint
runs this runbook unmodified.

---

## Maintenance

Update this runbook when:
- `FEATURE_SCHEMA_VERSION` bumps on main (update the expected value in
  Step 4a).
- A new validation gate becomes mandatory (add a Step 4e).
- The training-data regeneration command changes (update the stale-data
  caveat).
- The ownership contract changes (update the conflict resolution table
  in Step 3).
- The ritual is run and something breaks in a way that wasn't anticipated
  (add a "gotcha" entry below).

### Gotchas log

*Append findings here as the ritual gets run. Each entry: date, sprint
number, what went wrong, what to do next time.*

- **2026-04-17, Sprint 13 sync.** Step 2 drift check flagged 13 `-`
  lines in the queue.md diff. All 13 were research's own `**Status:** 🟡
  queued` → `✅ complete`/`⏸ blocked` rewrites on experiment entries
  research owns — not main adding content research hadn't seen. The
  merge resolved cleanly with no manual `checkout --ours` needed
  because git's three-way merge saw the surrounding context match.
  Next time: when drift shows `-` lines, run `grep -E '^-[^-]'` on
  the diff — if every `-` line is a `**Status:**` line, it's research's
  own status updates and is safe to proceed. Only stop if `-` lines
  carry actual entry content (text outside the status field).
- **2026-04-17, Sprint 13 sync.** `family_accuracy_benchmark` now
  requires `--out` and `--summary` args (previously optional). Updated
  Step 4d invocation.
