# Prompt Analysis Research Queue

**Branch:** `research/prompt-analysis`

**Scope:** Research threads for the prompt analysis module
(`docs/spec/08-prompt-analysis-module-spec.md`). Covers intent classification,
zone segmentation, and risk engine research. Content detection is owned by the
structured research branch (`research/meta-classifier`).

**Relationship to main:** One-way promotion via sprint items, per the research
workflow contract. Findings graduate to `backlog/` items before they reach main.

**Sibling research branch:** `research/meta-classifier` handles meta-classifier,
feature engineering, and structured-data accuracy research.

**Created:** 2026-04-16

---

## Architectural commitments

### Multi-label is fundamental (committed 2026-04-16)

Intent classification in this branch commits to **multi-label output
from Day 1** of any classifier work. A prompt can legitimately express
multiple parallel intents (`{summarize, translate}` or
`{data_processing, knowledge_request}`). Forcing argmax-one-winner at
the prompt level would reproduce the Sprint 12 mistake that the
structured branch just corrected — softmax on heterogeneous columns
returned confidently-wrong single-class predictions on 3/6 fixtures,
triggered a RED safety-audit verdict, and caused the directive-
promotion item to be retired.

See the library-wide philosophy memo (research-side location pending
promotion to spec):
`../../../data_classifier-research-ops/docs/research/multi_label_philosophy.md`
on `research/meta-classifier`. Post-Sprint-12 close, promoted to
`docs/spec/10-multi-label-architecture.md`.

**Practical implications for the Intent readiness track:**

- **Stage 0 (label-set design)** must produce a taxonomy that
  accommodates multi-label per prompt. Flat "one intent per prompt"
  taxonomies are not viable even if they appear cleaner on paper.
- **Stage 3 (gold-set hand-labeling)** accepts multi-label per prompt
  — annotators label the set of intents present, not a single winner.
- **Stage 4 (LLM-labeled training set)** the labeler prompt must
  return a list of intents per input, not a single top label.
- **Stage 5 (intent model benchmark)** metrics must be multi-label
  (precision@k / recall@k / Jaccard / subset-F1). Single-label macro
  F1 is not the right quality gate — it would reward argmax-style
  predictions that silently miss parallel intents.

This is a **pre-committed architectural decision, not a design
question to be re-opened during Stage 0.** Discussion during Stage 0
is about *which* taxonomy to pick; it is not about whether the
taxonomy should be multi-label.

### Scope note — single-label may apply at narrow sub-tasks

Per philosophy memo §3, single-label primitives remain valid at
narrow sub-tasks where labels are mutually exclusive (e.g., given a
prompt already classified as carrying `data_processing`, which
specific task-type child is the strongest match — `summarize` vs
`translate` vs `rewrite`?). The multi-label commitment is at the
prompt-level output, not at every internal sub-task.

The risk engine's cross-correlation (content × intent × zone)
benefits: a risk verdict is a function over three parallel lists, not
three winners.

---

## Intent readiness track

The intent classification dimension of prompt analysis requires a labeled
corpus that does not exist in public form. This track builds the data
infrastructure before any model work happens. Sequencing is deliberate — each
stage blocks the next.

### Stage 0 — Label set design

- **Status:** 🟡 open — discussion needed before any labeled data exists
- **Blocks:** Stages 2-6 (all labeled work depends on the taxonomy)
- **Reference:** `docs/spec/08-prompt-analysis-module-spec.md`
  §"Intent Taxonomy Design"
- **Constraint:** per Architectural commitments § above, the chosen
  taxonomy MUST accommodate multi-label output per prompt. Flat "one
  intent per prompt" taxonomies are not viable. Parallel intents
  (`{summarize, translate}`, `{data_processing, knowledge_request}`)
  must be representable.

Decide the intent taxonomy. Current proposal from the 2026-04-16 discussion:
**hybrid** — 3 top-level data-flow directions (`data_processing`,
`data_extraction`, `knowledge_request`) plus up to 10 fine-grained task-type
children (per spec §"Intent Taxonomy Design"). Top-level is the risk gate;
fine-grained is for risk characterization.

Alternatives to consider: flat 10-intent (spec default), flat 4-intent
(3 directions plus `unknown`), hybrid with fewer children.

### Stage 1 — Corpus acquisition

- **Status:** 🟡 unblocked — can start immediately, zero dependencies
- **Blocks:** Stages 3-6

Download and stage raw prompt corpora under clean licenses:

- **WildChat-1M** (`allenai/WildChat-1M`) — CC0, real ChatGPT conversations, 1M samples
- **LMSYS-Chat-1M** (`lmsys/lmsys-chat-1m`) — research use, real LMSYS arena conversations
- **Dolly-15K** (`databricks/databricks-dolly-15k`) — CC-BY-SA 3.0, crowdsourced instructions with `category` field
- **OASST** (`OpenAssistant/oasst1` + `oasst2`) — Apache 2.0, multi-turn assistant conversations

Target location: `corpora/prompt_analysis/` (new directory in this worktree).

### Stage 2 — Dolly bootstrap labeling

- **Status:** ⏸ blocked on Stage 0
- **Blocks:** Stage 5 (provides a weak-labeled baseline for the benchmark)

Map Dolly-15K's `category` field (`summarization`, `information_extraction`,
`open_qa`, `closed_qa`, `general_qa`, `brainstorming`, `creative_writing`,
`classification`) onto the chosen intent taxonomy. Produces ~15K weakly-labeled
examples for zero-shot model benchmarking. Mapping is conceptual work (decide
which Dolly categories map to which intents, handle the ones that do not fit),
no manual per-sample annotation.

### Stage 3 — Gold set hand-labeling

- **Status:** ⏸ blocked on Stage 0 + Stage 1
- **Blocks:** Stages 4-6

Sample 200-500 prompts from WildChat (real user prompts, not crowdsourced
instructions). Hand-label against the taxonomy. This is the honest evaluation
set — every subsequent experiment is measured against it. Small effort,
enormous leverage. Without this gold set, no model result is trustworthy
because every downstream label source is some form of weak supervision.

### Stage 4 — LLM-labeled training set

- **Status:** ⏸ blocked on Stage 3
- **Blocks:** Stages 5-6

Use a strong LLM (Claude or GPT-4 class) as a labeler on 5-10K WildChat
prompts. Measure label agreement against the gold set on a held-out slice.
Iterate on the labeling prompt until agreement is high enough. Produces the
labeled corpus needed for real intent training or evaluation.

### Stage 5 — Intent model benchmark

- **Status:** ⏸ blocked on Stage 4
- **Blocks:** Stage 6

Compare zero-shot intent classification accuracy across three candidate models
on the labeled corpus, evaluated against the gold set for honesty:

- **GLiNER2** (Fastino) — `classify_text()` first-class. Note: different
  package from the current `gliner` v1.x we use for content detection, see
  `docs/research/gliner_fastino/GLINER_REFERENCE.md` §5.4 for the API
  differences.
- **BART-MNLI** (`facebook/bart-large-mnli`) — zero-shot via NLI entailment,
  ~400M params, standalone.
- **EmbeddingGemma** (`google/embeddinggemma-300m` or similar) —
  nearest-neighbor against per-intent reference examples.

Output: F1-per-intent × latency × memory Pareto + "start here" recommendation.

### Stage 6 — Zero-shot vs fine-tune decision

- **Status:** ⏸ blocked on Stage 5

Based on Stage 5's benchmark results, decide whether zero-shot is
production-ready or whether fine-tuning on the LLM-labeled set is justified.
If fine-tune, the LLM-labeled set from Stage 4 becomes training data; the
gold set from Stage 3 stays as eval.

---

## Other tracks

Empty for now. Zone segmentation research, risk engine research, and
behavioral signal integration research will be added as separate tracks
if/when they become active.

---

## Cross-references to structured research

Findings from `research/meta-classifier` that touch this branch get a
cross-reference note here.

- **Boundary detector / structural classifier** — Sprint 14 candidate Theme B
  (spec Stage 12). If it lands on main, the same heuristics serve as
  Zone Segmentation Tier 1
  (`docs/spec/08-prompt-analysis-module-spec.md` §"Tier 1: Heuristic Zone Detection").
  This is the clearest shared-infrastructure payoff between the two tracks.
- **GLiNER2 package adoption** — if the structured track ever adds `gliner2`
  (Fastino) alongside `gliner` v1.x for content detection, the Stage 5 intent
  benchmark becomes cheaper because one model instance serves both content
  detection and intent classification. Current status: research thread only,
  not a committed migration
  (see `docs/research/gliner_fastino/GLINER_REFERENCE.md` §5.3-5.4).
- **Calibration audit** — if the structured track produces calibrated
  confidence scores, the prompt analysis risk engine's threshold logic
  (`docs/spec/08-prompt-analysis-module-spec.md` §"Risk Score Computation")
  inherits that calibration for free.
