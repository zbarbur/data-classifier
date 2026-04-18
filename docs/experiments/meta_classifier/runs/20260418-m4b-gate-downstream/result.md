# M4b — gate vs downstream evaluation harness

**Run date:** 2026-04-18
**Corpus:** family benchmark (9,870 shards across 7 corpora)
**Benchmark:** `tests/benchmarks/family_accuracy_benchmark.py` extended with
`gate_accuracy` and `per_branch_accuracy` surfaces.
**Run artifact:** `summary.json` + `predictions.jsonl` (this directory).
**Run mode:** `DATA_CLASSIFIER_DISABLE_ML=1` (canonical offline run).

## Headline

Router gate accuracy: **88.02%** on 9,870 shards. The 1,182 gate errors
decompose into two distinct failure modes that per-branch downstream
accuracy makes visible:

| Signal | Value | Interpretation |
|---|---|---|
| Gate accuracy (overall) | **0.8802** | 8,688 / 9,870 shards routed to correct branch |
| structured_single gate P / R | **0.963 / 0.890** | Good precision, some recall leak to wrong branches |
| free_text_heterogeneous gate P / R | **0.676 / 0.833** | Router over-routes structured shards here (360 FPs) |
| opaque_tokens gate P / R | **0.533 / 0.828** | Router over-routes structured shards here (543 FPs) — dominant error mode |

Per-branch downstream accuracy (oracle-routed by `true_shape`) shows
the cascade logic is strong on two of three branches:

| Branch | n | live cross_family | live macro_f1 | Verdict |
|---|---|---|---|---|
| structured_single | 8,220 | 0.135 | 0.935 | ✅ cascade works well |
| opaque_tokens | 750 | **0.024** | **0.968** | ✅ cascade works great |
| free_text_heterogeneous | 900 | 0.528 | 0.370 | ❌ cascade struggles |

## What M4b measures

Three evaluation surfaces, each answering a different question:

1. **Gate accuracy** (`summary.gate_accuracy`) — does the router route
   columns to the correct branch? Confusion matrix of predicted_shape
   × true_shape plus per-shape P/R/F1.

2. **Per-branch downstream accuracy** (`summary.per_branch_accuracy`) —
   given an oracle that routes by `true_shape` (bypassing router
   errors), does each branch's cascade classify correctly? Isolates
   routing errors from downstream errors.

3. **End-to-end accuracy** — the pre-existing `summary.live.overall` /
   `summary.shadow.overall` tiers, unchanged. Aggregates gate + downstream
   errors for a customer-visible view.

An end-to-end family_macro_f1 of 0.75 could decompose into either
"0.95 gate / 0.80 downstream" or "0.85 gate / 0.88 downstream." M4b
surfaces which is which.

## True-shape heuristic

`true_shape` is derived from `(corpus, ground_truth)` via:

```python
def _derive_true_shape(corpus, ground_truth):
    if corpus in {"secretbench", "gitleaks", "detect_secrets"}:
        return "free_text_heterogeneous"      # KV config-line fragments
    if ground_truth in {"BITCOIN_ADDRESS", "ETHEREUM_ADDRESS", "OPAQUE_SECRET"}:
        return "opaque_tokens"                 # single opaque-by-design blobs
    return "structured_single"                 # clean single-entity columns
```

**Grounding:** "does this column need multi-engine cascade to classify
correctly?" Scanner corpora have KV wrappers (`SECRET_KEY=xyz`,
`"CLIENT_SECRET": "..."`, `<Passwd value="..."/>`) that require
`column_name` + `regex` + `secret_scanner` — the definitional case for
heterogeneous. Crypto addresses and explicit opaque tokens are single
blobs needing shape-specific handling. Everything else is a clean
single-entity column where one engine suffices.

**Shape distribution under this heuristic:**
- structured_single: 8,220 (83.3%)
- free_text_heterogeneous: 900 (9.1%)
- opaque_tokens: 750 (7.6%)

**This heuristic deliberately does NOT align to the router's current
behavior.** Aligning would make gate accuracy trivially 100% and the
metric meaningless. Documented disagreements with the router are the
data M4b is designed to surface.

## Gate accuracy details

**Confusion matrix** (rows = true_shape, cols = predicted shape):

| true \\ pred | structured | free_text_het | opaque | no_shape |
|---|---|---|---|---|
| structured_single (n=8,220) | **7,317** | 360 | 543 | 0 |
| free_text_heterogeneous (n=900) | 150 | **750** | 0 | 0 |
| opaque_tokens (n=750) | 129 | 0 | **621** | 0 |

**Per-shape P/R/F1:**

| Shape | TP | FP | FN | P | R | F1 |
|---|---|---|---|---|---|---|
| structured_single | 7,317 | 279 | 903 | 0.963 | 0.890 | 0.925 |
| free_text_heterogeneous | 750 | 360 | 150 | 0.676 | 0.833 | 0.746 |
| opaque_tokens | 621 | 543 | 129 | 0.533 | 0.828 | 0.649 |

**Key findings:**

- **543 structured_single shards are routed to `opaque_tokens`** — the
  biggest single error mode. These are single-entity clean columns
  (gretel_en/HEALTH, gretel_en/SSN, etc.) whose values happen to have
  high entropy. Router heuristic triggers on entropy without enough
  context.
- **360 structured_single shards are routed to `free_text_heterogeneous`** —
  second-biggest error mode. Driven by gretel_en/ADDRESS (150/150 routed
  het) and nemotron/URL (150/150 routed het). Addresses and URLs have
  multi-component structure per value that trips the router's heterogeneity
  heuristic; functionally they are clean single-entity columns.
- **150 scanner NEG shards are routed to `structured_single`** —
  detect_secrets/NEGATIVE values (`PORT=8080`, `LOG_LEVEL=INFO`) are
  compact KV pairs that the router treats as structured rather than
  heterogeneous config-line fragments.
- **129 opaque_tokens shards are routed to `structured_single`** —
  mostly nemotron/OPAQUE_SECRET (111/150 routed structured) where short
  numeric values (`5487`, `234951`) look structured rather than opaque.

## Per-branch downstream details

### structured_single branch (n=8,220)

Live path: `cross_family_rate=0.135`, `macro_f1=0.935`. The cascade
classifies 86.5% of single-entity columns into the correct family.
Shadow path (meta-classifier): `macro_f1=0.914`, `emitted_xfam=0.0001`
(4 errors on 7,596 emitted predictions — the shadow path is nearly
perfect on rows it emits).

### free_text_heterogeneous branch (n=900, all scanner corpora)

Live path: `cross_family_rate=0.528`, `macro_f1=0.370`. The cascade
correctly classifies scanner corpus shards 47% of the time. This is
the **weakest branch**. Breakdown by corpus:

- secretbench/CREDENTIAL, gitleaks/CREDENTIAL, detect_secrets/CREDENTIAL:
  cascade variously under-fires or fires wrong family on these
  config-wrapped credentials.
- *_NEGATIVE: expected family is "NEGATIVE" (no secret); cascade over-fires.

This is consistent with the Sprint 13 research findings that motivated
the multi-label and per-value GLiNER work (the sibling `benchmark-emit-all-
cascade-findings-multi-label` backlog item).

### opaque_tokens branch (n=750)

Live path: `cross_family_rate=0.024`, `macro_f1=0.968`. The cascade
correctly classifies 97.6% of opaque-token columns. This is the
**strongest branch** — the pre-existing shape-specific opaque_token
handler (Sprint 13) is doing its job.

Shadow path: emits no predictions on this branch (by design, shadow
suppresses on non-structured shapes); `cross_family_rate_emitted` is
vacuously 0.0 because denominator is 0. This is the intended Sprint 13
shadow behavior, not a regression.

## Implications for ongoing work

1. **Sprint 14 cascade short-circuit fix** (backlog item:
   `cascade-suppress-short-circuit-on-heterogeneous-shape`) directly
   addresses the heterogeneous branch weakness — per-value regex needs
   to run on heterogeneous shards instead of short-circuiting on
   column_name confidence. M4b's 0.528 cross_family on this branch is
   the number that item should reduce.

2. **Router precision on `opaque_tokens` (0.533)** is a real issue
   worth filing. 543 clean structured shards are mis-routed to opaque.
   The per-branch metric shows this doesn't always cost accuracy (the
   opaque_token handler is lenient), but it's a latent risk.

3. **Gate accuracy ceiling is ~88%** under current heuristic. Even if
   downstream branches were perfect, end-to-end accuracy would cap
   there without router improvements. This decomposes the ~92.2%
   end-to-end `family_macro_f1` into "88% gate × 99+% structured /
   opaque downstream + 37% heterogeneous downstream" — the
   heterogeneous leg dominates residual error.

## Artifacts

- `summary.json` — canonical summary JSON with new `gate_accuracy` +
  `per_branch_accuracy` top-level keys (preserves pre-existing `live`,
  `shadow`, `n_shards`, etc.)
- `predictions.jsonl` — one row per shard with `true_shape` field
  added (all existing fields preserved)
- `run.log` — stderr output from the benchmark CLI run

## Reproduction

```bash
PYTHONPATH=. DATA_CLASSIFIER_DISABLE_ML=1 \\
    .venv/bin/python -m tests.benchmarks.family_accuracy_benchmark \\
    --out docs/experiments/meta_classifier/runs/20260418-m4b-gate-downstream/predictions.jsonl \\
    --summary docs/experiments/meta_classifier/runs/20260418-m4b-gate-downstream/summary.json
```

## Follow-ups

- **M4f** (filed this commit) — add `free_text_heterogeneous` shards
  from non-scanner corpora (Sprint 12 safety audit fixtures, synthesized
  log lines, CFPB Tier 7b) so heterogeneous downstream accuracy is
  measurable on more than just scanner KV shards.
- **Router precision on opaque_tokens** — worth filing a sibling
  investigation for Sprint 15+: what distinguishes `gretel_en/HEALTH`
  from `synthetic/BITCOIN_ADDRESS` structurally, and is there a cheap
  gate we can add?
