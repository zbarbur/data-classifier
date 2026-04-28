# Multi-Label Architecture — Library Philosophy

> **Status:** Canonical specification — library-wide architectural commitment.
>
> **Decided:** 2026-04-16 (Sprint 12 safety-audit outcome).
>
> **Promoted to spec:** 2026-04-28 (Sprint 17). Source memo at
> `docs/research/multi_label_philosophy.md` on `research/meta-classifier`
> deleted as part of the same promotion to prevent post-sync drift.
>
> **Scope:** library-wide. Both `research/meta-classifier` (structured-data
> detection) and `research/prompt-analysis` (prompt analysis / WASM
> detector) inherit this commitment, as do all consumers of the public
> Python API (`classify_columns`, `scan_text`).
>
> **Evidence base:** the Sprint 12 Phase 5b safety audit
> ([`../research/meta_classifier/sprint12_safety_audit.md`](../research/meta_classifier/sprint12_safety_audit.md)),
> which returned a RED verdict on the proposed flat-softmax directive
> promotion and identified the softmax-is-wrong-primitive structural
> finding.
>
> **Open follow-up:** §5 retirement-YAML pointer fix on
> `backlog/gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation.yaml`
> — see §5 below for the YAML payload.

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

### Retirement pointer fix — open follow-up

The backlog YAML at
`backlog/gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation.yaml`
should carry the following fields (open follow-up tracked on the
Sprint 17 backlog item that promoted this spec):

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
superseded_by_memo: docs/spec/11-multi-label-architecture.md
```

---

## §6 — Practical scoping: where softmax shines and what multi-label approaches exist

The multi-label commitment at the column scope (§1) does NOT imply
softmax is wrong everywhere. This section is the practical companion
to §1-§5 — without it, future sprints could over-correct away from
legitimate softmax uses.

### §6.1 — Where softmax is right (and we keep using it)

Softmax is the right primitive when the scope of the decision is
genuinely "one of K mutually exclusive things." That is not rare; it
is the norm at narrow scopes.

Five cases where softmax is the honest choice:

1. **Single-class-per-column by construction.** Schema-typed columns
   (`ssn VARCHAR(11)`, `email_address STRING`) where every non-null
   value is unambiguously one entity type. Sprint 12's v5 at 0.9943
   in-distribution macro F1 is exactly this case — it wins cleanly
   when columns are genuinely single-class.

2. **Per-value classification with mutually-exclusive labels.** Given
   a single high-entropy string, *is* it API_KEY or SHA_HASH or UUID
   or BASE64_PAYLOAD? A string is one thing. Sprint 14+ Q8's
   specialist credential-subtype classifier operates here — exactly
   the §3 pattern.

3. **Fine-grained sub-classification inside a committed parent.**
   Once a prompt is multi-label-tagged at the top level
   (`data_processing`), "which task-type child — `summarize` vs
   `translate` vs `rewrite`?" is single-label per tag. The
   prompt-level decision is multi-label; per-tag task-type refinement
   is single-label.

4. **Well-represented classes + low calibration-sensitivity.** When
   each class has hundreds of training examples and we care about
   rank-1 winner rather than absolute probability magnitudes, softmax
   is honest — its class-competition is matched by the actual
   decision boundary.

5. **Auditability beats accuracy.** LR over K features is debuggable
   (feature importances interpret cleanly); multi-label neural nets
   are not. For production classification flows that legal /
   compliance teams need to explain, LR-on-narrow-scope beats any
   fancier multi-label model.

**Net:** softmax is not "wrong" — it is **the right tool at narrow
single-label scope, and wrong at multi-label column scope**. The
router architecture routes to it where appropriate (per §3) and
routes away from it where inappropriate (free-text heterogeneous
columns → per-value GLiNER, not v5).

### §6.2 — Taxonomy of multi-label approaches

Multi-label approaches span three layers that compose independently:
output representation, learning approach, architectural pattern.

**Layer 1 — Output representation:**

| Approach | What it does | Honesty |
|---|---|---|
| Argmax softmax | One class wins | ❌ false at column scope |
| Threshold softmax | All classes above T | ⚠️ dishonest — sum=1 couples threshold to K |
| Sigmoid-per-class | K independent probabilities | ✅ honest |
| Power set (label combinations) | Treat combinations as classes | ⚠️ combinatorial explosion |
| List of findings | Structured list output | ✅ honest — what the cascade already does |

**Layer 2 — How to learn multi-label:**

| Approach | Description | Training data needed |
|---|---|---|
| Binary Relevance (BR) | K independent binary classifiers, one per class | Multi-label labels |
| Classifier Chains (CC) | BR + label-order dependency | Multi-label labels |
| Multi-label neural net | Shared encoder + sigmoid output, binary-cross-entropy loss | Multi-label labels, lots of data |
| Per-value decomposition | Classify each value single-label, aggregate per column | **Single-label per-value** (what we have) |
| Embedding + nearest-neighbor | Encode columns, top-K similarity against labeled exemplars | Unlabeled corpus + small gold set |

**Layer 3 — Architectural patterns:**

| Pattern | Description | Our status |
|---|---|---|
| Cascade | Ensemble of specialists, each single-label, union output | **Current** — produces `list[Finding]` |
| Router (Sprint 13) | Heuristic gate → per-branch tool | **Next** — column-shape router |
| Multi-label meta-classifier | Single trained model, column → multi-label | **Research bet** (Sprint 15+) |
| Hybrid (router + per-branch multi-label) | Router picks, each branch uses appropriate primitive | **Emerges from Sprint 13** |

### §6.3 — Constraints that shape our practical choices

Four constraints eliminate most of the theoretical menu:

1. **Training data is single-label.** Existing corpora (gitleaks,
   secretbench, detect_secrets, Gretel-EN, Gretel-finance,
   openpii-1m, Nemotron) label one entity type per value / row. Pure
   BR / CC / multi-label-NN at the column level requires multi-label
   labeling we don't have and haven't committed to building.

2. **Auditability matters for BQ.** Compliance-reviewable output
   requires interpretable primitives. Multi-label neural nets fail
   this bar; LR per narrow scope doesn't.

3. **Latency budget is tight (BQ batch workloads).** Per-value
   decomposition is N× inference cost — known cost, acceptable.
   Multi-label neural inference adds unknown cost at unknown
   accuracy lift.

4. **We already have list-output infrastructure.** The cascade
   produces `list[Finding]`. We should *compose* it with better
   per-branch tools, not *replace* it with a single monolithic model.

### §6.4 — Practical roadmap

- **Sprint 13 (committed):** router + per-value decomposition
  (Layer 3 hybrid, Layer 2 per-value decomposition). Uses what we
  have, produces multi-label output honestly, requires no new
  training.
- **Sprint 14 candidate:** specialist classifiers inside router
  branches (per §3 criteria). v5 already serves `structured_single`;
  Q8 specialist for `opaque_tokens` if §3 criteria pass on real
  evidence.
- **Sprint 15+ research bet:** Binary Relevance sigmoid-per-class
  meta-classifier (Layer 2 BR) on multi-label-labeled data, **only
  if** we invest in multi-label labeling infrastructure. Evaluated
  against router + single-label baseline on multi-label metrics
  (defined by a future M4 research item). Replaces the router
  architecture only if it wins on multi-label metrics.
- **Long-term research (no commitment):** embedding + nearest-
  neighbor (Layer 2 embedding). Pure research bet — no blocker on
  short-term roadmap.

### §6.5 — Key design principles

- **Scope the decision before picking the primitive.** Softmax is
  right at narrow scope; wrong at column scope. The question is never
  "softmax or multi-label?" in the abstract — it is always "what
  scope is this decision at?"
- **Multi-label approaches are orthogonal on three layers.** Output
  representation, learning approach, and architectural pattern
  compose independently. A multi-label architecture can use
  single-label classifiers at narrow scope (what Sprint 13 does).
- **Our constraints point to the hybrid router pattern, not a
  monolithic multi-label model.** Sprint 13's architecture is the
  practical answer to the Sprint 12 structural finding.
- **Future research bets on "true" multi-label classifiers are
  real** but gated on (a) multi-label labeling investment and
  (b) M4 research item defining evaluation metrics. They are NOT
  required to ship the Sprint 13 architecture.

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
| Softmax is the right primitive at narrow scope | **Committed** (§6.1) |
| Multi-label approaches span three composable layers | **Documented** (§6.2) |
| Our constraints point to hybrid router, not monolithic multi-label | **Documented** (§6.3-§6.4) |
| Retirement YAML pointer fix | **Open follow-up** (§5) |
| Promotion of this memo to `docs/spec/` | **Done** (Sprint 17, slot 11) |
