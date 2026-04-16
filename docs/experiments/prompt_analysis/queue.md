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

## Secret detection track

The first prompt-analysis client (a Chrome extension over ChatGPT,
scoped 2026-04-16) needs single-purpose secret detection on submitted
prompts, running entirely client-side. This track scopes the research
and feasibility work for that delivery.

The track is parallel to (and shorter than) the Intent readiness track.
It reuses `secret_scanner` + `regex_engine` already on `main`, and
focuses on browser-port feasibility, prompt-corpus evaluation, and
pattern-set expansion. No taxonomy decisions; no labeled-data
infrastructure.

### Architectural commitments

- **PoC location**: `data_classifier/clients/browser/` on `main`. The
  Python wheel excludes that path; the JS package does not depend on
  Python at runtime.
- **Patterns are a shared asset on `main`** — single source of truth
  for Python and JS consumers. JS pattern dict is generated from the
  Python JSON via a build script. No fork.
- **`secret_scanner` is built for structured content** (`key: value`
  pairs in JSON / YAML / env / code). For free-form prose without
  structure, only `regex_engine` patterns fire. This shapes prompt-side
  expectations.
- **CREDENTIAL family is API_KEY (35), PRIVATE_KEY (1), PASSWORD_HASH
  (4), OPAQUE_SECRET (1) — no plaintext PASSWORD subtype.** Documented
  for clarity; gap addressed by the out-of-scope note below.
- **ReDoS defense via Web Worker terminate, not pattern audit-as-gate.**
  Static `recheck` audit runs and informs optimization priority but
  does not block patterns from shipping. Justification: in a browser
  extension over user-owned input, ReDoS is a UX problem, not a
  security one — the worker terminate is the real defense.
- **Regex engine: JS-native for Stage 1, re2-wasm for Stage 2.** Both
  committed; only the migration trigger is open. JS regex ships first
  because the toolchain is lighter and the PoC unblocks the client
  conversation faster. re2-wasm is the planned destination because
  pattern-audit cost is linear in pattern count while re2-wasm bundle
  cost is fixed (~80KB), and re2-wasm gives byte-identical semantics
  with the Python library forever (the differential test passes on
  regex semantics by construction). See Stage S4 for migration triggers.
- **Worker pool architecture** (size 2, lazy init, eager respawn,
  MV3-lifecycle-aware). Chosen over spawn-per-scan because forward
  compatibility with future ML-backed engines (intent / zone / risk)
  requires "load model once per worker, reuse forever" — spawn-per-scan
  defeats that.
- **Fail-open default on scan timeout, configurable to fail-closed.**
  Configurable kill budget; default 100ms pending S2 measurement.
- **Pattern source policy**: trufflehog (AGPL-3.0) is **excluded** from
  any mining. Bridge gaps via secretlint (MIT, JS-native), detect-
  secrets (Apache 2.0), provider documentation, and RFCs/specs.
  Provenance is per-pattern (source, license_clearance, pulled date,
  validator) in `docs/process/CREDENTIAL_PATTERN_SOURCES.md`,
  CI-enforced.
- **Validators are first-class for the JS port** (added 2026-04-16
  from S0 evidence). Empirical finding: in a 500-prompt smoke against
  WildChat, every regex-pattern false positive was correctly rejected
  by its validator (phone, AWS_secret_key, dob, ipv4-as-substring all
  matched the regex but failed the validator). The browser JS port MUST
  faithfully implement validators, not just regexes — patterns alone
  overfire ~4× per pattern. Same applies to stopwords / placeholder
  filters. This is a Day-1 architectural commitment, not an
  optimization.
- **`secret_scanner` heuristic (key + entropy) MUST be in the JS port**
  (added 2026-04-16 from S0 evidence). The only confirmed real
  credential found in the 500-prompt smoke was caught by
  `secret_scanner` (`password = "stcmalta"` in pasted C# login code),
  not by any of the 76 regex patterns. Real-world prompts contain
  hardcoded credentials in code snippets — these have no standard
  format, only key+value structure. Pure-regex JS port would miss the
  most common real positive.

### Stage S0 — Prevalence scan on WildChat-1M

- **Status:** 🟢 in progress — smoke (500) + 50K complete 2026-04-16,
  full 1M deferred pending v2 script with deduplication
- **Blocks:** S1; informs the client product conversation
- **Effort:** ~½ day

Run the existing Python `secret_scanner` + `regex_engine` over the
WildChat-1M user-message column. Output:

- Prevalence rate by entity type (hit count / total prompts)
- Hit distribution histograms
- Hand-audit ~50 random hits for FP estimate
- Top-K most-fired patterns
- Captured examples (XOR-encoded per the fixture rule)

**Findings as of 2026-04-16 (50K)**:

- Engine-level prevalence (any entity type): **3.66%** (1,830 / 50K)
- **Credential-family prevalence**: **0.12%** (59 = 36 OPAQUE_SECRET + 23 API_KEY)
- One real positive confirmed in the 500-smoke audit: hardcoded
  `password = "stcmalta"` in pasted C# login code, caught by
  `secret_scanner`. Extrapolation: ~720 OPAQUE_SECRET + ~460 API_KEY = ~1,200 real credential leaks per 1M prompts.
- Two general-classifier precision bugs surfaced + filed as Sprint 13
  backlog items: SWIFT_BIC missing validator (593 FPs in 50K) +
  IPv4 validator-too-narrow + boundary issue.
- Two missing patterns surfaced + filed as Sprint 13 backlog item:
  OpenAI legacy `sk-*` (no `proj-` prefix) + Anthropic `sk-ant-api03-*`.
- Throughput: 1,140 prompts/sec on warm cache; 1M run ≈ 15 min wall.

**Script v2 deferred work** (not blocking v1 findings):

- Drop finditer accounting (overcounts because validators are bypassed)
- Capture engine-only positives in audit_sample (current bug skips
  secret_scanner-only finds)
- Deduplicate repeated-substring matches (one base64 blob produced
  11 AWS_secret_key sub-spans in smoke — engine validator caught it,
  but pattern_hits.json overcounted)

Output location: `docs/experiments/prompt_analysis/s0_artifacts/`
(committed at end of Stage S0 with the formal memo).

### Stage S1 — Pattern gap audit

- **Status:** ⏸ blocked on S0
- **Blocks:** S3 (informs prioritization)
- **Effort:** ~1 day

Compare S0's hit distribution against the gap inventory:

| Gap area | Examples |
|---|---|
| Modern LLM provider keys | Anthropic, Gemini, Mistral, Perplexity, Cohere, Together, Replicate, Groq |
| Crypto beyond BTC/ETH | Solana, Polkadot, Cosmos, TRON, Litecoin |
| Cloud DB connection strings | Supabase, Neon, PlanetScale, MongoDB Atlas SRV, Upstash |
| Modern webhook tokens | Discord, Teams, Zapier, n8n |
| Mobile / CI tokens | Firebase service-account JSON, App Store Connect, CircleCI personal, Bitrise |
| Auth token formats | PASETO v3/v4, Branca, biscuit |

Output: a backlog item filed on `main` for Sprint 14 with prioritized
targets, estimated source per target (provider-doc / secretlint /
detect-secrets / spec), and rough effort estimate.

### Stage S2 — Browser-port feasibility spike

- **Status:** 🟡 unblocked — can start in parallel with S0
- **Blocks:** the PoC build itself (separate sprint item, post-spike)
- **Effort:** ~1 day

Three measurements in headless Chrome via Playwright:

1. **JS regex perf benchmark** — all 178 current patterns over a
   WildChat sample. Report P50/P95/P99/max scan latency, throughput,
   bundle parse time, memory delta.
2. **ReDoS audit** — all 178 patterns through `recheck`. Categorize
   by severity (exponential / polynomial / safe). No gate, just data.
3. **Bundle size estimate** — pattern dict + entropy + validators,
   minified + gzipped. Target <200KB.

Output: go/no-go on Path 1 (audited JS regex) vs Path 2 (re2-wasm)
for the PoC. If worst-case scan stays under the worker kill budget,
Path 1 ships; otherwise Path 2.

Output location: `docs/experiments/prompt_analysis/s2_browser_port_spike.md`.

### Stage S3 — Pattern expansion mine (filed on `main`, Sprint 14 candidate)

- **Status:** ⏸ blocked on S1
- **Effort:** 5-7 days; sibling of the Sprint 10 Kingfisher mine

Mine secretlint (MIT, JS-native) + detect-secrets (Apache 2.0) +
provider documentation + RFCs/specs for the gap set from S1. Refresh
existing mines (gitleaks / Kingfisher / Nosey Parker) since Sprint 10.

Update `CREDENTIAL_PATTERN_SOURCES.md` schema to require per-pattern
provenance fields (source URL, source_type, license_clearance, pulled
date, validator). CI enforces presence of all five fields per new
pattern.

Lives on `main` because patterns are a shared asset across both
research branches and both consumers (BQ-connector + browser
extension).

### Stage S4 — Migrate JS regex engine to re2-wasm (planned, trigger-driven)

- **Status:** ⏸ planned — pre-committed direction, deferred execution
- **Effort:** 1-2 weeks when triggered

The PoC ships on JS regex (Stage 1 engine). Migration to re2-wasm is
the planned long-term destination, not a fallback. Triggers (any one
fires the migration sprint item):

- **Pattern count crosses ~250-300** — audit cost outgrows audit value
  at this scale (current 178 + S3 expansion 40-70 = ~220-250 lands us
  near the threshold).
- **First confirmed ReDoS escape in production** — telemetry catches a
  scan that exceeded the worker kill budget, root-caused to a
  pattern-audit miss.
- **Forward-need from another engine** — any new engine (intent /
  zone / risk) needs multi-pattern scanning at scale, where re2's
  set-matching beats JS regex.
- **Differential test divergence** — JS regex semantics drift from
  Python on a corner case that's expensive to patch in pattern code.

Migration scope:

- Replace JS `RegExp.exec` calls with re2-wasm bindings; pattern dict
  format unchanged (already JSON, RE2-syntax compatible since Python
  uses RE2).
- Recompile pattern set at extension init (~10ms one-time cost,
  amortized across the session).
- Re-run differential test; expect zero behavior change on regex
  semantics (the validators + entropy paths are unchanged).
- Bundle size: +~80KB fixed (re2-wasm binary).

Lives on this branch as a planned milestone; gets a `main` sprint
item when the trigger fires.

### Out of scope

- **Plaintext-prose password detection** ("my password is hunter2") —
  deferred per 2026-04-16 client conversation. Future layer
  (NL-context classifier, separate from regex/entropy) if/when added.
  Consciously not addressed by this track.
- **All non-secret detection** (intent classification, zone
  segmentation, risk scoring) — owned by the Intent readiness track
  and future tracks. Not in scope for the first client.

---

## Other tracks

Zone segmentation research, risk engine research, and behavioral
signal integration research will be added as separate tracks if/when
they become active.

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
