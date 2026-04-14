# Fail-Fast Stretch-Item Dispatch Protocol

> **Status:** standard. Adopt for every stretch item dispatched to an agent.
> **Origin:** Sprint 10 lesson #3 — fastino promotion revert (commit `7aafa01`).
> **Last updated:** 2026-04-14.

## TL;DR

**Stretch items fail fast; core sprint items fix forward.** When you dispatch a stretch item to a subagent, the prompt must say "if gates fail, REVERT the code and file a Sprint N+1 item — do NOT attempt to fix." The agent's job is to measure, not to salvage.

This doc is the playbook. It exists because Sprint 10's fastino promotion validated the pattern: dispatch → fail at the gate → revert → file retry → total main-session cost ~5 minutes. Without the fail-fast instruction, the same failure would have burned hours of back-and-forth on a structurally broken approach.

## When to use

Use this protocol for **stretch items only**:

- The item is a measurable bet (promotion, threshold bump, architecture swap) with pre-committed accept/reject gates.
- The primary risk is "this hypothesis is wrong" — not "the implementation is buggy."
- Rollback is cheap (`git reset` or revert one commit) and does not leave the repo in a broken state.
- The sprint will still close successfully if this item fails.

**Do NOT use this protocol for core sprint items.** Core items are committed deliverables — if they fail at the gate, the response is "diagnose and fix," not "revert and reschedule." Stretch items are opt-in risk; core items are not.

### Stretch vs core — quick test

| Question | Stretch | Core |
|---|---|---|
| Is this item in the sprint's headline deliverables? | No | Yes |
| Did the user explicitly mark it as stretch / nice-to-have? | Yes | No |
| Does the sprint's success story depend on it? | No | Yes |
| Is the hypothesis unproven on production data? | Usually | Sometimes |
| If it lands in Sprint N+1 instead of Sprint N, is anyone blocked? | No | Maybe |

If two or more answers fall in the **Stretch** column, dispatch it fail-fast.

## Dispatch prompt template

Copy this template when dispatching a stretch item. The `REVERT PROTOCOL` block is the load-bearing part — do not delete or soften it.

```
TASK: {one-sentence description of the change}

CONTEXT:
- {what the hypothesis is}
- {where the research / pre-work lives}
- {what artifacts you're applying: patch file, config diff, etc.}

ACCEPT/REJECT GATES (pre-committed, non-negotiable):
- Gate A: {benchmark metric} delta ≥ {threshold} on {corpus}
- Gate B: {benchmark metric} delta ≥ {threshold} on {corpus}
- Gate C: full test suite passes (no new failures)
- Gate D: {any additional quality gate — lint, format, specific integration test, etc.}

INSTRUCTIONS:
1. Apply the change as described.
2. Run the accept/reject gates in order. Report the raw numbers.
3. If ALL gates pass: commit, push, report success, stop.
4. If ANY gate fails: follow the REVERT PROTOCOL below. Do NOT attempt to tune,
   fix, or iterate. Do NOT "try one more thing."

REVERT PROTOCOL (run on first gate failure):
1. Dump the failure evidence: which gate, the delta, the top 10 FP/FN rows
   from the failing benchmark, and any new test failures. Save to a scratchpad
   in the prompt response — do NOT commit the dump.
2. `git reset --hard` back to the dispatch-start SHA. Verify the working tree
   is clean.
3. Write a Sprint N+1 retry YAML (do NOT stage it — leave it untracked for the
   main session to pick up) containing:
   - What was tried
   - The gate numbers that failed
   - The hypothesis for WHY it failed (structural vs. tunable)
   - Recommended next attempts (ranked, most-likely-to-succeed first)
4. Report "REVERTED at gate {X}" with the failure summary and the path to the
   untracked YAML. Stop.

DO NOT:
- Commit broken code "for debugging"
- Push a failing branch for someone else to fix
- Tune thresholds or swap models to make the gates pass
- Spend more than one round-trip on diagnosis
```

### Why the template is rigid

Each clause has a story behind it:

- **"Do NOT attempt to tune, fix, or iterate"** — Without this, agents default to the engineering reflex of "make the red number green." On a structurally broken hypothesis, this burns the sprint.
- **"Do NOT stage the retry YAML"** — Keeps the revert a true revert. The main session decides whether the retry is worth Sprint N+1 scope; the agent doesn't get to auto-schedule its own follow-up.
- **"Do NOT spend more than one round-trip on diagnosis"** — The agent is measuring, not salvaging. A second round-trip is a sign the protocol has been abandoned.
- **"Save the FP/FN dump to the response, not to a commit"** — The dump is evidence for the retry YAML, not a code artifact. Committing it pollutes the history.

## Sprint N+1 filing template

When the main session picks up a reverted stretch item, file the retry YAML using this template. The key discipline: **the retry YAML must cite the failure magnitude and state the structural hypothesis.** If you can't state a structural hypothesis, the retry is premature — file it as research, not as a backlog item.

```yaml
id: {short-slug}-retry
title: "{original title} — retry with {new approach}"
status: backlog
priority: P2       # P2 unless the original was P0/P1 and still is
category: feature  # or whatever the original was
sprint_target: {N+1}
complexity: M      # usually M: re-dispatch + evaluate is not S

goal: |
  Retry {original change} after the Sprint {N} attempt failed at {gate X}
  with a {delta magnitude} regression. Try {new approach} to address the
  structural issue: {one-sentence hypothesis for why it failed}.

technical_specs:
  - "Sprint {N} failure evidence: {benchmark metric} delta {value}, dominant
     failure mode {mode}."
  - "Preserved artifacts: {patch path, research memo path}."
  - "Structural hypothesis: {why the previous approach failed in prod but
     worked in research}."
  - "Retry approach: {specific, ranked list of changes to make — threshold,
     suppressor, prompt variant, etc.}"

acceptance_criteria:
  - "All original accept/reject gates from Sprint {N} pass"
  - "{Any new gate specific to the retry approach}"
  - "If retry fails, REVERT and document — do NOT iterate"  # fail-fast sticks

test_plan:
  - "Same benchmark run as Sprint {N}"
  - "Re-run any integration tests that broke in Sprint {N}"

notes: |
  This is a retry of {original item id} from Sprint {N}. See
  docs/sprints/SPRINT{N}_HANDOVER.md section "{section name}" for the full
  failure evidence. The preserved patch at {path} is the starting point.
```

### The "preserve the patch" rule

When a stretch item reverts, **preserve the patch file** in `docs/research/` (or wherever the pre-work lives). Do NOT delete it from the working tree. Two reasons:

1. The retry starts from the patch, not from scratch. Regenerating a 200-line patch because the original was cleaned up is wasted work.
2. The patch is evidence: anyone auditing "why did Sprint N+1 attempt X again?" should be able to see exactly what Sprint N tried.

Sprint 10 preserved `docs/research/gliner_fastino/fastino_promotion_draft_20260414.patch` for exactly this reason; the Sprint 11 retry item references it directly.

## Worked example — Sprint 10 fastino promotion

This is the canonical case. Read it before dispatching your next stretch item.

### Setup

- **Item:** `promote-gliner-tuning-fastino-base-v1` (wave 3 stretch on Sprint 10).
- **Hypothesis:** Swapping `_MODEL_ID` from `urchade/gliner_multi-v2.1` to `fastino/gliner2-base-v1`, raising `_DEFAULT_GLINER_THRESHOLD` to 0.80, and applying PERSON_NAME/SSN label swaps would lift blind-corpus F1 by ~+0.04 (the Pass 1 research signal from `research/gliner-context`, measured on the empty-context Ai4Privacy stratum at n=315).
- **Pre-work:** Patch file at `docs/research/gliner_fastino/fastino_promotion_draft_20260414.patch`, ready to apply on top of Sprint 10 items #1 + #2.
- **Gates:** Gretel-EN blind ≥ baseline − 0.005; Nemotron blind ≥ baseline − 0.005; full test suite green.

### Dispatch

The main session dispatched a fresh subagent with the fail-fast template filled in. The prompt explicitly said "if gates fail, REVERT and file a Sprint 11 retry YAML — do NOT attempt to fix."

### Measurement

Agent applied the patch, ran the benchmarks, and measured:

- **Gretel-EN blind:** 0.611 → 0.413 (delta **−0.198**, gate −0.005) ❌
- **Nemotron blind:** 0.821 → 0.526 (delta **−0.295**, gate −0.005) ❌
- **Integration tests:** Two new failures (`test_invalid_dates_rejected[32/13/2000]` and `test_sin_luhn_validates_formatted_and_unformatted`) from fastino firing PHONE@0.92+ on numeric tokens.

Both primary gates failed by ~40× the threshold. This is not a "close to the gate, let me tune" failure — this is a structural wrong-turn.

### Diagnosis (one round-trip only)

The agent dumped the top FP/FN rows and identified the dominant failure mode:

> Fastino fires PHONE at 0.92+ confidence on numeric-looking columns (ABA_ROUTING, BANK_ACCOUNT, CREDIT_CARD, HEALTH, VIN), and the orchestrator's cross-engine dedup suppresses the correct regex-engine findings in favor of the more-confident PHONE.

This is structural: the model binds numeric token sequences to PHONE regardless of context. No threshold can fix it without losing real PHONE recall. The research-stratum signal was real, but it was measuring a non-transferable effect size.

### Revert

`git reset --hard` to the dispatch-start SHA. Zero commits touched `gliner_engine.py`.

### Sprint 11 retry YAML (filed, not staged)

Agent left `backlog/fastino-promotion-retry-investigate-s1-variant-b-always-wrap-fallback-to-close-blind-corpus-regression.yaml` untracked. The main session picked it up in Sprint 11 planning. The YAML cites the −0.198/−0.295 failure magnitudes, names the structural hypothesis ("attention-based NER needs grammatical scaffolding; numeric tokens have none"), and ranks the retry approaches: (a) S1 variant B "always-wrap even on metadata-free inputs," (b) higher fastino threshold (0.85–0.90), (c) hard PHONE suppressor for fastino on numeric `data_type` columns, (d) Pass 2 research run on post-S1 Gretel-EN + Nemotron before the next promotion attempt.

### Cost accounting

- **Main-session time:** ~5 minutes (dispatch + read report + move item back to backlog).
- **Agent time:** ~15 minutes (apply patch + run two benchmarks + dump evidence + write retry YAML).
- **Code debt:** zero. Working tree clean.
- **Lost work:** zero. The patch is preserved for retry.

Compare this to the counterfactual: without the fail-fast instruction, the same failure would have triggered threshold tuning, model swap attempts, and integration-test quarantine. Sprint 10's other 6 items would have been starved of attention. The fail-fast protocol paid for itself in the first attempted use.

## Anti-patterns

These are the failure modes the protocol prevents. Recognize them and reject them:

1. **"Let me just try one more thing"** — You're one round-trip in; stop. A second round-trip is a signal that you're salvaging, not measuring.
2. **"I'll commit this broken state so someone else can debug"** — No. Revert. The broken state is not a deliverable; the measurement is.
3. **"The gate is only slightly off, let me tune"** — Tuning is fine for core items. For stretch items, tuning defeats the purpose of the gate. If the gate was the wrong threshold, fix the gate in Sprint N+1, not the code in Sprint N.
4. **"The test failures are unrelated, I'll skip them"** — New test failures from a stretch item are gate failures. Skipping them launders broken state past the protocol.
5. **"I'll stage the retry YAML so it's not forgotten"** — No. The main session owns Sprint N+1 scope. Untracked files are the contract.
6. **"This is so close, let me extend the sprint"** — If a stretch item needs a sprint extension, it wasn't a stretch item. Revert and re-file.

## Integration with sprint workflow

- **Sprint start** — Label stretch items in the sprint YAML with a `stretch: true` marker (or tag). The main session uses the marker to decide whether to apply this protocol on dispatch.
- **Sprint mid** — When dispatching a stretch item, copy the dispatch prompt template and fill in the gates. Do NOT omit the REVERT PROTOCOL block.
- **Sprint end** — Reverted stretch items show up in the handover doc under "Attempted, reverted" with their failure magnitudes. The retry YAML (if any) is listed under "Sprint N+1 candidates."

## Cross-references

- `docs/sprints/SPRINT10_HANDOVER.md` — Sprint 10 handover, sections "6. Fastino promotion (wave 3 stretch)" and "Lessons learned #3" (the origin of this doc).
- `docs/research/gliner_fastino/fastino_promotion_draft_20260414.patch` — the preserved patch (example of the "preserve the patch" rule).
- `backlog/fastino-promotion-retry-investigate-s1-variant-b-always-wrap-fallback-to-close-blind-corpus-regression.yaml` — the worked-example retry YAML.
- `docs/process/SPRINT_START_CHECKLIST.md` and `docs/process/SPRINT_END_CHECKLIST.md` — where stretch-item labeling and reporting plug in.
