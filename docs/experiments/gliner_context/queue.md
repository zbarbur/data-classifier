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
| S1 | NL prompt construction (column + table + description sentence, prefix + per-value variants) | 🟢 Pass 1 SHIP-GATE PASS, proceeding to Pass 2 | gliner-context session 2026-04-13 | 2026-04-13 | Pass 1 n=315: Δ +0.0887 at threshold 0.8, BCa CI [+0.050, +0.131] excludes +0.02 gate. Uniform lift across empty/helpful/misleading. Pass 2 on Nemotron-PII next; final verdict still gated on Gretel-EN. See `runs/20260413-2300-pass1/result.md` |
| S2 | Per-column dynamic label descriptions | ❌ DO NOT SHIP (refuted Pass 1) | gliner-context session 2026-04-13 | 2026-04-13 | Catastrophic at threshold 0.7: Δ −0.0603, CI [−0.084, −0.040], McNemar (b=39, c=0) p=0.0000. Zero columns where S2 helps, 39 where it hurts. Mechanism: injecting column context into per-label descriptions creates internal prompt contradictions that corrupt GLiNER's label semantics. Latency +25% also exceeds gate. Do not re-propose without addressing the mechanism. See `runs/20260413-2300-pass1/result.md §"S2 per-column descriptions"` |
| S3 | Label narrowing via column-name pre-selection (naive keyword) | ❌ REFUTED in current form | gliner-context session 2026-04-13 | 2026-04-13 | Δ F1 CI spans 0 at all thresholds; McNemar (b=15, c=3) at threshold 0.5 goes WRONG direction. Bimodal (helpful +0.076, misleading −0.039) — keyword hinter too naive to discriminate. Superseded by S3b. |
| S3b | Confidence-gated label narrowing (only narrow when column_name_engine hint confidence ≥ 0.70) | 🟡 queued | — | — | Follow-up on Pass 1 S3 refutation. Hypothesis: confidence gate captures +0.076 helpful lift while avoiding −0.039 misleading penalty. Needs column_name_engine integration, not just a keyword match. |
| S4 | data_type pre-filter | ⏸ deferred | — | — | Handled directly in Sprint 9 main backlog, not in this research track |
| S5 | Description tokens as additional labels | ⏸ deferred | — | — | Lowest priority; only if S1–S3 all ship and sprint time remains |
| S1b | Shorter NL prompt variant (`{col}@{tbl}: v1, v2, ...`) | 🟡 queued | — | — | Ablation on S1 — is it the sentence structure or just "any prefix"? Cheap to measure once Pass 2 confirms S1. |
| P2 | Nemotron-PII cross-corpus validation of S1 (fastino, thr=0.8, 3 seeds) | 🟡 queued | — | — | Fulfills "holds on ≥2 corpora" ship gate without waiting for Gretel-EN. Corpus already cached at 603MB, `NEMOTRON_TYPE_MAP` already exists. |
| P1b | Re-run McNemar with corrected correctness bit (`predicted == {GT}`) | 🟡 queued | — | — | Cheap — uses cached per_column_thr*.json, no re-inference. Addresses the McNemar/bootstrap divergence documented in Pass 1 methodological note. |

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
