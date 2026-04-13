# Corpus License Audit

> **Scope:** Single source of truth for the licenses of all datasets and
> corpora consumed by data_classifier — training data, benchmark blind
> sets, fixtures shipped in `tests/fixtures/corpora/`, and anything
> downloaded by `scripts/download_corpora.py`.
>
> **Status of this document:** Authoritative as of 2026-04-13 (Sprint 9
> kickoff). Updated whenever a corpus is added, removed, or its license
> reverified.
>
> **Companion docs:** `docs/PATTERN_SOURCES.md` covers regex/pattern
> source licenses; this doc covers *datasets* used for training and
> benchmarking.

## Why this doc exists

Sprint 8's dataset landscape survey (`docs/experiments/meta_classifier/dataset_landscape.md`
on `research/meta-classifier @ cd3a5cc`) verified `ai4privacy/pii-masking-400k`'s
license directly by fetching `license.md` from HuggingFace — and discovered
it is **not** OSI-compatible despite appearances in the dataset README.
The custom Ai4Privacy license prohibits commercial use, redistribution,
and derivative works without explicit written permission.

The 300k variant (`ai4privacy/pii-masking-300k`) already integrated by
data_classifier since Sprint 4 shares the same custodian and was presumed
to share the same license terms. This doc records the verification, the
removal plan, and the discipline for verifying future corpora
**by fetching the actual LICENSE file, not trusting dataset card claims**.

## Verification discipline for new corpora

When adding a corpus, the ingestion item's acceptance criteria MUST
include:

1. **Direct LICENSE file fetch** from the dataset's source repo or
   HuggingFace repo (e.g., `https://huggingface.co/datasets/<org>/<name>/blob/main/LICENSE`
   or the equivalent GitHub path). Do NOT trust the "License" tag in
   the dataset card.
2. **Check for custom license files** (e.g., `license.md`, `LICENSE.txt`,
   `TERMS.md`) in addition to the canonical `LICENSE` file. Some
   datasets ship a standard-looking LICENSE and a separate restrictive
   terms file — both must be read.
3. **Record the verification in this file** with date, verifier (if
   agent), verification URL, and the verbatim license SPDX identifier
   or custom license classification.
4. **If the license is custom or non-OSI**, escalate to the user before
   ingesting. Do not silently proceed.

## Corpus licenses as of 2026-04-13

### ✅ Currently in use — OSI-compatible

| Corpus | License | SPDX | Verified on | How verified |
|---|---|---|---|---|
| [Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII) | CC BY 4.0 | `CC-BY-4.0` | 2026-04-11 | Dataset card |
| [SecretBench](https://github.com/setu1421/SecretBench) | MIT | `MIT` | 2026-04-11 | Direct LICENSE fetch |
| [gitleaks fixtures](https://github.com/gitleaks/gitleaks) | MIT | `MIT` | 2026-04-11 | Direct LICENSE fetch |
| [detect_secrets fixtures](https://github.com/Yelp/detect-secrets) | Apache-2.0 | `Apache-2.0` | 2026-04-11 | Direct LICENSE fetch |
| Synthetic (Faker-based, in-repo generator) | MIT (inherited from Faker) | `MIT` | n/a | Generated locally, no external data |

### 🟡 Being ingested — Sprint 9 in-flight

| Corpus | License | SPDX | Verified on | How verified | Status |
|---|---|---|---|---|---|
| [gretelai/gretel-pii-masking-en-v1](https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1) | Apache 2.0 | `Apache-2.0` | 2026-04-13 | Dataset card metadata — **to re-verify via direct LICENSE fetch before Sprint 9 close** | Ingest in progress on Sprint 9 |

### ⚠️ Flagged for removal — Sprint 9 chore `ai4privacy-license-reaudit-and-compliance-decision`

| Corpus | Claimed license | Actual license | Verified on | Action |
|---|---|---|---|---|
| [ai4privacy/pii-masking-300k](https://huggingface.co/datasets/ai4privacy/pii-masking-300k) | "Custom, research OK" (dataset card) | **Custom non-OSI — prohibits commercial use, redistribution, and derivative works** | 2026-04-13 via [license.md on pii-masking-400k](https://huggingface.co/datasets/ai4privacy/pii-masking-400k/blob/main/license.md) (same custodian, presumed identical terms) | Remove from training + benchmark pipeline; replace with Gretel-EN |

**Scope of Sprint 9 removal** (in-flight, tracked by backlog item
`ai4privacy-license-reaudit-and-compliance-decision`):

- `tests/fixtures/corpora/ai4privacy_sample.json` — committed 30 MB derivative, to remove + gitignore
- `tests/benchmarks/meta_classifier/training_data.jsonl` — 2 MB derivative, contains feature vectors derived from ai4privacy rows, to regenerate without ai4privacy
- `data_classifier/models/meta_classifier_v1.pkl` — retrain from new training data (without ai4privacy), re-publish
- `tests/benchmarks/corpus_loader.py::load_ai4privacy_corpus` — remove (or stub to raise)
- `tests/benchmarks/meta_classifier/build_training_data.py` — remove ai4privacy from the corpus list
- `tests/benchmarks/accuracy_benchmark.py` — remove ai4privacy from blind/named benchmark targets
- `scripts/download_corpora.py` — remove or deprecate the ai4privacy download command
- `docs/process/PROJECT_CONTEXT.md` — replace headline `Ai4Privacy 0.6667` baseline with new Gretel-EN number once measured
- Sprint handover footnotes (SPRINT3–SPRINT7, SPRINT4_BASELINE_REPORT,
  SPRINT5_BENCHMARK) — add pointer to this document. Historical F1
  numbers stay intact as records of what was measured at the time.

**No production exposure has occurred.** The BigQuery connector
consumer is still in development as of 2026-04-13, so ai4privacy has
never been shipped to a customer-serving runtime. This is an internal
state cleanup, not an emergency hotfix, but the removal still happens
in Sprint 9 to stop derivative artifacts accumulating.

### ❌ Anti-recommendations — do NOT ingest (from dataset landscape survey)

| Corpus | Reason |
|---|---|
| `ai4privacy/pii-masking-400k` | Same custom non-OSI license as the 300k variant |
| `bigcode/bigcode-pii-dataset` | Gated access, license not explicitly stated — cannot verify OSI compatibility |
| `bigcode/bigcode-pii-dataset-training` | Gated access, license not explicitly stated |
| `n2c2 / i2b2 2006-2018` | Credentialed access via Harvard DBMI DUA — not redistributable |
| `MIMIC-III / MIMIC-IV` | Credentialed PhysioNet access + DUA + CITI training — not redistributable |
| `MultiNERD` | CC BY-SA-NC 4.0 — NC clause makes it incompatible with MIT-licensed downstream use |

Source: `docs/experiments/meta_classifier/dataset_landscape.md` on
`research/meta-classifier` (Sprint 8 research commit `cd3a5cc`).

## Historical citation policy

Historical F1 numbers cited across sprint handover docs SPRINT4 through
SPRINT7 (and their associated benchmark report docs) were measured
against Ai4Privacy and remain accurate records of what the benchmark
runs produced at the time. **They are not rewritten when a corpus is
retired** — the numbers describe the measurement, not a recommendation.
Each cited document gets a footnote linking to this audit so future
readers can find the corpus provenance and license verification in one
place.

## Change log

| Date | Change | Author |
|---|---|---|
| 2026-04-13 | Initial audit. Ai4Privacy flagged for removal, Gretel-EN flagged as incoming replacement, 5 OSI-compatible corpora cataloged. | Sprint 9 kickoff (Claude, `sprint-start` skill) |
