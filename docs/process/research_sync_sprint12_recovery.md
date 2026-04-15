# Research Branch Sync — Sprint 12 Recovery (one-time)

**Status.** Deferred until Sprint 12 delivers.

**Delete this file after successful execution.** This is a one-time
memo for recovering from a crash + drift combination specific to the
Sprint 9 → Sprint 12 window. The reusable ritual lives in
[`research_branch_sync_runbook.md`](research_branch_sync_runbook.md).
This file lists only the one-time extras that won't apply to future
sprints.

---

## Background

Between 2026-04-12 (`fca2a61`, last shared commit with main) and
2026-04-15 (`ccc2704`, GLiNER reference guide commit), the
`research/meta-classifier` branch fell 117 commits behind `main`.
During that window Sprint 11 shipped:

- Meta-classifier feature schema v2 → v3 (15 features → 46)
- Chao-1 bias-corrected cardinality estimator (Sprint 11 item 11-E)
- Dictionary-word-ratio heuristic feature (item 11-D)
- Tier-1 credential pattern-hit gate (item 11-F)
- `primary_entity_type` one-hot with FAMILY taxonomy (item 11-H/11-I)
- v2/v3 meta-classifier pkl artifacts retrained (commits `ff70775`,
  `1547fd8`)
- Family accuracy benchmark as the canonical quality gate

All of this was shipped as production code while the research branch
continued to reference a 15-feature schema. The E11 "gated architecture
ablation — yellow verdict" commit (`c5fb047`, 2026-04-14) was run
against that stale schema and its findings are a pre-image of work that
had already merged to main. See
`runs/20260414-e11-gated-tier1-ablation/result.md` for the frozen
research context; the file is preserved as an append-only record per
the research workflow contract.

On 2026-04-15 14:37 a session committed `ccc2704`
(`docs/research/gliner_fastino/GLINER_REFERENCE.md`), a consolidated
reference guide for GLiNER as an upstream feature-provider. The commit
message §8 marks "GLiNER-as-feature" as *"not yet filed"* — the next
intended action. That filing never happened; the session crashed
before a new queue entry was written. No code changes from that
session were lost.

Recovery is deferred until Sprint 12 delivers and its shipped schema
state is stable on main, then executed by this memo.

---

## Pre-conditions

Same as the standard runbook, plus one:

1. Sprint 12 sprint-end commit has landed on `origin/main`.
2. `gh run list --workflow=ci.yaml --branch=main --limit 3` shows the
   top entry green against the sprint-end commit.
3. `docs/sprints/SPRINT12_HANDOVER.md` exists.
4. *(Sprint 12 specific)* Confirm the "DATE_OF_BIRTH_EU retirement"
   backlog item shipped — if it did, the recovery's queue.md
   annotation pass (Step 7) has an extra entry. If it did not, no
   change.

Do not proceed until all four are true.

---

## Recovery sequence

### Step 0 — Delete stale E11 follow-up files

Two files from the 2026-04-14 E11 follow-up session were never
committed and have been superseded. They are currently untracked in
the research worktree.

```bash
cd <research-worktree>
rm tests/benchmarks/meta_classifier/e11_per_class_diagnostic.py
rm docs/experiments/meta_classifier/runs/20260414-e11-gated-tier1-ablation/per_class_diagnostic.txt
```

**Why each is safe to delete:**

- `e11_per_class_diagnostic.py` is a pre-promotion version of
  `tests/benchmarks/meta_classifier/per_class_diagnostic.py`, which
  main already has as a committed utility (promoted during Sprint 11).
  The stale version imports `FEATURE_NAMES, Row, load_rows, make_lr`
  from `e11_gated_experiment`, which is tied to the 15-feature layout
  and would not run against the post-sync v3 schema.
- `per_class_diagnostic.txt` measured a 15-feature schema that no
  longer exists. The numbers in it (macro F1 0.2322, 10 classes at
  F1=0.000 despite 100% regex firing) are not interpretable under v3
  and would actively mislead anyone who found the file later.

Neither file contains insight that isn't already captured in
`runs/20260414-e11-gated-tier1-ablation/result.md`.

### Steps 1-6 — Standard sync ritual

Execute
[`research_branch_sync_runbook.md`](research_branch_sync_runbook.md)
in full, substituting `N=12` throughout.

**Expected conflict count for this specific sync: 1-3 files.**
- `docs/experiments/meta_classifier/queue.md` — guaranteed conflict,
  resolve with `git checkout --ours`.
- `scripts/train_meta_classifier.py` — very likely. The research
  branch has 15 lines of edits from M1 + Q6 work; main has Sprint 11
  pipeline changes for v2/v3 retraining. Standard three-way merge.
  If the conflict is messy, take `theirs` from main and file a
  research-side follow-up to re-apply the M1 CV methodology edits on
  top of the new pipeline.
- `tests/benchmarks/corpus_loader.py` — possible, append-only on
  both sides should auto-merge.

**Expected validation state:**
- Step 4a should report `schema v3, dim=46` (or whatever Sprint 12
  ships — bump the expected value in the runbook if it changed).
- Steps 4b-4d should pass cleanly. If 4c fails on a test that imports
  a 15-feature constant, that test was dropped or renamed on main —
  the research worktree is reading a stale test file that the sync
  just replaced. Refresh the worktree (`git clean -fd` untracked or
  restart the Python interpreter) and retry.

### Step 7 — Queue.md corrections (multi-sprint batch)

The standard runbook Step 5 asks for queue.md annotations for items
shipped in the latest sprint. For this sync specifically, multiple
sprints' worth of shipping has accumulated. Work through the queue
top-to-bottom and add `✅ SHIPPED` annotations for at least the
following entries (cross-reference against Sprint 9, 10, 11, and 12
handover docs for completeness):

- **E11 — Gated architecture** (queue.md line ~950)

  Current status: `✅ complete (see runs/20260414-e11-gated-tier1-ablation/result.md) — Yellow verdict`

  Add: `✅ SHIPPED TO PRODUCTION — Sprint 11 item 11-F (tier-1
  credential pattern-hit gate), commit bb1644f. Yellow verdict was
  an under-estimate of the gating benefit; production gating is now
  the default v3 path per Sprint 12 single-path classifier rollout.`

- **E11 follow-up "E12 candidate"** (in the E11 commit message, not
  a standalone queue entry)

  The dict-word-ratio + placeholder-run features referenced as an E12
  follow-up shipped as:
  - Sprint 11 item 11-D (dictionary-word-ratio feature, commit `d3d29d8`)
  - `fef2f12` (placeholder-credential validator + stopwords expansion)

  The E12 candidate as originally scoped is **obsolete**. Do not file
  it. Add a comment under the E11 entry noting this.

- **Q8 — Opaque-secret specialized meta-classifier** (line ~1208)

  Current status: `🟡 queued — Sprint 8 prerequisite satisfied; scope partially subsumed by Sprint 10 gated-architecture item`

  Verify whether Q8's opaque-secret angle is still distinct from
  what shipped in Sprint 11 v3. If the v3 classifier handles the
  opaque-secret case via the tier-1 gate + dict-word-ratio + Chao-1
  combination, mark Q8 as obsolete. If there is still an
  unaddressed gap (e.g., opaque secrets with high entropy and no
  dictionary words), keep it queued with a sharpened scope note.

- **Any other `🟡 queued` entries** whose "future direction" language
  is now shipped code on main. Cross-reference:
  - Sprint 9 handover (`project_sprint9_complete.md` in MEMORY)
  - Sprint 10 handover
  - Sprint 11 handover (family benchmark, v3 retrain, scanner tuning)
  - Sprint 12 handover (once it exists)

Budget 20-30 minutes for this pass. It is a one-time catch-up. Future
syncs annotate only the single sprint just delivered and should take
5-15 minutes.

### Step 8 — File the GLiNER-as-feature experiment

**Do not file this as part of the recovery.** Filing a new experiment
entry is design work — aggregation strategy (max / rate / presence /
count / mean / top-k per `GLINER_REFERENCE.md` §4), decoy-negative
label choice, F1 delta threshold that counts as a promotion signal —
and deserves a fresh session with full attention, not a tacked-on
step in a recovery sequence.

The inputs are already staged:
- `docs/research/gliner_fastino/GLINER_REFERENCE.md` §4 and §6 contain
  the knob settings and aggregation options.
- §8 of the same file lists "GLiNER-as-feature (not yet filed)" as
  Open Research Thread #1.
- After this recovery completes, the post-sync feature schema
  (`FEATURE_SCHEMA_VERSION == 3`, 46 slots) will be the correct
  baseline for the experiment.

File the entry in a dedicated planning session after this recovery
is complete and marked successful. The entry should slot into the
queue at the next unused `E{N}` number and reference the GLINER
reference guide as its design input.

---

## Success criteria

All of the following, checked off in order:

- [ ] Both stale E11 files deleted (Step 0)
- [ ] Standard runbook Steps 1-6 completed with all validation passing
- [ ] `FEATURE_SCHEMA_VERSION == 3` (or current main value) confirmed
  post-sync
- [ ] `pytest tests/ -v -x --ignore=tests/benchmarks/` fully green
- [ ] Family benchmark smoke run (Step 4d) completes
- [ ] Queue.md annotations for E11 landed and committed
- [ ] Q8 scope resolved (obsolete OR sharpened)
- [ ] Research branch pushed to `origin/research/meta-classifier`
- [ ] GLiNER-as-feature entry noted as "next session, not this one"
- [ ] This recovery file deleted (`git rm docs/process/research_sync_sprint12_recovery.md`)

When all boxes check, `git commit -m "chore(research): complete Sprint 12 recovery — delete one-time memo"` and push.

---

## If anything goes wrong

Rollback via the tag (runbook Step 6 standard procedure):

```bash
git reset --hard research/pre-sprint12-sync
git push origin research/meta-classifier --force-with-lease
```

File a blocker with:
- Which recovery step failed (Step 0 / Steps 1-6 / Step 7 / Step 8)
- Full error output
- `FEATURE_SCHEMA_VERSION` on research vs main
- Whether any other research session was active during the sync

Research experiments can continue on the pre-sync state (`ccc2704`)
until the issue is resolved. The stale schema is safe for
investigations that do not touch feature engineering — Q-series
methodology work, corpus diversity analysis, descriptive statistics,
and the Pass-2 GLiNER context experiments on
`research/gliner-context` are all unaffected.
