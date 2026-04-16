# Sprint 12 safety audit — directive promotion go/no-go

**Author:** Sprint 12 owner
**Date:** 2026-04-16 (iteration 2; iteration 1 dated same day with YELLOW
verdict was superseded by the multi-fixture Q3 evidence documented below)
**Status:** Phase 5b complete — verdict **RED**
**Artifact:** `/tmp/sprint12_safety_audit.json`
**Harness:** `tests/benchmarks/meta_classifier/sprint12_safety_audit.py`
**Model under audit:** `data_classifier/models/meta_classifier_v5.pkl`
(49-feature schema, 47 kept after `ALWAYS_DROP_REDUNDANT`, trained against
the regenerated `training_data.jsonl` after the Phase 2/3 feature additions
and the Phase 5a Option A train/serve skew fix)

---

## TL;DR

v5 passes the in-distribution bars and passes the headline aggregate LOCO
bar, but **structurally fails the heterogeneous-column audit**. The Sprint
12 directive promotion (Item #4) is therefore **deferred indefinitely**
pending a structural reformulation of the meta-classifier's role (not to
be confused with "deferred to Sprint 13 conditionally" — the deferral is
not about more model capacity or a retrain; it is about the softmax
primitive being wrong for the problem).

Three findings drive the decision:

1. **Q3 (heterogeneous)** — tested across 6 realistic heterogeneous
   fixture types (log lines, Apache access logs, JSON events, base64
   tokens, chat messages, Kafka streams). **3 of 6 fixtures produce
   high-confidence wrong-class v5 predictions** (VIN @ 0.934 on base64,
   CREDENTIAL @ 1.000 on chat, CREDENTIAL @ 0.999 on Kafka). **2 of 6
   produce medium-confidence wrong-class predictions.** v5 is not
   "uncertain and hedging" on heterogeneous input — it is **confidently
   wrong** on the majority of it, picking different wrong classes
   depending on the fixture shape. No confidence threshold can separate
   these cases from v5's correct in-distribution predictions.

2. **Training-data coverage** — the "log-ish" feature region
   (`distinct≥0.9, avg_length≥0.7, dict_word≥0.3`) covers 0.77% of v5's
   training rows, and those are labeled NEGATIVE/CREDENTIAL only. Any
   heterogeneous column is structurally out-of-distribution for v5, and
   OOD softmax predictions are unreliable in both direction and magnitude.

3. **Softmax is the wrong primitive.** v5 models the problem as "exactly
   one of K classes is true for this column," which is false for a
   meaningful fraction of BQ columns (log lines, event streams, chat,
   webhook payloads, JSON blobs). The cascade's `list[ClassificationFinding]`
   output already has the structurally-correct shape (multi-label); v5
   re-imposed mutual exclusivity on top of it. Any version of directive
   promotion that lets v5's single-class output override the cascade's
   multi-class output inherits this structural error.

**Verdict: RED.** Sprint 12 ships v0.12.0 with shadow-only meta-classifier
(Items #1, #2, Option A train/serve skew fix land as shadow improvements;
BQ continues consuming live cascade as source of truth). Directive
promotion defers until a multi-label reformulation exists — either a
column-shape router (see §6) that restricts v5 to the subset of columns
where mutual exclusivity holds, or a genuinely multi-label meta-classifier
(sigmoid-per-class, per-value GLiNER aggregation, etc.).

The Q1 capacity finding (LR is not the bottleneck — MLP ties or loses)
is load-bearing for this conclusion: it means the fix is not "more model
capacity" or "a better softmax classifier," it is a different problem
formulation altogether. That is what Sprint 13 needs to deliver.

---

## 1. Capacity audit (Q1)

**Question:** Is LR the information ceiling on v5's training data?

**Method:** Three arms evaluated on identical folds:

| Arm | Description | Hyperparameters |
|---|---|---|
| A0_LR | v5-equivalent baseline | LogisticRegression(C=1.0, class_weight=balanced, max_iter=2000) |
| A1_MLP | Two-layer MLP | hidden_layer_sizes=(32,32), alpha=1e-3, early_stopping=True |
| A2_LR_interactions | LR + top-5 feature pairwise products | Top-5 features by mutual_info_classif; 10 interaction features appended |

Evaluated on:
- **CV**: 5-fold StratifiedGroupKFold on `_base_shard_id` groups (shard-twin leak prevented per Sprint 11 Phase 4)
- **LOCO**: Leave-one-corpus-out across 6 non-synthetic corpora (detect_secrets, gitleaks, gretel_en, gretel_finance, nemotron, secretbench)
- **Brier score**: multiclass average per-row squared error, mean over 5 CV folds

### Results

| Arm | CV mean macro F1 ± std | Brier | LOCO weighted | LOCO unweighted | Pooled family F1 |
|---|---|---|---|---|---|
| A0_LR | 0.9943 ± 0.0014 | 0.0107 | 0.5680 | 0.4334 | 0.6999 |
| A1_MLP | 0.9932 ± 0.0034 | 0.0124 | 0.5613 | 0.4144 | 0.7016 |
| **A2_LR_interactions** | **0.9942 ± 0.0013** | **0.0098** | **0.6041** | **0.4874** | **0.7206** |

Winner (CV + LOCO combined): **A2_LR_interactions**.

### Interpretation

**Pattern 3 per the audit spec** — v5 is at the information ceiling for
raw LR, and **MLP adds no capacity**. A1_MLP ties A0_LR on CV and is
*worse* on LOCO by −0.019 (unweighted). Adding hidden layers without
adding signal just memorizes training corpora more aggressively, which is
what the Sprint 9 learning memo warned about.

**A2_LR_interactions is the lift source.** Pairwise products of the top-5
features (by mutual information) add +0.054 LOCO F1 unweighted and
+0.036 LOCO F1 weighted over the LR baseline — with essentially the same
CV score. This is a cheap, deployable win: same model class, same
training pipeline, just 10 extra features.

**Cap the claim at the right frame.** The improvement is on LOCO
(generalization), not CV (in-distribution), which is the harder and more
important axis. It is also within CV std (A0 CV 0.9943 ± 0.0014,
A2 CV 0.9942 ± 0.0013 — overlapping error bars on CV, clear lift on
LOCO). This is the shape of evidence that "the features have more signal
than a flat LR is extracting".

### Per-corpus LOCO — the buried finding

The aggregate LOCO numbers pass Item #4's 0.30 bar, but the **per-corpus
breakdown exposes catastrophic failures on two corpora**:

| Holdout corpus | n_test | A0_LR F1 | A2_LR F1 |
|---|---|---|---|
| detect_secrets | 300 | **0.0044** | **0.0022** |
| gitleaks | 300 | 0.2665 | 0.2665 |
| gretel_en | 1800 | 0.5802 | 0.6188 |
| gretel_finance | 1800 | 0.7107 | 0.7131 |
| nemotron | 1950 | 0.5740 | 0.6190 |
| secretbench | 300 | 0.4647 | 0.7048 |

`detect_secrets` is effectively zero-F1 across both arms. `gitleaks` is
below the 0.30 bar individually. Both are credential-name-heavy corpora
— the exact data class the CREDENTIAL branch in Q2 measures. The
aggregate LOCO mean is driven up by the three large corpora (gretel_en,
gretel_finance, nemotron at ~2k rows each) and masks the catastrophic
failure on the two small credential corpora.

**This is the honest out-of-distribution picture.** v5 generalizes to
gretel/nemotron data (which are in-distribution for its training corpora)
and fails almost completely on held-out credential corpora. The aggregate
bar is formally met, but the shape of the failure tells us the model
has learned corpus-specific priors on credentials, not credential semantics.

---

## 2. Architecture audit (Q2)

**Question:** Does v5 need hard gating to separate credential-family
classification from PII classification?

**Method:** Oracle-gate upper bound — partition training rows by
ground-truth family (CREDENTIAL vs non-CREDENTIAL), train a specialized
LR on each branch with the Q1 winner's config, evaluate per-branch LOCO,
compare the support-weighted sum to the single-model baseline LOCO.

An oracle gate is the **upper bound** of what a real gate classifier
could deliver. If oracle gating doesn't beat the single-model baseline
by a meaningful margin, no practical gate classifier will.

Heterogeneous branch: omitted — the training data contains no rows for
heterogeneous columns (each row is a synthetic single-entity column).
The heterogeneous case is covered by Q3 instead.

### Results

| Branch | n_rows | LOCO weighted | LOCO unweighted |
|---|---|---|---|
| CREDENTIAL | 750 | 0.3360 | 0.3360 |
| non_CREDENTIAL | 9120 | 0.7064 | 0.5669 |
| — | — | — | — |
| Single-model baseline | 9870 | **0.5680** | — |
| Hard-gated (oracle) sum | 9870 | **0.6711** | — |
| **Delta** | | **+0.1031** | |

### Interpretation

Delta = +0.1031. The YELLOW trigger is ≥ 0.10, the RED trigger is ≥ 0.15.
**This is YELLOW territory, just past the trigger line.** Hard gating
delivers about 10 points of LOCO headroom that soft gating (the current
primary_entity_type one-hot workaround from Sprint 11) cannot reach.

Two readings of this number, both defensible:

1. **"+0.10 is real and load-bearing."** The Sprint 9 learning memo
   argued that credential detection and PII detection have structurally
   different signal distributions. This result confirms it quantitatively
   on post-Sprint-12 data. The Sprint 13 gated architecture item is
   designed to close exactly this gap; the measurement supports filing
   it.

2. **"+0.10 is noise at the boundary."** The CREDENTIAL branch has only
   750 training rows split across 4 corpora (150 rows per LOCO holdout).
   Per-corpus F1 inside the CREDENTIAL branch swings from 0.026
   (detect_secrets) to 1.000 (gitleaks) to 0.000 (gretel_finance — where
   there are no in-branch training rows). The branch measurement is
   therefore intrinsically noisy, and a different random seed could push
   delta to 0.09 or 0.12.

**Pragmatic call:** treat the +0.1031 as real for planning purposes
(it matches the Sprint 9 memo's theoretical prediction) but do not
treat it as blocking. The soft-gated v5 is clearly inferior to a
hypothetical hard-gated v6 on credential generalization, but not
catastrophically so.

---

## 3. Heterogeneous audit (Q3) — 6 fixtures

**Question:** Does flat v5 collapse on heterogeneous columns, and if so
how consistently? What is the *failure surface* — single fixture type, or
multiple?

**Method (iteration 2, 2026-04-16):** Construct 6 heterogeneous fixtures
spanning distinct shapes of realistic multi-entity column content. For
each fixture, run both:

1. **Live cascade** (`classify_columns`) — the current BQ code path, used
   as ground truth for "what entities are present in this column?"
2. **Meta-classifier shadow** (`MetaClassifier.predict_shadow` with the
   Phase 5a `engine_findings` kwarg wired) — the directive-promotion
   candidate being audited

Collapse verdict is computed **per fixture** against the shadow
prediction. Aggregate verdict is the **worst single-fixture verdict**
across all 6 shapes — a single fixture with high-confidence wrong-class
collapse is enough to block GREEN because a BQ customer with that shape
would see a confident-wrong directive prediction in production.

### Fixture taxonomy

| Fixture | Shape |
|---|---|
| `original_q3_log` | 50 unique log lines, 4+ entities per line (emails, API keys, IPs, URLs, SSNs, phones, …) |
| `apache_access_log` | Classic HTTP access log (IPs + paths + methods + status codes) |
| `json_event_log` | Structured JSON events (pub/sub sink pattern) |
| `base64_encoded_payloads` | Opaque base64 tokens (JWT / auth audit pattern) |
| `support_chat_messages` | Conversational text with embedded PII (support tickets / chat transcripts) |
| `kafka_event_stream` | Key-value event records (Kafka topic dump pattern) |

### Per-fixture results

| Fixture | Cascade entities | Shadow prediction | Confidence | Verdict |
|---|---|---|---|---|
| `original_q3_log` | EMAIL, IP_ADDRESS, URL, API_KEY | ADDRESS | 0.688 | collapsed_medium_confidence_**wrong_class** |
| `apache_access_log` | IP_ADDRESS | ADDRESS | 0.639 | collapsed_medium_confidence_**wrong_class** |
| `json_event_log` | EMAIL, IP_ADDRESS | EMAIL | 0.653 | collapsed_medium_confidence_*one_of_live* |
| **`base64_encoded_payloads`** | *(none)* | **VIN** | **0.934** | **collapsed_high_confidence_wrong_class** |
| **`support_chat_messages`** | EMAIL, PHONE | **CREDENTIAL** | **1.000** | **collapsed_high_confidence_wrong_class** |
| **`kafka_event_stream`** | EMAIL, IP_ADDRESS, URL | **CREDENTIAL** | **0.999** | **collapsed_high_confidence_wrong_class** |

**Aggregate: `collapsed_high_confidence_wrong_class` → RED.**

- 3/6 fixtures: shadow emits a class not present in the column at ≥0.80 confidence
- 2/6 fixtures: shadow emits a class not present in the column at 0.50–0.80 confidence
- 1/6 fixtures: shadow emits one of the live-detected classes (`json_event_log` → EMAIL)
- 3/6 fixtures: live cascade found multiple entities AND shadow collapsed to a wrong class (the pathology label `live_multi_vs_shadow_collapse`)

### Interpretation — the failure mode is not "noise near the boundary"

v5's wrong predictions on heterogeneous columns are not marginal hedges at
moderate confidence. They are **confident wrong predictions that pass any
reasonable confidence threshold**:

- `support_chat_messages` → CREDENTIAL at **softmax-max** (1.000)
- `kafka_event_stream` → CREDENTIAL at 0.999
- `base64_encoded_payloads` → VIN at 0.934

And the class v5 picks depends on the fixture's feature shape:

- **Long + wordy + regex-multi-hit** → ADDRESS (log lines, apache log)
- **Long + wordy + JSON-like** → EMAIL or CREDENTIAL (json, kafka)
- **Long + wordy + conversational** → CREDENTIAL (chat messages)
- **Long + no-words + opaque-alphanumeric** → VIN (base64 payloads)

Each is explainable post hoc from the v5 training distribution — every
wrong class is the training-corpus class whose feature profile most
closely matches the OOD fixture — but none of them is *right*, and the
specific wrong answer is not predictable ex ante. The failure surface is
"v5 picks whichever class its linear decision boundary happens to
assign this out-of-distribution point to, at high confidence, no
uncertainty signal."

### Why a confidence threshold cannot fix this

Iteration 1 of this audit (YELLOW verdict, same-day) proposed a
confidence-threshold mitigation: use v5 when `shadow_confidence >= 0.85`
else fall back to the live cascade. The threshold was chosen from the
family-benchmark confidence distribution of correct corrections (p10 =
0.893) vs wrong predictions (p75 = 0.789) — a clean gap on the benchmark.

The 6-fixture evidence invalidates that reasoning. The benchmark's
"wrong predictions" distribution was measured on in-distribution rows
(synthetic single-entity shards from the same 7 training corpora) and
produced moderate confidences. On OOD heterogeneous input, v5 produces
*high* confidences on wrong predictions:

| Shadow prediction source | Median confidence | p90 confidence |
|---|---|---|
| Benchmark "correct corrections" (A bucket) | 0.978 | 0.999 |
| Benchmark "both wrong" (D bucket) | 0.611 | 0.873 |
| **OOD fixtures that collapsed wrong-class** | **0.934** | **1.000** |

The OOD wrong-class distribution is **indistinguishable from the
correct-corrections distribution** at the 0.85+ end. A threshold at
0.85 would keep 93.1% of correct in-distribution corrections *and* keep
the support_chat/kafka/base64 OOD collapses. There is no threshold that
separates them.

This is a well-documented property of linear/softmax classifiers on OOD
input (sometimes called "asymptotic overconfidence") — the model's
decision function does not know it is extrapolating, and the softmax
temperature does not decrease on OOD input. Confidence calibration is
not a structural fix for this class of failure.

### How prevalent is this in BQ

We don't have ground-truth numbers on real BQ column shapes, but
structurally the failure mode lives on:

- **Pub/Sub / Kafka event streams** → BQ is a common sink for these
- **Application logs** (Cloud Run, GAE, Stackdriver) → frequently routed to BQ for analytics
- **Audit logs** (Cloud Audit, Data Access) → routed to BQ as best practice
- **Webhook payloads** (Stripe, GitHub, Slack, etc.) → often stored raw in BQ `STRING` columns
- **Chat / support transcripts** → increasingly common as LLM workflows land in BQ
- **Base64-encoded JWT / opaque tokens** → stored in audit / auth tables
- **Mixed CSV-in-a-column** (denormalized ETL outputs) → common in data-lake tables

These shapes together account for a non-trivial fraction of BQ string
columns in practice — probably double-digit percentage. The exact number
is unknown without BQ production data, but the answer to "is this rare?"
is clearly "no."

### What directive promotion would mean for these columns

Under the Sprint 11 shadow semantics of "v5's single top-class prediction
is the directive answer," BQ customers with these column shapes would
see:

- **Chat/support transcripts** currently surfaced as EMAIL + PHONE (2
  correct findings) → reclassified as CREDENTIAL (1 wrong finding) at
  confidence 1.000
- **Kafka event streams** currently surfaced as EMAIL + IP_ADDRESS + URL
  (3 correct findings) → reclassified as CREDENTIAL (1 wrong finding) at
  confidence 0.999
- **Base64 token columns** currently producing no findings → reclassified
  as VIN at confidence 0.934

In each case, directive promotion would *downgrade* the BQ customer's
quality from current production. Items #1 and #2 add signal to v5 for
the subset of columns where mutual exclusivity holds (homogeneous
single-entity columns) without addressing the structural multi-label
failure mode at all.

---

## 4. Structural finding — softmax is the wrong primitive

The three audit questions surfaced three different symptoms of the same
root cause: **v5's softmax architecture models a problem shape that does
not match the real problem.**

### What softmax assumes

Multinomial logistic regression over K classes is a *mutually-exclusive*
classifier. The output is a probability distribution that must sum to 1:
`p(class_1) + p(class_2) + ... + p(class_K) = 1`. The architecture
encodes the assumption "exactly one of these K classes is true for this
input." The loss (categorical cross-entropy) penalizes the model for
putting probability mass on non-target classes, which drives the learned
parameters toward confident single-class decisions.

### What the problem actually is

PII classification in database columns is not a mutually-exclusive
problem. A column is a *container* of values, and containers can hold
multiple kinds of content:

- `user_email` column contains only emails — mutually-exclusive shape; softmax fits
- Application log column contains emails AND IPs AND API keys — multi-label shape; softmax structurally cannot represent

The cascade's `list[ClassificationFinding]` output natively handles
both. A homogeneous column returns a list of length 1; a heterogeneous
column returns a list of length N. The list length encodes the
multi-label cardinality without any architectural hack. Per-class
confidences are independent — EMAIL at 0.997 and IP_ADDRESS at 0.945 can
coexist because they are independent binary detections, not competing
softmax classes.

v5 layered a softmax over this naturally-multi-label problem and
re-imposed mutual exclusivity. The benchmark metrics look good because
the benchmark contains only mutually-exclusive test rows (single-entity
synthetic columns). The metrics would be bad — and actively worse than
the cascade — on any multi-entity test set. We did not have a multi-entity
test set until Q3 iteration 2 built one.

### Why this is not a modeling-choice question

"Should we use softmax or sigmoid?" is usually a modeling choice with
pros and cons on each side. In this case it is not — it is a
problem-formulation question. The answer depends on what PII-in-columns
**is**, not on what the model should be. Once you accept that BQ
columns include both homogeneous and heterogeneous shapes in
meaningful fractions, the mutually-exclusive assumption is false for a
meaningful fraction of inputs, and no amount of tuning / retraining /
capacity adjustment can rescue the formulation.

The three standard ways to align the model formulation with the
problem are:

1. **Per-class sigmoid + binary cross-entropy** (independent per-class
   decisions, no sum-to-1 constraint) — requires multi-label training data
2. **Span extraction models** like GLiNER, which predict *spans* of
   entities within sample values and naturally emit multi-label output
   when aggregated to the column level — the tool already exists in our
   engine cascade but is currently used as a column-level single-label
   classifier, which throws away its native capability
3. **Shape-gated routing** — detect the column shape first, then use the
   mutually-exclusive softmax classifier *only* on columns where the
   assumption holds, and a different tool on columns where it does not

Option 3 is particularly compelling because (a) it requires no new
training data, (b) it preserves v5's Sprint 11 wins on homogeneous
columns, (c) the shape detector is a pure heuristic with no model
training needed, and (d) it is the simplest route from current code to
a production system that matches the problem shape. See §6 for details.

---

## 5. Verdict — RED

**Aggregate: RED.** Sprint 12 Item #4 (directive promotion) is
**deferred indefinitely** pending structural reformulation.

### Why RED

| Axis | Target | Result | Status |
|---|---|---|---|
| Q1 LOCO unweighted | ≥ 0.30 | 0.4874 (A2 winner) | PASS |
| Q2 hard-gated delta | < 0.10 | +0.1031 | marginal (YELLOW) |
| Q3 heterogeneous aggregate | no wrong-class collapse | 3/6 high-confidence wrong, 2/6 medium-confidence wrong | **RED** |

Q3's RED is load-bearing. Q1 and Q2 are in a sense irrelevant — even if
Q1 LOCO were 0.90 and Q2 delta were 0.00, Q3 would still block directive
promotion because Q3 is not a "model quality" failure, it is a
"model architecture is wrong for the problem" failure. Adding training
data, capacity, or regularization does not fix it; only changing the
problem formulation does.

### Why not YELLOW (iteration 1)

Iteration 1 of the audit (same day, earlier) produced a YELLOW verdict
on the single-fixture evidence (Q3 only tested the `original_q3_log`
fixture at 0.688 confidence) and proposed a confidence-threshold
mitigation. The 5 additional fixtures added in iteration 2 invalidate
both the YELLOW verdict and the mitigation:

- **3/6 fixtures produce high-confidence wrong-class collapses** — the
  0.80 threshold that would have blocked iteration 1's Q3 now itself is
  exceeded, so the "trigger RED on ≥0.80" criterion fires
- **The confidence-threshold mitigation fails on base64, chat, and
  Kafka** — all three are above any reasonable threshold, and v5 would
  emit wrong directive predictions on these shapes

The iteration 1 YELLOW was wrong. It relied on the assumption "wrong
predictions live at moderate confidence," which held for in-distribution
benchmark rows but not for out-of-distribution heterogeneous fixtures.

### What ships in v0.12.0 under the RED verdict

Sprint 12 still ships meaningful improvements, just not directive
promotion:

1. **Option A train/serve skew fix** (Phase 5a) — ships. Fixes a real
   bug in the shadow observability stream that has existed since Sprint
   6; correct regardless of whether v5 is ever promoted.
2. **Item #1 `validator_rejected_credential_ratio`** — ships as a
   shadow feature. Improves shadow prediction quality on placeholder
   credential columns without affecting live output.
3. **Item #2 `has_dictionary_name_match_ratio`** — ships as a shadow
   feature. Improves shadow prediction quality on name-heavy columns
   without affecting live output.
4. **v5 artifact** (47 kept features, schema v5) — ships, kept in shadow
   mode. Sprint 11 shadow wins remain visible in the observability
   stream but never affect BQ's live classifications.

BQ's source of truth for v0.12.0 remains the live cascade output. This
is the same contract as v0.8.0 + v0.11.0; Sprint 12's feature additions
are pure shadow improvements.

---

## 6. Sprint 13 reframe — column-shape router

The original Sprint 13 item
(`gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation`)
was scoped as "build a gate classifier + train 3 specialized stage-2
classifiers for CREDENTIAL / PII / HETEROGENEOUS branches + new
`HeterogeneousColumnFinding` type." That item is closing as **wrong
framing** — it assumed the fix was "more classifiers" when the
evidence in §4 says the fix is "a routing layer that picks the right
tool for each column shape."

### Reframe: 3 shapes, 3 existing tools, 1 heuristic gate

The 6-fixture evidence plus the Q1 capacity finding plus the training-
data coverage analysis point at a three-way routing design:

| Column shape | Detector signal | Handler |
|---|---|---|
| **Structured single-entity** | `avg_len_norm < 0.3` AND cascade emits ≤ 1 entity type | Current cascade + v5 meta-classifier (v5's Sprint 11 wins live here) |
| **Free-text heterogeneous** | `avg_len_norm ≥ 0.3` AND `dict_word_ratio ≥ 0.1` | Per-value GLiNER span extraction + aggregation to column-level multi-label `list[ClassificationFinding]` |
| **Opaque long tokens** | `avg_len_norm ≥ 0.3` AND `dict_word_ratio < 0.1` AND cascade emits 0 entities | Tuned `secret_scanner` + entropy features |

All three branches emit `list[ClassificationFinding]` in the current type
shape, so no type-system changes are required. The gate itself is a
pure-heuristic function of column-level statistics — no model training
needed, no new training data, ~5 lines of code.

### Why GLiNER is the natural handler for heterogeneous

GLiNER (`GLiNERInferenceEngine` in the current engine cascade) is a span
extraction model. Its native capability is "given a text span, emit the
set of entity types found within it." Currently we use it as a
column-level single-label classifier — running it once on the
concatenated column and taking the top entity — which throws away the
per-value multi-span capability that is exactly what heterogeneous
columns need.

Reconfiguring GLiNER to run per-value and aggregate entity-type
mentions across 50 log lines would give us the multi-label output the
cascade approximates and v5 mangles. The aggregation logic is simple:
"for each entity type observed in any sample value, emit a
`ClassificationFinding` with confidence proportional to per-value
coverage." This matches the cascade's regex-based aggregation exactly
in shape, just with a stronger underlying detector for free-form text.

### Sprint 13 brief (draft — to be turned into backlog YAMLs in Phase 7)

**Item A — Column-shape router implementation (~1 week):**

- Implement `detect_column_shape()` helper in
  `data_classifier/orchestrator/` with the 3-way classification above
- Wire the orchestrator to route columns based on detected shape
- Preserve current behavior for structured-single (cascade + v5 meta
  unchanged)
- Route free-text-heterogeneous to a new per-value GLiNER handler
  (Item B)
- Route opaque-token to tuned `secret_scanner` (Item C)
- Add unit tests with known-shape fixtures and assert correct routing

**Item B — Per-value GLiNER aggregation (~1 week):**

- Refactor `GLiNERInferenceEngine` to support per-value mode in addition
  to current column-level mode
- Implement aggregation: for each entity type seen in any sample value,
  compute coverage ratio and emit a `ClassificationFinding` at
  confidence proportional to coverage
- Benchmark against the cascade on the 6 Q3 fixtures — directive
  win condition is "per-value GLiNER finds ≥ as many entity types as
  the cascade on each fixture, at comparable confidence"

**Item C — Opaque-token branch tuning (~3 days, optional):**

- Audit `secret_scanner` behavior on base64 / JWT / opaque hash
  fixtures
- Add entropy features if needed for subclassification (base64 JWT vs
  random hash vs placeholder secret)
- Optional — could defer to Sprint 14+ if Items A+B deliver most of
  the value

**Research questions (for the research branch to drive):**

1. What fraction of real BQ columns fall in each shape bucket? Requires
   sampling production column schemas; blocked until BQ integration
   team shares anonymized column-shape statistics.
2. Is the simple heuristic gate robust on edge cases? Needs a larger
   synthetic corpus covering 20+ column shapes (long IBAN columns,
   short UUID columns, mixed-case GUID columns, emoji-heavy chat
   columns, multi-byte CJK text, …) and measured misclassification
   rate.
3. Does per-value GLiNER generalize to non-English heterogeneous
   columns? Current GLiNER is English-only; Kafka streams and log
   columns in international deployments contain non-English content.

### Why this reframe is better than the original

| Criterion | Original Sprint 13 | Reframed Sprint 13 |
|---|---|---|
| Work estimate | 3–4 weeks | ~2 weeks |
| New model training needed? | Yes (3 specialized classifiers) | No |
| New training data needed? | Yes (multi-label corpus) | No |
| New type-system surface? | Yes (`HeterogeneousColumnFinding`) | No |
| Reuses existing infrastructure? | Partially | Fully (cascade, v5, GLiNER) |
| Preserves Sprint 11 v5 wins? | Partially (stage-2 classifier would be retrained) | Fully (v5 unchanged on homogeneous branch) |
| Structural correctness? | Yes (specialized classifiers) | Yes (right tool per shape) |

The reframe is smaller, safer, and preserves more of the work already
done. It is also more testable — the shape detector can be unit-tested
with fixture columns, the per-value GLiNER can be benchmarked
independently of the router, and the three branches can be developed
and deployed incrementally.

---

## 7. Audit thresholds reference

| Axis | GREEN | YELLOW (between) | RED |
|---|---|---|---|
| Q1 LOCO unweighted | ≥ 0.30 | — | < 0.20 |
| Q2 hard-gated delta | < 0.10 | 0.10 ≤ d < 0.15 | ≥ 0.15 |
| Q3 per-fixture | `graceful_degradation` or shadow ∈ live-entities | med-conf wrong-class collapse | high-conf (≥0.80) wrong-class collapse |
| Q3 aggregate | no fixture at worse than *one_of_live* | at least one med-conf-wrong | at least one high-conf-wrong |

Thresholds are defined in the backlog item
`backlog/sprint12-shadow-directive-promotion-gate-safety-analysis-memo.yaml`
and are mirrored at the top of `sprint12_safety_audit.py` as module
constants (`HETERO_COLLAPSE_CONFIDENCE = 0.80`, etc.).

---

## 8. Next steps

1. **Phase 7 handover** documents the shadow-only Sprint 12 outcome,
   the RED verdict evidence trail, and the Sprint 13 reframe above.
2. **Retire `sprint12-shadow-directive-promotion-gate.yaml`** to
   `status: retired` with pointer to this memo.
3. **Close
   `gated-meta-classifier-architecture-...q8-continuation.yaml`** as
   "wrong framing" with pointer to the column-shape router brief above.
4. **File 2–3 new Sprint 13 items** from §6's Item A / Item B / Item C
   drafts.
5. **Research branch sync** — the research branch owner uses this memo
   as the input for the next research steps (shape-detector robustness
   measurement, per-value GLiNER benchmark, BQ production column-shape
   sampling request).

---

## Artifact pointers

- **Harness:** `tests/benchmarks/meta_classifier/sprint12_safety_audit.py`
- **JSON output:** `/tmp/sprint12_safety_audit.json` (regenerable via
  `DATA_CLASSIFIER_DISABLE_ML=1 python -m tests.benchmarks.meta_classifier.sprint12_safety_audit`)
- **Model audited:** `data_classifier/models/meta_classifier_v5.pkl`
- **Training data:** `tests/benchmarks/meta_classifier/training_data.jsonl`
  (regenerable via `build_training_data`, not committed — see
  `.gitignore`)
- **Prior investigation:**
  `docs/research/meta_classifier/sprint12_item4_directive_promotion_investigation.md`
- **Backlog:**
  `backlog/sprint12-shadow-directive-promotion-gate-safety-analysis-memo.yaml`
  (this memo's AC) and
  `backlog/sprint12-shadow-directive-promotion-gate.yaml` (Item #4 it
  gates)
