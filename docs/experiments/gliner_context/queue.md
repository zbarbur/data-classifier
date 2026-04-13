# GLiNER context injection — research queue

> **Scope:** Can we improve GLiNER's structured-data classification by
> injecting table / column / dataset / description context into its input?
>
> **Branch:** `research/gliner-context` (off `main`, worktree at
> `/Users/guyguzner/Projects/data_classifier-gliner-context`)
>
> **Contract:** see project memory `project_research_workflow.md`.
> Research sessions write here, never promote to main. Promotion happens
> through a separate Sprint 10 backlog item.

## Status legend

- 🔴 blocked — upstream dependency missing
- 🟡 queued — ready to dispatch
- 🟢 in progress — session active, do not race
- ✅ complete — result memo merged
- ⏸ deferred — paused, see notes

## Entries

| ID | Strategy | Status | Owner | Started | Notes |
|---|---|---|---|---|---|
| S1 | NL prompt construction (column + table + description sentence, prefix + per-value variants) | 🟢 in progress | gliner-context session 2026-04-13 | 2026-04-13 | v1 model OK as a floor; v2 fastino needed for final measurement once `promote-gliner-tuning-fastino-base-v1` lands |
| S2 | Per-column dynamic label descriptions | 🔴 blocked | — | — | Gated on Sprint 9 `promote-gliner-tuning-fastino-base-v1` (v1 API treats descriptions statically) |
| S3 | Label narrowing via column-name pre-selection | 🟡 queued | — | — | Will start after S1 harness is proven |
| S4 | data_type pre-filter | ⏸ deferred | — | — | Handled directly in Sprint 9 main backlog, not in this research track |
| S5 | Description tokens as additional labels | ⏸ deferred | — | — | Lowest priority; only if S1–S3 all ship and sprint time remains |

## Measurement gate (SHIP criteria, same for every strategy)

- Macro F1 on Gretel-EN blind set lifts by **≥ +0.02**
- No individual entity-type regresses by more than -0.03 F1
- Latency penalty ≤ +20% per-column
- McNemar p < 0.01 on blind set
- Holds on at least TWO distinct corpora (Gretel-EN + synthetic acceptable)

If any gate fails → DO NOT SHIP verdict, memo explains why, file nothing
for Sprint 10.

## Baseline citation rule

When citing any meta-classifier F1 delta, use **+0.191** (honest E10
baseline) not +0.257. See memory `project_active_research.md` for the
full explanation.
