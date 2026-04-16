# Multi-Label Architecture — Library Philosophy

> **Status:** Research-side articulation of the philosophy decided
> 2026-04-16 during the Sprint 12 safety-audit outcome discussion.
>
> **Promotion action (Sprint 12 close-out):** This memo should be
> promoted to `docs/spec/10-multi-label-architecture.md` as part of
> the Sprint 12 close session. The research-branch location here is
> temporary pending that promotion. When promoted, delete this file
> and update the cross-reference in
> `research/prompt-analysis:docs/experiments/prompt_analysis/queue.md`
> to point at the spec location.
>
> **Scope:** library-wide — both `research/meta-classifier` (structured
> data) and `research/prompt-analysis` (prompt analysis) branches
> inherit this commitment.
>
> **Decided:** 2026-04-16
>
> **Evidence base:** the Sprint 12 Phase 5b safety audit
> ([docs/research/meta_classifier/sprint12_safety_audit.md on
> `sprint12/main`](meta_classifier/sprint12_safety_audit.md)), which
> returned a RED verdict on the proposed flat-softmax directive
> promotion and identified the softmax-is-wrong-primitive structural
> finding.

---

## §1 — Domain truth: multi-label is fundamental

For the data_classifier library's domain — sensitive-data detection in
structured data sources and in prompts — multi-label is not a
"modeling convenience" or a "representation choice." It is the reality
of the domain:

- A single chat-message value legitimately contains
  `{PHONE, PERSON, ORG, FREE_TEXT}` in parallel.
- A column of customer complaints contains
  `{PERSON, COMPANY, DATE, MONETARY}` at varying rates per row.
- A log column contains `{UUID, URL, TIMESTAMP, FILE_PATH, IP_ADDRESS}`
  per row.
- A user prompt can legitimately express `{summarize, translate}` or
  `{data_processing, knowledge_request}` as parallel intents.

Single-label was always a training-convenience reduction, not a
truthful model of the domain. Sprint 12's safety audit produced the
definitive evidence: flat softmax on v5 produced confidently-wrong
single-class predictions on 3 of 6 heterogeneous fixtures (base64
payloads → `VIN` @ 0.934, chat messages → `CREDENTIAL` @ 1.000, Kafka
event stream → `CREDENTIAL` @ 0.999). The failure was not tunable
because the primitive itself forces "exactly one of K classes is true"
— a statement that is false for any column containing multiple entity
types.

**The commitment:** multi-label is the library's architectural truth
for as long as the library exists. Future sprints may disagree on
*how* to represent, compute, or evaluate it — but not on *whether* it
exists.

---

## §2 — Library contract: `list[Finding]` is authoritative

The library's public API returns `list[ClassificationFinding]` per
column (for the structured branch) and will return a corresponding
list-shaped output for prompt analysis (intents × zones × content).
**This shape is the authoritative output. No rollup is the library's
business.**

**No winner.** If 3 findings are all true, all 3 are reported. The
library does not owe the consumer a single "winning" finding. That is
a rollup decision the consumer makes for their own reporting schema.
A consumer's choice to surface `findings[0].family` in their reporting
table is a **subscriber pattern**, not a library contract.

**Consumer convenience helpers** (`top_finding()`, `dominant_family()`,
etc.) may exist but must be clearly labeled as subscriber conveniences,
not authoritative answers. The library's job is detection; the
consumer's job is rollup.

**API evolution principle:** any future change that collapses findings
before returning to the consumer — threshold filtering, deduplication,
family aggregation, argmax-style winner selection — is a **breaking
API change** and requires a public API contract update. The list stays
authoritative.

---

## §3 — Scope matters: when is single-label appropriate?

The "softmax is wrong primitive" finding applies at the **column
level**. It does NOT mean specialist single-label classifiers are
invalid everywhere.

**Multi-label is fundamental at the column scope.** A column can
contain multiple entity types. Any classifier that claims "exactly one
of K classes is true for this column" is architecturally wrong.

**Single-label may be appropriate at narrow sub-task scope.** For
narrow sub-tasks where labels ARE mutually exclusive per item, softmax
is the right primitive:

- **Per-value classification with mutually-exclusive labels.** Given a
  single high-entropy string, is it an `API_KEY` or a `SHA_HASH` or a
  `UUID` or a `BASE64_PAYLOAD`? A string is one thing. Softmax is
  valid here.
- **Branch-internal routing decisions.** Given a column already routed
  to the `opaque_tokens` branch by the Sprint 13 column-shape router,
  which credential subtype does this column most resemble? The branch
  has already narrowed the scope to mutually-exclusive subtypes.

### Three criteria for introducing a specialist classifier inside a router branch

1. **Training data exists in sufficient quantity** for the specialist's
   narrow task.
2. **The specialist's task is narrow enough that single-label is
   valid** — per-value, mutually exclusive labels, no multi-label
   ambiguity at the sub-task scope.
3. **The specialist is measurably better than the simpler baseline**
   (heuristic, existing tool) on a held-out test set for the branch.

### What §3 forbids

- Replacing the multi-label architecture with a fleet of specialists
  that **collectively re-impose single-label at the column level**.
  (This is the Sprint 12 retired framing — see §5.)
- Claiming specialists are "the architecture" rather than "tools
  within the architecture."

### What §3 allows

- **Specialist credential classifier inside the `opaque_tokens` router
  branch** (Q8's sharpened scope on the research queue), if the three
  criteria are met. Training data exists (gitleaks / secretbench /
  detect_secrets / Sprint 10 harvest). The task is narrow and
  mutually-exclusive (API_KEY vs PRIVATE_KEY vs PASSWORD_HASH vs
  OPAQUE_SECRET vs NOT_SECRET, per-value). Measurability against the
  current heuristic baseline is straightforward.
- **Further-specialized classifiers inside the `structured_single`
  branch.** Sprint 12 Q2's +0.1031 LOCO delta on hard-gated CREDENTIAL
  vs not suggests internal family splits could yield further lift.
  Sprint 14+ investigation candidate under the §3 criteria.
- **Per-value multi-label NER** like GLiNER running span extraction
  inside the `free_text_heterogeneous` branch. GLiNER is a specialist
  *multi-label* tool — appropriate because the task (per-value span
  extraction) is itself multi-label at its scope.

---

## §4 — Cross-branch: applies to prompt-analysis too

The multi-label commitment is **library-wide**. Both research branches
inherit it:

- **`research/meta-classifier`** (structured data detection):
  covered by §1-3. The Sprint 13 column-shape router embraces
  multi-label via `list[ClassificationFinding]`; specialist classifiers
  live inside router branches where the §3 criteria are met.

- **`research/prompt-analysis`** (prompt intent / zones / risk
  engine): intent classification must commit to multi-label **from
  Day 1** — before any classifier work begins. A prompt can
  legitimately express parallel intents (`{summarize, translate}` or
  `{data_processing, knowledge_request}`). Forcing argmax-one-winner
  would reproduce the exact Sprint 12 mistake in a different domain.
  The prompt-analysis queue declares this commitment at its
  Architectural commitments section, pre-empting the Stage 0 label-set
  design from accidentally committing to single-label.

**Risk engine implication.** The risk engine's cross-correlation logic
(content × intent × zone) gets cleaner when all three dimensions are
multi-label: the risk verdict is a function over three parallel lists,
not three winners. A detection of `{SSN in content, data_extraction in
intent, customer_support_context in zone}` is richer than any single
"winning" label from each dimension.

---

## §5 — Relationship to the Sprint 12 retired item

The backlog item
`gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation`
was retired 2026-04-16 on structural grounds as part of the Sprint 12
close (commit `407d4a5` on `sprint12/main`). The retirement reason is
sometimes mis-summarized as "specialists are wrong." **That is not the
correct summary.**

**What was actually retired:** the *framing* that specialist
classifiers collectively form the architecture, replacing flat v5.
Under that framing, the architecture still re-imposed single-label
mutual exclusivity at the column level — the winning stage-2
classifier's softmax picked a single class, just as v5 did, so the
heterogeneous-column failure mode was not addressed. The Sprint 12
RED verdict on v5 would have reproduced on this architecture.

**What was NOT retired:** specialist classifiers as **tools inside a
multi-label architecture**. The Sprint 13 column-shape router IS that
architecture. A specialist credential classifier inside its
`opaque_tokens` branch is a valid Sprint 14+ candidate under the §3
criteria. Q8's sharpened scope on the research queue captures this.

### Retirement pointer fix — to-do for Sprint 12 close session

The backlog YAML at
`backlog/gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation.yaml`
should be updated to carry the following fields during the Sprint 12
close session (this memo cannot write to `backlog/` from the research
branch per the file-ownership contract):

```yaml
status: retired
retired_on: 2026-04-16
superseded_by:
  - sprint13-column-shape-router
  - sprint13-per-value-gliner-aggregation
  - sprint13-opaque-token-branch-tuning
supersede_reason: >
  Original framing replaced flat v5 with 3 specialist classifiers as
  the architecture, which would have re-imposed single-label mutual
  exclusivity at the column level and reproduced the same RED verdict
  on heterogeneous columns that Sprint 12's safety audit found on flat
  v5. Multi-label is domain-fundamental per the
  multi_label_architecture_philosophy memo. Specialist classifiers
  remain viable as TOOLS INSIDE the router architecture (per memo §3)
  — see Q8 on the research queue for the specialist-credential
  candidate within the `opaque_tokens` branch as a Sprint 14+
  investigation under the §3 criteria.
superseded_by_memo: docs/spec/10-multi-label-architecture.md
```

The `superseded_by_memo` pointer should be written once this memo is
promoted to the spec location. Until then, point at the research-side
location (`docs/research/multi_label_philosophy.md` on
`research/meta-classifier`).

---

## Summary

| Claim | Status |
|---|---|
| Multi-label is fundamental at the column level | **Committed** (§1) |
| `list[Finding]` is the authoritative library output | **Committed** (§2) |
| No rollup is the library's business | **Committed** (§2) |
| Specialist classifiers inside router branches are valid | **Committed** (§3) |
| Specialist classifiers AS the architecture are invalid | **Committed** (§3, §5) |
| Prompt-analysis branch inherits the same commitment | **Committed** (§4) |
| Risk engine cross-correlation uses multi-label dimensions | **Implied** (§4) |
| Retirement YAML pointer fix | **To-do for Sprint 12 close** (§5) |
| Promotion of this memo to `docs/spec/` | **To-do for Sprint 12 close** (header) |
