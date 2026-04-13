# Dataset Landscape Survey for data_classifier — Credential Bias Diversification

> **Produced by:** general-purpose research subagent (dispatched 2026-04-13)
> **Purpose:** Identify open-source labeled datasets to diversify the data_classifier training corpora and break the credential-pure-corpus bias that drives the meta-classifier's LOCO collapse.
> **Constraint:** Open-source / free only. No paid, commercial, vendor-trial, or non-OSI-licensed datasets.
> **Source of truth:** This file is authoritative for "what training datasets exist and can we use them?" Do not re-survey — update this file instead.
> **Companion doc:** `pattern_source_landscape.md` covers regex/pattern sources; this doc covers training datasets only. Two different topics.

## Why this research was commissioned

The data_classifier currently trains its meta-classifier on 6 corpora with a structural bias: **3 of 6 corpora (gitleaks, secretbench, detect_secrets) are label-pure** — they contain only CREDENTIAL and NEGATIVE rows, no PII or financial labels. The other 3 (ai4privacy, nemotron, synthetic) carry the PII labels.

This makes leave-one-corpus-out (LOCO) evaluation a "predict corpus = predict label" shortcut for credentials. The model learns corpus fingerprints (especially `heuristic_avg_length`) instead of learning what credentials actually look like as values. Q3 LOCO investigation, Q5 feature distribution audit, Q6 PII-only retraining, and E10 GLiNER-features experiment all confirmed this is structural, not a CV bug.

The fix is NOT more credential corpora — those make the bias worse. The fix is corpora that **contain credentials AND PII AND financial AND health labels mixed together in realistic structured-database proportions**.

## Executive summary

The single highest-value finding is **Gretel's two open datasets** (`gretel-pii-masking-en-v1` and `synthetic_pii_finance_multilingual`), both Apache 2.0, both synthetic, and — critically — both contain **credentials, PII, financial, and health labels mixed together within the same documents**, in realistic structured-document contexts (banking forms, insurance claims, healthcare records). These are exactly the "grail" Tier 1 corpora the research question asked for, and they exist in the open.

Paired with `beki/privy` (MIT, 26 entity types across SQL/JSON/HTML protocol traces) and the smaller `E3-JSI/synthetic-multi-pii-ner-v1` (MIT, 7 languages, 5 domains), we have enough to move from 6 corpora with 3 label-pure outliers to **10-11 corpora with every new addition being mixed-label**.

**The credential-bias problem is fixable with open data.** It does not require 15+ corpora. A meaningful dent requires ~4 well-chosen additions, all found in this survey.

### CRITICAL ANTI-FINDING — license risk on a corpus we already use

**`ai4privacy/pii-masking-400k` is NOT open source** despite appearances — its `license.md` is a custom AI4Privacy license that prohibits redistribution and commercial use. The 300k version already in use by data_classifier should be **re-audited against this license text immediately** — same custodian, likely same license. If true, this is a compliance issue independent of this research and must be escalated. The 400k must NOT be pulled.

## Tier 1 — Mixed-label corpora (highest value)

### 1. gretelai/gretel-pii-masking-en-v1

- **URL:** https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1
- **License:** Apache 2.0 (verified at dataset metadata, standard Apache clause, no additional restrictions)
- **Size:** 60,000 rows (50k train / 5k val / 5k test), 25.1 MB
- **Format:** Parquet
- **Annotation:** Span-level labels (`{entity, types}` arrays), 43+ entity types
- **Coverage:** 47 domains spanning Healthcare, Banking & Financial Services, Government, Manufacturing, Cybersecurity, Education. Single documents combine e.g. `medical_record_number` (26k instances) + `date_of_birth` (23k) + `ssn` (16k) + `credit_card_number` (6k) + passwords/API keys.
- **ETL effort:** **S** — span labels directly convertible via Ai4Privacy-style ETL pattern
- **Why mixed:** A healthcare document may carry SSN + DOB + MRN + credit card in one record. A banking document may carry name + account + IPs + credentials. Exactly the realistic distribution structure the meta-classifier needs.
- **Bias impact:** High. Adds ~60k mixed rows where credentials sit next to health + financial + PII, destroying the "credentials live only alongside negative corpus fingerprints" shortcut.

### 2. gretelai/synthetic_pii_finance_multilingual

- **URL:** https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual
- **License:** Apache 2.0 (stated in dataset metadata; note the README includes a "not harmful" aspirational clause — not license-altering for training use)
- **Size:** 55,940 rows (50.3k train / 5.6k test)
- **Format:** Parquet
- **Languages:** EN, FR, DE, NL, ES, IT, SV (7)
- **Annotation:** Span-level (`pii_spans` column with `{start, end, label}`), 29+ entity types including `name`, `ssn`, `iban`, `bban`, `swift_bic_code`, `account_pin`, `api_key`, `password`, `credit_card_number`, `driver_license_number`, `customer_id`, `employee_id`, plus dates, addresses, phone
- **Coverage:** 60 financial document types (loan agreements, bank statements, tax forms, insurance policies, SWIFT messages, insurance claim forms). Insurance claims and insurance policies contain health expense/claim data as free-text context.
- **ETL effort:** **S**
- **Why Tier 1 despite being "finance":** The credentials (`api_key`, `password`, `account_pin`) and health-adjacent content coexist with financial labels in the same documents. Critically, this is the **only** open dataset found where API keys appear labeled *inside real-looking financial paperwork contexts* rather than in source code.
- **Bias impact:** Very high. Directly attacks `heuristic_avg_length` corpus fingerprint because credentials here live in long-form financial prose, not short credential-only lines.

### 3. beki/privy

- **URL:** https://huggingface.co/datasets/beki/privy
- **License:** MIT (verified in dataset metadata — re-verify by direct LICENSE fetch before ingestion)
- **Size:** 100k-400k range (exact count not specified), 308 MB
- **Format:** **Protocol traces — JSON, SQL (PostgreSQL + MySQL), HTML, XML** — the only open corpus found that directly represents structured-database-adjacent formats rather than prose
- **Annotation:** 26 entity types (PERSON, ORG, LOCATION, CREDIT_CARD, IBAN, ROUTING_NUMBER, SWIFT, US_BANK_NUMBER, US_SSN, US_PASSPORT, US_DRIVER_LICENSE, US_ITIN, EMAIL, PHONE, URL, IP_ADDRESS, MAC_ADDRESS, IMEI, PASSWORD, DATE_TIME, TITLE, COORDINATE, CURRENCY, AGE, LICENSE_PLATE, NRP)
- **ETL effort:** **M** — SQL trace parsing needs a custom extractor, but the format is closer to our target domain (database columns) than any other corpus in the set, so extra effort pays double
- **Caveat:** Last updated ~3 years ago. **Verify still accessible.** This is marked "verify accessible" per the process note for pre-2024 data. Generated from OpenAPI specs, so schema is programmatic/stable.
- **Why Tier 1:** PASSWORD labels inside JSON and SQL payloads directly, no health labels but mixes credentials + financial + ID + contact in single traces.
- **Bias impact:** High structural fit. This is the closest thing to "labeled structured database columns with mixed sensitive types" in the open-data landscape.

## Tier 2 — PII-pure (or PII-heavy mixed) corpora to add

### 4. E3-JSI/synthetic-multi-pii-ner-v1

- **URL:** https://huggingface.co/datasets/E3-JSI/synthetic-multi-pii-ner-v1
- **License:** MIT (verified in dataset metadata — re-verify before ingestion)
- **Size:** 2,970 rows (small — supplemental, not primary)
- **Format:** Parquet, token-classification
- **Languages:** EN, FR, DE, EL (Greek), NL, IT, SL (Slovenian)
- **Coverage:** 5 explicit domains — healthcare, finance, legal, banking, general. Entity types include `blood_type`, `disease`, `symptom`, credit card, CVV, bank account, passport, health insurance number.
- **ETL effort:** **S**
- **Why Tier 2:** Multilingual + domain-tagged + explicit health labels (the only open corpus with labeled `blood_type` + `disease` + `symptom`). Addresses our US-EN-heavy bias and supplies health labels missing from Gretel finance.
- **Limit:** 2,970 rows is too small to be a LOCO-viable corpus on its own; use as multilingual supplement and health-specific enrichment.

## Tier 3 — Credential-pure corpora (paired pulls only)

**Recommendation: do not pull any more credential-pure corpora this sprint.** We have 3 already (gitleaks, secretbench, detect_secrets), and Hypothesis A from Q3 LOCO investigation is that the structural bias comes from having too many label-pure corpora relative to mixed ones. The minimum intervention is to pull Tier 1 first and re-measure LOCO. Only if, after pulling Tiers 1-2, credential recall drops do we consider credential-only augmentation.

If pulled later:

- **bigcode/bigcode-pii-dataset-training** — gated, requires form submission, license unspecified (do not pull blindly)
- **bigcode/bigcode-pii-dataset** — gated, license unspecified (same blocker)

## Tier 4 — Domain-specific PII

### Healthcare

#### 5. Synthea (MITRE)

- **URL:** https://github.com/synthetichealth/synthea
- **License:** **Apache 2.0 verified** at https://github.com/synthetichealth/synthea/blob/master/LICENSE
- **Size:** Generates 1k / 100k / 2.8M patient datasets on demand; OMOP + FHIR + CSV output
- **Format:** CSV tables (`patients.csv`, `conditions.csv`, `medications.csv`, `observations.csv`, `encounters.csv`) — **genuinely structured columnar**
- **Annotation:** **Schema-labeled, not span-labeled** — each column's semantic type is known by CSV name (e.g. `patients.SSN`, `patients.DRIVERS`, `patients.PASSPORT`, `patients.BIRTHDATE`, `conditions.CODE`, `observations.VALUE`). This is actually ideal for our per-column classification task — no NER→column ETL needed.
- **ETL effort:** **S** (schema-to-entity mapping is a one-time dict)
- **Why essential:** This is the healthcare corpus that structurally matches our library's API. Columns already exist; we only need to map column name → entity type. Produces `MEDICATION`, `CONDITION_CODE`, `MRN`, `PATIENT_ID`, `INSURANCE_NUMBER`, `PROVIDER_ID` label classes we completely lack.
- **Bias impact:** Very high. Adds health labels AND is structurally different from every current corpus (it's generated table rows, not NER spans).

**Not recommended: n2c2 / i2b2, MIMIC-III/IV, eICU.** All require DBMI/PhysioNet credentialed access + signed Data Use Agreement. Marked as **gated** in the process notes. Research-grade; human review required before use.

### Financial

Covered by Gretel finance (Tier 1) and privy (Tier 1). No additional open finance-specific corpora worth separate listing.

### Legal

No open labeled legal-PII corpus found in this scan. E3-JSI covers some legal-domain labels as a secondary slice. A dedicated legal corpus appears to be a genuine open-data gap.

### Government / public records

No open labeled corpus found. Synthea supplies some government-ID columns (`SSN`, `DRIVERS`, `PASSPORT`) as a partial substitute. Also a genuine gap.

## Tier 5 — Synthetic generators

### 6. Microsoft Presidio-Research

- **URL:** https://github.com/microsoft/presidio-research
- **License:** **MIT** (confirmed in repo metadata; direct LICENSE fetch returned 404 — low-confidence verification, human should re-confirm before ingesting)
- **Purpose:** Template-based synthetic data generator with 50+ recognizers, produces labeled BIO/IO/BILUO spans
- **Multi-category:** Yes — templates can be parameterized to emit mixed entity types per sentence
- **Integration effort:** **M** — we'd author templates for our missing entity classes
- **Why include:** Fills gaps rather than being primary corpus. Use to top up underrepresented categories (e.g. legal IDs, government IDs) after Tier 1 ingestion.

### 7. Synthea (counted above in Tier 4 healthcare but is also a generator)

## Tier 6 — Anti-recommendations (do NOT pull)

| Source | Reason |
|---|---|
| **ai4privacy/pii-masking-400k** | **Custom non-OSI license** — research + non-commercial only, no redistribution, no derivatives without written permission. README implies open; actual `license.md` is restrictive. **Also reverify the 300k variant already in use** — same custodian, likely same license. |
| **bigcode/bigcode-pii-dataset** | Gated, requires Terms of Use form, license **not explicitly stated**. Cannot verify OSI compatibility. |
| **bigcode/bigcode-pii-dataset-training** | Same as above — gated, no stated license. |
| **n2c2 / i2b2 2006-2018** | Credentialed access via Harvard DBMI DUA. Not redistributable. Research-only. Mark as gated. |
| **MIMIC-III / MIMIC-IV** | Credentialed PhysioNet access + DUA + CITI training. Not redistributable. Mark as gated. |
| **MultiNERD** | **CC BY-SA-NC 4.0** — NC clause makes it incompatible with MIT-licensed downstream use. |
| **unimelb-nlp/wikiann** | Silver-standard (auto-labeled), not human-verified; only PER/LOC/ORG — no PII-sensitive labels. |
| **CoNLL-03 / OntoNotes v5** | Source text behind NIST / LDC paywalls; not freely redistributable. |
| **Zenodo "Labeled Datasets for Information Operations"** | Restricted access, academic-only. |
| **Yet another gitleaks/secretbench derivative** | Would deepen credential-pure bias (the exact problem we're trying to break). |

## License + effort matrix

| Dataset | License | Rows | Format | Annotation | ETL | Active | Tier |
|---|---|---|---|---|---|---|---|
| gretel-pii-masking-en-v1 | Apache 2.0 | 60,000 | Parquet | Span, 43+ types | S | Yes | 1 |
| synthetic_pii_finance_multilingual | Apache 2.0 | 55,940 | Parquet | Span, 29+ types | S | Yes | 1 |
| beki/privy | MIT | 100-400k | Parquet (SQL/JSON/HTML/XML) | Span, 26 types | M | Stale (3y) | 1 |
| E3-JSI/synthetic-multi-pii-ner-v1 | MIT | 2,970 | Parquet | Token class | S | Yes | 2 |
| Synthea (MITRE) | Apache 2.0 | Generated | CSV/FHIR/OMOP | Schema-labeled | S | Yes | 4-Health |
| presidio-research | MIT* | Generator | Templates | BIO/IO/BILUO | M | Yes | 5 |

*presidio-research license verified only via repo metadata, not direct LICENSE file fetch (404). Re-verify before ingestion.

## Expected impact analysis

**Corpus count:** 6 → 10 after ingesting Gretel-EN, Gretel-finance, privy, Synthea (E3-JSI counted as a supplement, not a LOCO-viable corpus given 2,970 rows).

**New per-corpus label distribution, estimated:**

| Corpus | Credential | PII | Financial | Health | Negative |
|---|---|---|---|---|---|
| gitleaks (existing) | HIGH | 0 | 0 | 0 | HIGH |
| secretbench (existing) | HIGH | 0 | 0 | 0 | HIGH |
| detect_secrets (existing) | HIGH | 0 | 0 | 0 | HIGH |
| ai4privacy (existing, **license re-audit needed**) | LOW | HIGH | LOW | 0 | LOW |
| nemotron-pii (existing, CC-BY-4.0) | 0 | HIGH | LOW | MED | LOW |
| synthetic/Faker (existing) | 0 | HIGH | MED | 0 | MED |
| **gretel-en** (new) | MED | HIGH | HIGH | HIGH | LOW |
| **gretel-finance** (new) | MED | HIGH | HIGH | LOW* | LOW |
| **privy** (new) | MED | HIGH | HIGH | 0 | LOW |
| **synthea** (new) | 0 | HIGH | 0 | HIGH | HIGH |

*Gretel finance: health labels absent but health-context prose present in insurance claim documents.

**Critical change:** Before ingestion, credentials exist only in 3 label-pure corpora, so `corpus_id` is a near-perfect credential predictor. After ingestion, 3 of 4 new corpora carry credentials **mixed with** PII/financial/health labels, breaking the `corpus_id → credential` shortcut.

**LOCO viability:** All four new corpora individually exceed 50k rows (except Synthea, which can be generated at arbitrary size — recommend 100k-patient run). Each can serve as a held-out fold with enough representation to produce meaningful held-out metrics.

**Hypothesis A verdict:** The "need 15-20+ corpora regardless of quality" interpretation is **wrong**. The correct framing is "need ≥3 mixed-label corpora so that no single axis (credential, PII, health, financial) is confined to ≤50% of corpora." Four good mixed-label additions get us there. The structural bias is **fixable**, not inherent to small corpus count.

## Recommended ingestion order

1. **gretelai/gretel-pii-masking-en-v1** — first primary. Apache 2.0, 60k rows, 47 domains, span-labels easy to ETL. Highest bias-breaking value per hour of work. **Effort: S (1-2 days).**
2. **gretelai/synthetic_pii_finance_multilingual** — second primary. Same custodian and schema → almost zero ETL cost after #1. Adds multilingual + financial documents with labeled credentials. **Effort: S (0.5-1 day after #1).**
3. **Synthea 100k-patient generation run** — parallel. Truly structured-table format; no NER ETL at all, just schema mapping. Supplies health labels. **Effort: S (1 day including generation run).**
4. **beki/privy** — second-pass sprint. Structurally closest to our target domain (SQL/JSON traces), but pre-2024 and custom ETL for SQL traces. **Effort: M (3-5 days).** Verify dataset still loadable before committing sprint capacity.
5. **E3-JSI/synthetic-multi-pii-ner-v1** — supplement. Small, but fills multilingual + health label gaps missing from #1-4. **Effort: S (half day).**
6. **[Audit only, no pull]** Re-verify the ai4privacy license on the 300k version already in use. If it's the same AI4Privacy custom license as the 400k, we have a compliance problem independent of this research and it must be escalated.

**Dependencies:** Gretel-EN must land first because its schema defines the canonical span format we'll reuse for Gretel-finance and privy. Synthea is independent and can run in parallel.

**Sprint-effort estimate:** One sprint (~2 weeks) absorbs items 1-3 and a ~2-day LOCO re-measurement. Items 4-5 fit in the following sprint as a second pass.

## Open gaps the survey did not close

1. **Legal corpora** — no open labeled legal-PII corpus found. Genuine gap.
2. **Government / public records** — no open labeled corpus found beyond Synthea's partial coverage. Genuine gap.
3. **bigcode datasets** — gated and license-unspecified. Worth a one-off email request to the bigcode team if their dataset is high-quality enough to justify the friction; not worth blind ingestion.
4. **License re-verification** for `beki/privy`, `E3-JSI/synthetic-multi-pii-ner-v1`, and `presidio-research` was via dataset metadata only, not direct LICENSE file fetch. Pattern-survey discipline says fetch the actual file before ingestion. Pre-ingestion checklist.

## Methodology

**Search tools:** Web search (HuggingFace hub, GitHub topic pages, Zenodo) and direct fetches of license files and dataset cards.

**License verification:**
- Directly fetched: Synthea (`github.com/synthetichealth/synthea/blob/master/LICENSE` → Apache 2.0 confirmed), ai4privacy-400k (`license.md` → confirmed NOT OSI), Gretel-EN README, Gretel-finance README, Nemotron-PII dataset card.
- Verified via dataset metadata only (not direct LICENSE fetch): `beki/privy`, `E3-JSI/synthetic-multi-pii-ner-v1`, `presidio-research` (direct LICENSE fetch 404'd). These should be re-verified by fetching the repo LICENSE file before ingestion — pattern-survey discipline.

**What couldn't be accessed:** MIMIC, n2c2/i2b2 (all credentialed-access), bigcode-pii variants (gated Terms of Use). These are correctly listed as gated, not in recommendation tiers.

**Out of scope:** Pattern/regex sources — covered separately in `pattern_source_landscape.md`.

**Token usage:** ~62k total for the survey.
**Wall time:** ~33 minutes.

## Sources

- [gretelai/gretel-pii-masking-en-v1](https://huggingface.co/datasets/gretelai/gretel-pii-masking-en-v1)
- [gretelai/synthetic_pii_finance_multilingual](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual)
- [beki/privy](https://huggingface.co/datasets/beki/privy)
- [E3-JSI/synthetic-multi-pii-ner-v1](https://huggingface.co/datasets/E3-JSI/synthetic-multi-pii-ner-v1)
- [Synthea generator (MITRE)](https://github.com/synthetichealth/synthea)
- [Synthea LICENSE (Apache 2.0)](https://github.com/synthetichealth/synthea/blob/master/LICENSE)
- [ai4privacy/pii-masking-400k (anti-recommendation)](https://huggingface.co/datasets/ai4privacy/pii-masking-400k)
- [ai4privacy custom license file](https://huggingface.co/datasets/ai4privacy/pii-masking-400k/blob/main/license.md)
- [nvidia/Nemotron-PII (existing, CC-BY-4.0)](https://huggingface.co/datasets/nvidia/Nemotron-PII)
- [bigcode/bigcode-pii-dataset (gated, anti-rec)](https://huggingface.co/datasets/bigcode/bigcode-pii-dataset)
- [bigcode/bigcode-pii-dataset-training (gated, anti-rec)](https://huggingface.co/datasets/bigcode/bigcode-pii-dataset-training)
- [Microsoft presidio-research](https://github.com/microsoft/presidio-research)
- [n2c2 data portal (gated)](https://n2c2.dbmi.hms.harvard.edu/data-sets)
- [MIMIC-IV registry (gated)](https://registry.opendata.aws/mimic-iv-demo/)
- [MultiNERD (anti-rec, CC BY-SA-NC)](https://github.com/Babelscape/multinerd)
