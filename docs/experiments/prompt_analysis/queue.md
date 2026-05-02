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

See the library-wide philosophy spec at
[`docs/spec/11-multi-label-architecture.md`](../../spec/11-multi-label-architecture.md)
(canonical location since Sprint 17 promotion; previously lived as a
research memo on `research/meta-classifier`).

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

- **Status:** ✅ COMPLETE 2026-04-17 (3/4 corpora; LMSYS deferred)
- **Blocks (resolved):** Stages 3-6

Downloaded and staged via DVC (`data/` + GCS `gs://data-classifier-datasets`):

- **WildChat-1M** (`allenai/WildChat-1M`) — CC0, 1M samples, 6.7 GB — ✅ already tracked
- **Dolly-15K** (`databricks/databricks-dolly-15k`) — CC-BY-SA 3.0, 15,011 rows, 7.2 MB — ✅ tracked
  - 8 categories: brainstorming, classification, closed_qa, creative_writing, general_qa, information_extraction, open_qa, summarization
- **OASST2** (`OpenAssistant/oasst2`) — Apache 2.0, 135,174 rows (13,162 root prompts), 101 MB — ✅ tracked
  - OASST2 is a superset of OASST1; only OASST2 tracked
  - Top languages: en 47%, es 27%, ru 9%, zh 4%, de 4%
- **LMSYS-Chat-1M** (`lmsys/lmsys-chat-1m`) — ⏸ **deferred**: gated dataset, requires HF access approval + research-use license

All datasets registered in `data_classifier/datasets.py` `_HF_REGISTRY` and loadable via `load_local_or_remote()`.

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

- **Status:** ✅ COMPLETE 2026-04-16 — smoke (500) + 50K + 1M all run,
  artifacts committed, findings memo published
- **Blocks (resolved):** S1 (gap audit folded into S0 — 3 Sprint 13
  backlog items drafted); informed the client product conversation
- **Effort actual:** ~1 day (vs ½-day estimate; expanded scope from
  finding more bugs than expected)

**Headline numbers (full 1M scan)**:

- **0.12% of real ChatGPT prompts contain a leaked credential** (1,171 / 1M)
- **1,712 raw credential findings** (1,025 API_KEY + 680 OPAQUE_SECRET
  + 6 PRIVATE_KEY + 1 PASSWORD_HASH)
- Distinct credential prompts: 1,171 (after SHA-256 dedup)
- Throughput: 2,022 prompts/sec on warm HF cache (8.2 min for 1M)
- Engine breakdown: 1,069 secret_scanner + 643 regex

**Real credential examples** (anonymizable for client demo):

- Live Shopify access token + secret pair (PHP code)
- Instagram username + password (Selenium scraper)
- Telegram bot token (Russian bot Python code)
- Facebook Graph API access token (Instagram automation)
- OpenAI API key (legacy `sk-` format — Sprint 13 pattern gap)

**Bugs surfaced + Sprint 13 backlog items drafted** (file from
`/tmp/backlog_drafts/` via the sprint13/main session):

1. `sprint13-s0-pattern-precision-pass.yaml` (P1 bugfix, ~1d) —
   SWIFT_BIC validator (~11K FPs in 1M extrapolation) + IPv4
   validator/boundary
2. `sprint13-add-legacy-llm-provider-patterns.yaml` (P2 feature, ~½d)
   — OpenAI legacy `sk-*` + Anthropic `sk-ant-*`
3. `sprint13-secret-key-dict-stoplist.yaml` (P2 bugfix, ~½d) —
   secret-key dictionary stoplist for `*_address`, `*_field`, etc.

**Cross-references**:

- Memo: `s0_artifacts/s0_findings_memo.md`
- 50K artifacts: `s0_artifacts/{s0_credentials.jsonl, s0_non_credential_sample.jsonl, s0_curate_summary.json}`
- 1M artifacts: `s0_artifacts/s0_1m/{s0_credentials.jsonl, s0_non_credential_sample.jsonl, s0_curate_summary.json}`
- Reproduction: `scripts/s0_curate_credentials.py --limit N --out-dir ...`

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

- **Status:** ✅ COMPLETE 2026-04-17 — see `s2_spike/report/s2_browser_port_spike.md`
- **Blocks (resolved):** execution track can now commit to Path 1 (native JS RegExp)
- **Effort actual:** ~½ day (vs 1-day estimate; DVC infra setup took the other ½ day)

**Headline numbers** (77 content regex patterns, 11K WildChat corpus):

- Per-prompt scan latency P99 = **0.70 ms** (all 77), **0.30 ms** (41 credential-only)
- Max latency = 2.50 ms (all), 1.40 ms (credential-only)
- ReDoS: **73 safe / 3 polynomial / 0 exponential** — all polynomial patterns sub-0.3ms measured
- Bundle gzipped: **13.45 KB** projected total (target 200 KB) — 93% headroom
- **Path 1 (native JS RegExp) is a clear go.** No re2-wasm needed.
- Worker kill budget can be set generously (100ms) with zero expected kills at any tested threshold

Three measurements in headless Chrome via Playwright:

1. **JS regex perf benchmark** — all 77 content regex patterns over an
   11K WildChat sample (10K random + 1K longest). Reports P50-P99.9,
   histogram, per-pattern max, compile time. Separate distributions for
   all-patterns vs credential-only (browser PoC scope = 41 credential).
2. **ReDoS audit** — all 77 patterns through `recheck`. 73 safe,
   3 polynomial (email, JWT, Discord bot), 0 exponential.
3. **Bundle size** — patterns + entropy = 2.44 KB gzipped; plus
   projected validators ~11 KB = 13.45 KB total (target 200 KB).

Output location: `s2_spike/report/s2_browser_port_spike.md`.

### Stage S3 — Pattern expansion mine (filed on `main`, Sprint 14 candidate)

- **Status:** ✅ COMPLETE 2026-04-17 — see `s3_pattern_mine/` for all artifacts
- **Effort actual:** ~½ day (vs 5-7 day estimate; focused on high-yield sources)

**Results**: 19 net-new credential patterns + 6 quality upgrades across 4 sources.
Promotion to `main` via a single PR when ready.

| Stream | Source | License | Net-new | Upgrades |
|---|---|---|---|---|
| S3-A | secretlint | MIT | 9 | 5 |
| S3-B | detect-secrets | Apache 2.0 | 5 | 1 (GitLab 10 token types) |
| S3-C | Provider docs | N/A (factual) | 5 | 0 |
| S3-D | gitleaks/Kingfisher/NP refresh | MIT/Apache 2.0 | 0 (unchanged since Sprint 10) | 0 |

Net-new patterns: Grafana (2), Docker Hub, Linear, Groq, 1Password,
Notion, Figma, Basic Auth URL, PyPI, Mailchimp, Artifactory, Square
OAuth, Telegram Bot, Okta, Postman, Airtable, Heroku, Render.

Quality upgrades: GitHub (fine-grained PATs), Slack (unified prefixes),
OpenAI (svcacct/admin), HashiCorp Vault (hvb/hvr), HuggingFace
(tighten), GitLab (10 token types).

Corpus validation: 3 hits total (all Telegram bot tokens on 11K
WildChat). All other patterns: 0 hits (expected for niche formats).

Artifacts in `s3_pattern_mine/{s3a_secretlint,s3b_detect_secrets,
s3c_provider_docs,s3d_refresh}/`.

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
