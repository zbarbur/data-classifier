# Meta-Classifier Corpus Diversity — Closing the Secret-Scanner Signal Gap

> **Date:** 2026-04-12
> **Sprint:** 6, Phase 2 (meta-classifier training)
> **Author:** research pass for item `meta-classifier-for-learned-engine-arbitration...`
> **Scope:** Which additional PII / credential corpora to integrate into the Phase 1
> training-data builder (`tests/benchmarks/meta_classifier/build_training_data.py`)
> to give the meta-classifier a non-zero `secret_scanner_confidence` signal on
> credential-bearing rows.

---

## 1. Problem statement

Current Phase 1 training rows come from three sources wired into
`tests/benchmarks/corpus_loader.py`:

| Source | Rows on disk | Integrated? |
|---|---|---|
| `ai4privacy_sample.json` | 31 MB / ~621K raw values | ✅ `load_ai4privacy_corpus` |
| `nemotron_sample.json` | 12 MB / ~1.75M raw values | ✅ `load_nemotron_corpus` |
| Faker synthetic | generated on demand | ✅ `load_synthetic_corpus` |

The 15-feature vector in `data_classifier/orchestrator/meta_classifier.py`
includes `secret_scanner_confidence` and `has_secret_indicators`. On the
current training set those two features are **effectively constant zero** for
~342 credential-labelled rows.

### Root cause — not a bug

`secret_scanner` is a *KV-context* scanner. It requires a key token adjacent
to the value (`password = ...`, `"api_key": "..."`, `AWS_SECRET_ACCESS_KEY=...`).
Ai4Privacy and Nemotron, however, expose PII spans as *bare* strings:

- Ai4Privacy `PASS` span → `"hunter2"` (bare password, no surrounding key)
- Nemotron `password` span → `"NVidia#2023!"` (bare, no `password=` context)

Both corpora strip the surrounding text when `_records_to_corpus` groups
values by entity type into `sample_values`. So even if we remap every
`PASS`/`password` label to `CREDENTIAL`, the scanner still sees only naked
strings — no indicator, no fire, zero signal for the meta-classifier.

**Implication:** the fix is not to mine more bare-credential corpora. It is
to mine corpora whose raw records *preserve the `key = value` context* so
`secret_scanner` can fire on them.

---

## 2. Inventory — what is already on disk

```
tests/fixtures/corpora/
├── ai4privacy_sample.json       31 MB   ✅ loader wired
├── nemotron_sample.json         12 MB   ✅ loader wired
├── secretbench_sample.json     170 KB   ❌ NOT wired (1,068 rows)
├── gitleaks_fixtures.json       42 KB   ❌ NOT wired (171 rows)
└── detect_secrets_fixtures.json  2 KB   ❌ NOT wired (13 rows)
```

`scripts/download_corpora.py` already knows how to refresh all four of the
top-named corpora (`--corpus secretbench`, `--corpus gitleaks`, etc.). The
fixtures on disk match the schema the loader expects (`entity_type`,
`value`, plus optional `is_secret`, `source_type`).

### Cross-reference to P3 backlog items

| Backlog item (all P3, sprint_target null) | Status on disk | Needs fresh pull? |
|---|---|---|
| `external-corpus-integration-ai4privacy-...` | ✅ sample present, loader wired | No — sample covers Phase 2 needs |
| `external-corpus-integration-nemotron-...` | ✅ sample present, loader wired | No — same |
| `external-corpus-integration-secretbench-fpsecretbench-...` | ✅ sample present, **not wired** | No download needed, **wire it up** |
| `external-corpus-integration-presidio-cross-validation-...` | ❌ not on disk; this is a *comparator*, not a corpus | N/A for Phase 2 — benchmarking tool, not training data |
| `external-corpus-starpii-...-gated-access` | ❌ not on disk; HF gated | Yes, but only if Phase 2 budget allows |
| `external-corpus-nightfall-sample-datasets-...` | ❌ not on disk | Yes, optional |

Plus a fifth fixture, `detect_secrets_fixtures.json`, which has no backlog
item but ships on disk with 13 hand-curated positives.

---

## 3. SecretBench (`secretbench_sample.json`) — integration analysis

### 3.1 Format

```json
[
  {
    "entity_type": "CREDENTIAL",
    "value": "https://AKIAI44QH8DHBEXAMPLE/this.com",
    "source": "secretbench",
    "is_secret": true
  },
  {
    "entity_type": "CREDENTIAL",
    "value": "password         : password",
    "source": "secretbench",
    "is_secret": true
  }
]
```

**1,068 rows**, **all labelled `CREDENTIAL`**, perfectly balanced at **516 TP
/ 552 TN**. The loader schema (`entity_type`, `value`) already matches.

### 3.2 Does it have the KV structure `secret_scanner` needs?

**Yes — in ~82% of rows.** 873 / 1068 values contain `=` or `:`. Sampled
positives include:

- `"password": password || null` — JSON/JS KV
- `password         : password` — colon KV
- `internal func logIn(email: String, password: String) {` — typed-signature KV
- `client_secret=bP88Q~rcBcYjzzOhg1Hnn76Wm3jGgakZiZ.8vMgR` — equals KV
- `AKIA...EXAMPLE` embedded in a URL — no KV, pure-regex territory

This is precisely the signal shape the current training set lacks. Wiring
SecretBench should immediately turn `secret_scanner_confidence` into a
non-trivial feature for the L2 logistic regression.

### 3.3 Entity-type mapping

Trivial: the corpus ships with `entity_type: "CREDENTIAL"` already. The only
mapping work is deciding what to do with the **TN rows** (`is_secret: false`).
Two options:

| Option | Behaviour | Trade-off |
|---|---|---|
| **A. Emit TN rows with `ground_truth = "NOT_CREDENTIAL"`** (new pseudo-label) | Trains the meta-classifier to push `secret_scanner` confidence *down* when the scanner wrongly fires on placeholders | Requires a new sentinel label; one-line change to `extract_training_row` to allow it |
| **B. Drop TN rows** | Simpler; training set only sees positives | Loses half the value of the corpus — the TN set is the *hardest* signal for calibration |

**Recommendation: Option A.** The meta-classifier's whole purpose is to
arbitrate when engines disagree; discarding the hardest disagreement cases
defeats the point. A new `NOT_CREDENTIAL` ground-truth label costs ~5 LOC
in `build_training_data.py` and exposes the model to negative supervision
(`secret_scanner` says CREDENTIAL + ground truth is not → lower weight).

### 3.4 Integration cost

| Step | LOC | Hours |
|---|---|---|
| Add `load_secretbench_corpus(blind)` in `corpus_loader.py` | ~25 | 0.5 |
| Extend `load_corpus` dispatcher | ~5 | 0.1 |
| Wire into `build_training_data.py` (mirrors Nemotron/Ai4Privacy calls) | ~10 | 0.2 |
| Handle `is_secret=False` → `NOT_CREDENTIAL` ground truth | ~5 | 0.2 |
| Unit test (load → 1068 rows, expected class balance) | ~30 | 0.5 |
| Training-data stats update (new rows in report) | — | 0.2 |
| **Total** | **~75** | **~1.7 h** |

---

## 4. Gitleaks (`gitleaks_fixtures.json`) — integration analysis

### 4.1 Format

Same schema as SecretBench plus a `source_type` field naming the gitleaks
rule id (`aws`, `gcp`, `azure`, `1password`, `hashicorp`, ...).

- **171 rows total** (30 TP / 141 TN — skewed heavily toward *negative*
  look-alikes, which is by design: gitleaks mines false positives from real
  code to harden its own rules)
- All `entity_type = "CREDENTIAL"`
- Top `source_type` counts: gcp 21, generic 21, curl 17, azure 13, huggingface 13, sourcegraph 10, slack 6, sumologic 6, 1password 5, aws 5, facebook 5, meraki 5, privatekey 5, etsy 4, grafana 4, infracost 4, octopusdeploy 4, discord 3, artifactory 2, clickhouse 2, **hashicorp 1**

### 4.2 KV structure?

**Yes**, and often richer than SecretBench. Sampled TPs:

- `client_secret=bP88Q~rcBcYjzzOhg1Hnn76Wm3jGgakZiZ.8vMgR`
- `AUTH_CLIENTSECRET = _V28Q~IC8qxmlWNpHuDm34JlbKv9LXV5MvUR3a-P`
- `<value xsi:type="xsd:string">~Gg8Q~nVhlLi2vpg_nXBGqFsbGK-t~Hus1JmTa0y</value>` (XML-structured)
- `client_secret: .IQ8Q~79R7TOWOspFnWcEG-dYt4KXqFqxK16cxr` (YAML-structured)

This is higher-fidelity than SecretBench for `secret_scanner` specifically
(`secret_scanner` was designed around the `client_secret=`-style shapes
gitleaks rules emit).

### 4.3 Overlap with the Hashicorp XOR fix — **yes, and it is safe**

Commit `3773e25 fix: suppress 37 gitleaks placeholder false positives in
secret_scanner` added an XOR-encoded Hashicorp Terraform Cloud fixture
(`xxxxxxxxxxxxxx.atlasv1.xxxxxxx...`) to the suppression test, encoded at
rest because GitHub push protection can mis-identify the `.atlasv1.`
signature.

**Status in `gitleaks_fixtures.json`:** exactly **1 hashicorp row**, plaintext,
labelled `is_secret: false`:

```
token        = "xxxxxxxxxxxxxx.atlasv1.xxxx..." [source_type=hashicorp, is_secret=False]
```

Because the label is `False`, integrating this row as training data
**reinforces** the suppression behaviour commit `3773e25` introduced: the
meta-classifier will see `secret_scanner` firing on a placeholder that
the ground truth marks as non-credential, and learn to down-weight
scanner confidence in that context. No label conflict, no regression risk.

**Residual risk:** the raw file is already committed to the repo; if
GitHub push protection has not flagged it so far, integrating it into
the training-data build step does not change the on-disk bytes. No new
risk introduced.

### 4.4 Entity-type mapping

Same as SecretBench — `CREDENTIAL` is already set. `is_secret=false` rows
should use the same `NOT_CREDENTIAL` ground-truth handling (see §3.3,
Option A).

**Side-benefit:** `source_type` can become an additional stratification
key for the training-data stats report (per-vendor coverage), useful for
Phase 3 drift monitoring.

### 4.5 Integration cost

| Step | LOC | Hours |
|---|---|---|
| `load_gitleaks_corpus(blind)` in `corpus_loader.py` | ~25 | 0.4 |
| Dispatcher entry + `build_training_data` wiring | ~10 | 0.2 |
| Unit test (load → 171 rows, TP/TN counts, hashicorp row present) | ~25 | 0.4 |
| Shared with SecretBench: `NOT_CREDENTIAL` ground-truth plumbing | — | 0 (already done in §3.4) |
| **Total (if SecretBench shipped first)** | **~60** | **~1.0 h** |

---

## 5. Remaining P3 corpora — not on disk

The five items below are the non-downloaded backlog candidates. None of
them are blocking Phase 2, but the research request called for
license/URL/size/cost numbers so the Phase 3 plan has them.

### 5.1 SecretBench — *full* (not just sample)

| Field | Value |
|---|---|
| License | MIT (`brendtmcfeeley/SecretBench`) |
| Source | `https://raw.githubusercontent.com/brendtmcfeeley/SecretBench/main/battery/passwords.txt` |
| Full size | ~4,200 annotated lines (vs 1,068 in sample) |
| Download size | ~300 KB |
| Integration cost | **~0 h** beyond §3 — `scripts/download_corpora.py --corpus secretbench --max-per-type 9999` already works. Just rerun with a higher cap. |
| Value-add over sample | ~4× more KV-structured credential lines |

### 5.2 Nemotron-PII — full

| Field | Value |
|---|---|
| License | CC BY 4.0 |
| Source | `nvidia/Nemotron-PII` on HuggingFace |
| Size | ~100K records / ~1.75M raw spans |
| Download size | ~500 MB parquet |
| Integration cost | **~0 h beyond the sample** — existing loader already consumes the full-size file if placed at `tests/fixtures/corpora/nemotron_sample.json`. Bump `--max-per-type` in the download script. |
| Value-add for Phase 2 | **Low** — bare-value corpus, does not address the secret-scanner signal gap |

### 5.3 Ai4Privacy — full

| Field | Value |
|---|---|
| License | Apache 2.0 |
| Source | `ai4privacy/pii-masking-300k` on HuggingFace |
| Size | ~225K rows / ~621K PII spans |
| Download size | ~300 MB parquet |
| Integration cost | **~0 h** — same as Nemotron, just raise the cap |
| Value-add for Phase 2 | **Low** — bare-value corpus, same reason |

### 5.4 Presidio (comparator, **not a corpus**)

The backlog item `external-corpus-integration-presidio-cross-validation-comparison-tests`
is mislabelled in our title taxonomy. Presidio is a **benchmarking
comparator** (run their model on our corpora, emit F1 disagreement JSONL),
not a training-data source. Out of scope for Phase 2. Keep for Sprint 7 as
already tagged.

### 5.5 StarPII

| Field | Value |
|---|---|
| License | OpenRAIL + gated (HF access request required) |
| Source | `bigcode/bigcode-pii-dataset` (StarPII annotations) on HuggingFace |
| Size | ~20K annotated secrets-in-code snippets |
| Download size | ~80 MB |
| Integration cost | **~4 h** — gated access request (human in the loop), custom ETL (snippet-in-context not bare value), new loader function |
| Value-add for Phase 2 | **High** — in-code context preserves KV structure. But the gated-access delay makes it unsuitable as Phase 2's *first* corpus. |

### 5.6 Nightfall sample datasets

| Field | Value |
|---|---|
| License | Proprietary / Nightfall sample pack ToS — **must be vetted by legal before merging** |
| Source | `https://nightfall.ai/` developer sample pack (email gated) |
| Size | Unknown without download; marketing claim is "thousands of labelled samples" |
| Download size | Unknown |
| Integration cost | **~6 h** including license review |
| Value-add for Phase 2 | **Unknown** — likely marketing-grade, probably low uniqueness vs SecretBench + gitleaks + StarPII |
| **Recommendation** | **Defer indefinitely** unless legal review clears it — not worth the risk for a training-data source we already have better alternatives for. |

### 5.7 `detect_secrets` fixtures (already on disk, bonus)

Not in the 6 backlog items, but 13 curated positives ship in
`detect_secrets_fixtures.json` and are not wired. Free ~0.5 h win to
integrate alongside gitleaks — the schema already has `type`, `value`,
`expected_detected`, `layer` so it plugs straight into the same
dispatcher.

---

## 6. Ranked recommendation — Phase 2 order

> **Primary goal:** give `secret_scanner_confidence` and
> `has_secret_indicators` *non-zero* variance in the meta-classifier
> training set, without spending more than one dev-day on corpus plumbing.

| # | Corpus | Why first | Effort | Secret-scanner signal | Risk |
|---|---|---|---|---|---|
| **1** | **SecretBench sample (already on disk)** | Largest KV-structured credential set we own; 1,068 rows; perfectly balanced TP/TN; schema already loader-compatible | **~1.7 h** | **High** — 82% of rows are KV-shaped | None. All-synthetic / redacted-public. |
| **2** | **Gitleaks fixtures (already on disk)** | Adds *vendor-stratified* KV shapes (azure, gcp, aws, 1password, hashicorp, ...) so the model sees the same feature across many rule families, not just one | **~1.0 h** | **High** — KV shapes include XML/YAML/bash/env variants | Hashicorp row is a *confirmed* alignment with the XOR-suppression commit, `is_secret=false` label reinforces correct behaviour |
| **3** | `detect_secrets_fixtures.json` (already on disk, bonus) | Free 13 hand-curated positives; zero extra plumbing if dispatcher is generalised | **~0.5 h** | Medium — bare-value heavy, but covers JWT / basic auth that neither other corpus has | None |
| 4 | SecretBench **full** (fresh pull) | 4× more rows, same shape — only pursue if (1)–(3) do not move F1 enough | ~0.5 h pull + rerun training | Same shape as (1) | None |
| 5 | StarPII (gated HF request) | Best *in-code* context corpus available, but the gated-access request blocks start | ~4 h + wait | High | Access delay |
| — | Presidio | Comparator, not training data | — | — | Out of scope for Phase 2 |
| — | Nightfall | Legal review required, unclear uniqueness | ≥6 h | Unknown | Proprietary ToS |
| — | Nemotron / Ai4Privacy **full** | Same shape as current sample, does not close the gap | ~0.5 h each | **Zero** — bare values | — |

### 6.1 Concrete Phase 2 recommendation

> **Integrate SecretBench + gitleaks + detect_secrets in a single PR.**
> Total estimated effort: **~3.2 hours of plumbing + tests**. All three
> fixtures already exist on disk in the right schema, so there is no
> download or ETL step. Everything gates on one shared change:
> generalising `_records_to_corpus` (and `extract_training_row`) to
> understand a new `NOT_CREDENTIAL` sentinel ground truth so the TN rows
> are not thrown away.

Sequence inside the PR:

1. Add `NOT_CREDENTIAL` handling to `build_training_data.py` (shared plumbing)
2. `load_secretbench_corpus` + loader unit test
3. `load_gitleaks_corpus` + loader unit test (include hashicorp assertion)
4. `load_detect_secrets_corpus` + loader unit test
5. Extend `load_corpus("all", ...)` to include the three new sources
6. Rerun `python -m tests.benchmarks.meta_classifier.build_training_data`
   and update the stats report comment with the new class balance +
   per-feature coverage
7. Retrain the Phase 2 logistic regression, report offline F1 delta on
   Nemotron-blind and Ai4Privacy-blind (the acceptance-criteria gates)

### 6.2 What *not* to do this sprint

- Do **not** pull the full-size Nemotron or Ai4Privacy datasets. They
  will multiply row count without moving the signal we care about.
- Do **not** start StarPII until Phase 2 F1 is measured — it may turn
  out the three on-disk corpora already close the gap, in which case
  the gated-access request is unnecessary cost.
- Do **not** integrate Presidio under this item — it is a comparator
  scope and belongs in Sprint 7 per its existing tag.

---

## 7. Open questions for the Phase 2 design review

1. **`NOT_CREDENTIAL` sentinel naming** — is there a more general
   "negative" convention the meta-classifier already supports (e.g.
   an explicit "NONE" label), or is this the first time ground truth
   encodes negative supervision? If the latter, the label name should be
   agreed before the PR lands.
2. **Stratification weight** — gitleaks ships 4.7× more negatives than
   positives. Should the training-data builder down-sample negatives
   to match SecretBench's 1:1 ratio, or let the L2 regulariser handle
   it?
3. **`source_type` feature** — gitleaks exposes per-vendor rule ids.
   Worth plumbing through as a categorical feature for Phase 2, or
   deferred to Phase 3?

These are cheap to answer in review and do not gate the research
recommendation.

---

## Appendix A — file paths touched by the recommendation

- `tests/benchmarks/corpus_loader.py` — new `load_secretbench_corpus`, `load_gitleaks_corpus`, `load_detect_secrets_corpus`, dispatcher
- `tests/benchmarks/meta_classifier/build_training_data.py` — new rows-from-corpus loops, `NOT_CREDENTIAL` handling
- `tests/benchmarks/meta_classifier/extract_features.py` — confirm `NOT_CREDENTIAL` is not silently dropped
- `tests/test_corpus_loader.py` (new file or extension) — unit tests for each loader
- `docs/research/meta_classifier/corpus_diversity.md` — this doc

No code outside `docs/research/` is modified by this research pass.
