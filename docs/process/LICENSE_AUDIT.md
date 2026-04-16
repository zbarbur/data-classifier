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

### 🟡 Being ingested — Sprint 10 in-flight

| Corpus | License | SPDX | Verified on | How verified | Status |
|---|---|---|---|---|---|
| [gretelai/gretel-pii-masking-en-v1](https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1) | Apache 2.0 | `Apache-2.0` | 2026-04-13 | Dataset card metadata — **to re-verify via direct LICENSE fetch before Sprint 9 close** | Ingest in progress on Sprint 9 |
| [gretelai/synthetic_pii_finance_multilingual](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) | Apache 2.0 | `Apache-2.0` | 2026-04-14 | README YAML frontmatter + HF cardData (see evidence below). **No standalone LICENSE file present in the dataset repo.** See "License verification evidence" note below for the fetched-file audit trail. | Sprint 10 ingest landing |

**License verification evidence for gretelai/synthetic_pii_finance_multilingual
(2026-04-14):**

The Sprint 9 Gretel-EN row flagged a "re-verify via direct LICENSE fetch"
follow-up. The direct-fetch approach returns 404 for this dataset
(confirmed 2026-04-14, same result as Gretel-EN, same custodian): the
repo tree contains only `data/`, `.gitattributes`, and `README.md` — no
`LICENSE`, `LICENSE.md`, `LICENSE.txt`, or `license.md` file is present.
The authoritative license sources we can fetch are:

1. **Direct GET `https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual/raw/main/README.md`**
   returns HTTP 200 with YAML frontmatter containing `license: apache-2.0`.
2. **HF datasets API `/api/datasets/gretelai/synthetic_pii_finance_multilingual`**
   returns `cardData.license: "apache-2.0"` and a `license:apache-2.0`
   tag. No contradictory custom terms file is indexed.
3. **Repo tree listing** (`/api/datasets/.../tree/main`) enumerates
   every file in the repo — no hidden `TERMS.md` or alternative license
   file exists.

This is the best we can do without a standalone LICENSE file and matches
the Sprint 9 Gretel-EN verification path. The risk profile is identical
to Gretel-EN: same custodian, same claim format, Apache-2.0 tag in the
HF index, no hidden custom terms. **Open follow-up:** both Gretel rows
should remain flagged until Gretel AI either adds a `LICENSE` file to
these repos or confirms the license in writing.

### ⚠️ Flagged for removal — Sprint 9 chore `ai4privacy-license-reaudit-and-compliance-decision`

| Corpus | Claimed license | Actual license | Verified on | Action |
|---|---|---|---|---|
| [ai4privacy/pii-masking-300k](https://huggingface.co/datasets/ai4privacy/pii-masking-300k) | "Custom, research OK" (dataset card) | **Custom non-OSI — prohibits commercial use, redistribution, and derivative works** | 2026-04-13 via [license.md on pii-masking-400k](https://huggingface.co/datasets/ai4privacy/pii-masking-400k/blob/main/license.md) (same custodian, presumed identical terms) | Remove from training + benchmark pipeline; replace with Gretel-EN |

> **2026-04-14 correction (Sprint 10 scope):** the Sprint 9 removal decision
> applies **only** to `ai4privacy/pii-masking-300k` and `ai4privacy/pii-masking-400k`
> — it is NOT a blanket ban on the `ai4privacy` namespace. Direct verification
> on 2026-04-14 via the HuggingFace dataset page for
> [`ai4privacy/pii-masking-openpii-1m`](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m)
> shows that variant is explicitly licensed **CC-BY-4.0** (commercial use,
> redistribution, and modification all permitted subject to attribution).
> The corpus page states: *"License: CC-BY-4.0. Copyright © 2026 Ai Suisse SA.
> Permitted Use: Research, commercial use, redistribution, and modification —
> subject to attribution requirements under CC-BY-4.0."* The larger
> `ai4privacy/pii-masking-2m` variant also exists with a claimed 82+ label
> taxonomy but its license has **not** been independently verified as of
> this date.
>
> **Discipline lesson:** the Sprint 9 verification correctly followed
> "fetch the actual license file, never trust dataset card metadata" for
> `pii-masking-400k`, but then **presumed** that finding generalized to
> `pii-masking-300k` because of shared custodian. The presumption got
> applied implicitly to the entire `ai4privacy` namespace rather than the
> single dataset under audit, and that stopped the Sprint 9 team from
> checking newer variants. Going forward, every corpus variant from a
> shared custodian gets its own direct license fetch — no presumption.
>
> **Sprint 11 follow-up item:**
> `review-ai4privacy-dataset-family-and-ingest-best-cc-by-4-0-variant-re-open-sprint-9-removal-decision`
> (P2 feature, sprint 11) — reviews all 4 ai4privacy variants with per-variant
> verification, picks the best fit (row count × taxonomy × language coverage),
> and ingests it as a Sprint 11 corpus addition. The Sprint 9 retraining
> without ai4privacy stands as the current meta-classifier baseline until
> that work lands.

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
| 2026-04-14 | Added `gretelai/synthetic_pii_finance_multilingual` under Sprint 10 in-flight ingestion. Same license-fetch evidence profile as Gretel-EN (no standalone LICENSE file; README frontmatter + HF cardData both tag Apache-2.0). Open follow-up: both Gretel rows to be promoted to "Currently in use" once written license confirmation is received from Gretel AI. | Sprint 10 ingest (Claude, `ingest-gretel-pii-finance-multilingual`) |
| 2026-04-14 | Added Kingfisher + gitleaks + Nosey Parker as credential pattern upstreams for the Sprint 10 secret key-name dictionary expansion. See "Credential-pattern upstreams" section below and `docs/process/CREDENTIAL_PATTERN_SOURCES.md` for per-entry attribution. | Sprint 10 item `expand-secret-key-names-dictionary` |
| 2026-04-14 | Correction footnote added to the Sprint 9 ai4privacy removal section: blanket `ai4privacy` namespace ban was wrong. `ai4privacy/pii-masking-openpii-1m` is CC-BY-4.0 (commercial + redistribution + modification permitted with attribution). Sprint 11 follow-up item `review-ai4privacy-dataset-family-and-ingest-best-cc-by-4-0-variant` filed to review all 4 variants and re-ingest the best. | Sprint 10 correction |

## Credential-pattern upstreams (Sprint 10)

Unlike the dataset/corpus entries above, these three repositories provide
**derivation sources for key-name patterns** — no regex, YAML rule file,
or code has been copied verbatim.  The Sprint 10 harvest curates key-name
patterns derived from each upstream's rule *ids*, with each derived
pattern traceable to an exact rule id at a pinned SHA.  See
`scripts/ingest_credential_patterns.py` for the script and
`docs/process/CREDENTIAL_PATTERN_SOURCES.md` for per-entry attribution.

### In use — OSI-compatible, attribution recorded per entry

| Source | License | SPDX | Pinned SHA | Role in harvest | Verified on | How verified |
|---|---|---|---|---|---|---|
| [MongoDB Kingfisher](https://github.com/mongodb/kingfisher) | Apache 2.0 | `Apache-2.0` | `be0ce3bae0b14240bb2781ab6ee2b5c65e02144b` | Primary (~50 SaaS + cloud + DB key-names) | 2026-04-14 | Shallow clone + rule-id existence check in `scripts/ingest_credential_patterns.py --clone-sources` |
| [gitleaks](https://github.com/gitleaks/gitleaks) | MIT | `MIT` | `8863af47d64c3681422523e36837957c74d4af4b` | Secondary (~20 CI/CD + webhook + OAuth) | 2026-04-14 | Same |
| [Praetorian Nosey Parker](https://github.com/praetorian-inc/noseyparker) | Apache 2.0 | `Apache-2.0` | `2e6e7f36ce36619852532bbe698d8cb7a26d2da7` | Precision cross-check (~10 Jenkins/Django/generic) | 2026-04-14 | Same |

### Explicitly excluded — license-incompatible

| Source | License | Reason |
|---|---|---|
| [trufflehog](https://github.com/trufflesecurity/trufflehog) | AGPL-3.0 | Copyleft + network-use clause incompatible with data_classifier's MIT downstream. Consulted for gap-identification only; no regex or code was copied. |
| [Semgrep Rules](https://github.com/semgrep/semgrep-rules) | SRL v1.0 | Semgrep Rules License v1.0 is non-OSI and restricts redistribution. |
| [Atlassian SAST](https://github.com/atlassian/gostatic-check-secrets) | LGPL-2.1 | LGPL linking clauses incompatible with static-library downstream use. |
