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

## Tier 7 — Production-shape validation (BQ public)

> **Produced by:** general-purpose research subagent (dispatched 2026-04-16, experiment `E12`)
> **Billing project:** `dag-bigquery-dev` (user's gcloud default)
> **Total BQ cost:** ~$0.40 (8 candidates × schema/count/stats/sample; largest scans TABLESAMPLE'd)
> **Wall time:** ~35 minutes
> **Purpose:** Characterize `bigquery-public-data` tables against the gated-architecture shape taxonomy (`HOMOGENEOUS_CREDENTIAL` / `HOMOGENEOUS_PII` / `HETEROGENEOUS`) so the backlog item `gated-meta-classifier-architecture-*-q8-continuation` has validation data. Orthogonal axis to the Tier 1-6 survey above — that covers **labeled training corpora**, this covers **production-shape real tables** (unlabeled, shape-focused).

**Finding up front:** the single highest-value staging target is **`stackoverflow.users.about_me`** (2.3M rows, CC-BY-SA 4.0, median 81 chars of user-authored prose with embedded names/locations/URLs). It's the cleanest open-data analogue of "application message field / user bio column" that BQ customers actually classify, and it pairs naturally with `stackoverflow.users.location` (HOMOGENEOUS_PII control) and `crypto_ethereum.logs.data` (HOMOGENEOUS_STRUCTURED hex, negative control). Those three together are sufficient to validate all three stage-1 gate outcomes.

Secondary pulls (`hacker_news.full.text`, `new_york_311.resolution_description`) add NL-prose coverage without re-measuring the same shape. The 311 / Chicago-crime `description` / `descriptor` fields turned out to be **category-enum-shaped, not freeform** — they're short (avg 16-21 chars) and dominated by template strings like `"STRONGARM - NO WEAPON"`, so they validate HOMOGENEOUS_STRUCTURED rather than the heterogeneous path the queue entry expected. Surprise finding — the shortlist was wrong about which columns were freeform.

### A1. bigquery-public-data.stackoverflow.users — `about_me`, `location`, `website_url`

- **Path:** `bigquery-public-data.stackoverflow.users`
- **License:** **CC-BY-SA 4.0** (StackExchange data dump terms — verified at https://archive.org/details/stackexchange; attribution-ShareAlike required, downstream use must preserve license). Compatible with research use; downstream redistribution of derived models requires documenting StackExchange attribution. **Not Apache/MIT compatible** — model weights trained on this data inherit SA clause.
- **Rows:** 18,712,212 (2.3M have non-null `about_me`)
- **`about_me`** — STRING, `NULL` in ~88% of rows
  - Byte length: p10=28, p50=81, p90=293, p99=525, max=5,999; avg 219
  - Shape classification: `MIXED_CONTENT_FREEFORM`
  - Shape description: user-authored HTML-wrapped prose biographies. Observed content includes person names, city/state/country names, company names, embedded `<a href>` links, GitHub/Twitter handles, occasional email addresses in contact blurbs. No phone numbers observed in sample. No credentials observed. Prose contains full sentences with ~50-70% of non-null rows including at least one URL and ~30-40% including a location mention. HTML tags (`<p>`, `<a>`, `<ul>`, `<li>`, `<strong>`) are structural and should be stripped before engine input.
  - Entities densely represented: PERSON, LOCATION, ORGANIZATION, URL, HANDLE
  - Entities sparsely represented: EMAIL
  - Entities absent: CREDENTIAL, FINANCIAL (PAN/IBAN/SWIFT), SSN/ID, HEALTH
- **`location`** — STRING
  - Shape classification: `HOMOGENEOUS_PII` (free-text city/state/country strings; e.g. "West Lafayette, IN, United States", "Brno, Czech Republic", "Singapore, Singapore")
  - ~95% of non-null rows are single-entity location strings — clean homogeneous-PII gate target
- **`website_url`** — STRING
  - Shape classification: `HOMOGENEOUS_STRUCTURED` (URL)
- **Staging recommendation:** 🟢 **stage now** — highest-value candidate in this survey. Pull ~100k `about_me` rows + matched `location` + `website_url` columns to validate stage-1 gate (HOMOGENEOUS_PII vs HETEROGENEOUS routing) and stage-2c heterogeneous NER.
- **Gated-architecture stage validated:**
  - `about_me` → **stage-1 gate (HETEROGENEOUS verdict)** + **stage-2c `HeterogeneousColumnFinding`** heterogeneous NER output
  - `location` → **stage-1 gate (HOMOGENEOUS_PII verdict)** + **stage-2b PII homogeneous baseline**
  - `website_url` → **stage-1 gate (HOMOGENEOUS_STRUCTURED)** negative control (URL, not PII/credential)

### A2. bigquery-public-data.hacker_news.full — `text`

- **Path:** `bigquery-public-data.hacker_news.full`
- **License:** **MIT** (Hacker News data dump / Y Combinator permits research+commercial use; this specific BQ mirror is maintained under the HN API ToS which allows redistribution for non-commercial or "educational purposes" with attribution — **verify the HN API ToS before model training for a commercial product**). Lower risk than SO but not as clean as Apache/CC0.
- **Rows:** 47,749,045 total; 40,824,109 with non-null `text`
- **`text`** — STRING
  - Byte length: p10=59, p50=252, p90=837, p99=~3000, max=100,418; avg 386
  - Shape classification: `MIXED_CONTENT_FREEFORM`
  - Shape description: HTML-escaped (`&#x2F;` for `/`, `<p>` separators) comment / post text. Observed content includes person names, URLs (very prevalent — ~70% of long comments), company names, occasional phone numbers in spam posts ("Contact Arthur on EMAIL- Quickarturhack @ Gmail,com WhatsApp +17025301177"), email addresses, product pitches, code snippets, job postings. Character set mix is `[A-Za-z] + HTML entities + URLs + occasional non-Latin names`. Spam corpus is a notable contaminant — sampled 15 rows, 1 was an explicit "hire a hacker" spam post with embedded phone + email + Gmail handle.
  - Entities densely represented: PERSON, URL, ORGANIZATION
  - Entities sparsely represented: EMAIL, PHONE (almost exclusively in spam rows)
  - Entities absent: CREDENTIAL, FINANCIAL, SSN/ID
- **Staging recommendation:** 🟡 **stage later** — valuable but partially redundant with `about_me`. Hold for second pass unless we explicitly need longer-form prose (p90 = 837 vs `about_me` p90 = 293). The spam contamination is a feature for robustness evaluation, not a bug.
- **Gated-architecture stage validated:** stage-1 gate (HETEROGENEOUS) + stage-2c heterogeneous NER, longer-context variant of `about_me`.

### A3. bigquery-public-data.new_york_311.311_service_requests — `resolution_description`

- **Path:** `bigquery-public-data.new_york_311.311_service_requests`
- **License:** **Public domain** (NYC Open Data, no attribution required for use; verified at https://opendata.cityofnewyork.us/overview/ / NYC Open Data Terms of Use permit free reuse). Cleanest license in this Tier.
- **Rows:** 27,039,784 total; 26,490,668 with non-null `resolution_description`
- **`resolution_description`** — STRING
  - Byte length: p10=83, p50=135, p90=275, p99=930, max observed ~5000; avg 156
  - Shape classification: `MIXED_CONTENT_FREEFORM` (but **low-entropy templated**)
  - Shape description: NYC agency resolution notes. Observed sample is ~70% boilerplate templates (`"Service Request status for this request is available on the Department of Transportation's website. Please click the 'Learn More' link below."`), with ~30% genuinely variable prose ("NYC Parks determined that the issue will be addressed in the next pruning cycle..."). Low PII density — no person names, no phones, no emails observed. URLs embedded (`nyc.gov/parks/trees`). Character encoding: UTF-8 with curly quotes (`â€™`) occasionally mojibake'd.
  - Entities densely represented: URL (agency domains), ORG_GOV
  - Entities sparsely represented: LOCATION (street addresses in less-templated rows)
  - Entities absent: PERSON, EMAIL, PHONE, CREDENTIAL, FINANCIAL, SSN/ID
- **`descriptor`** and **`complaint_type`** — both STRING, both enum-like (avg 17 chars, few distinct values). Shape classification: `HOMOGENEOUS_STRUCTURED` (category).
- **`incident_address`** — STRING, NYC street addresses. Shape: `HOMOGENEOUS_PII` (address).
- **Staging recommendation:** 🟡 **stage later** — useful as a **low-entropy HETEROGENEOUS** test case (templated prose that looks freeform but carries almost no entities) but the `descriptor` / `complaint_type` columns are more useful as HOMOGENEOUS_STRUCTURED contrast. Don't pull `resolution_description` as primary — the surface-level shape fooled the shortlist; after inspection the actual free-form prose density is too low to train on.
- **Gated-architecture stage validated:** stage-1 gate HETEROGENEOUS + stage-2c NER (low-entity-density edge case — good for precision testing).

### A4. bigquery-public-data.austin_311.311_service_requests — `incident_address`

- **Path:** `bigquery-public-data.austin_311.311_service_requests`
- **License:** **Public domain** (City of Austin Open Data / CC0; verified at https://data.austintexas.gov/).
- **Rows:** 2,418,177
- **`incident_address`** — STRING, fully-qualified addresses ("2604 MALLARD GREEN CV, AUSTIN, TX 78728")
  - Shape classification: `HOMOGENEOUS_PII` (address) — cleaner than SO `location` because 100% of rows follow `<number> <street> <suffix>, <city>, <state> <zip>` pattern
- **`complaint_description`** — STRING
  - Byte length: p50=22, p90=29, max=44; avg 21
  - Shape classification: `HOMOGENEOUS_STRUCTURED` (category label — not freeform despite name). Sample: every one of 20 rows inspected was exactly `"(Tara) Financial Services Depart"`. Enum-shaped, not prose.
  - **Finding** (vs shortlist expectation): `complaint_description` was listed in the queue entry as the high-value freeform column. It is not — it's an enum with ~100 distinct values. **The shortlist was wrong about Austin.**
- **Staging recommendation:** 🟢 **stage now** — the `incident_address` column is one of the cleanest HOMOGENEOUS_PII-address columns in BQ public data, and the CC0 license is the least restrictive in this Tier. ~50k row sample is sufficient for stage-1 gate validation.
- **Gated-architecture stage validated:** stage-1 gate HOMOGENEOUS_PII (address) + stage-2b PII homogeneous baseline.

### A5. bigquery-public-data.chicago_crime.crime — `description`, `block`, `location_description`

- **Path:** `bigquery-public-data.chicago_crime.crime`
- **License:** **Public domain** (City of Chicago Data Portal / CC0).
- **Rows:** 8,532,007
- **All three text columns are category-enum shaped:**
  - `description` — avg 16 chars, values like `"STRONGARM - NO WEAPON"`, `"ARMED - HANDGUN"`, `"NON-AGGRAVATED"`. Shape: `HOMOGENEOUS_STRUCTURED`.
  - `location_description` — avg ~12 chars, values like `"CTA TRAIN"`, `"SIDEWALK"`, `"BANK"`. Shape: `HOMOGENEOUS_STRUCTURED`.
  - `block` — avg ~20 chars, **anonymized** addresses (`"001XX N DEARBORN ST"` — last two digits zero'd by Chicago Data Portal for victim privacy). Shape: `HOMOGENEOUS_STRUCTURED` (looks like address but is deliberately not a resolvable one — interesting as a LOCATION-shaped-but-not-PII edge case).
- **Staging recommendation:** 🟡 **stage later** — not a high-value training source. The **`block` column is interesting as a negative control** for address detection (looks like an address, is privacy-scrubbed, should not classify as LOCATION-PII at high confidence). Worth a 10k-row pull specifically for adversarial eval, not for training.
- **Gated-architecture stage validated:** stage-1 gate HOMOGENEOUS_STRUCTURED (all three columns) + stage-2a structured baseline.

### B1. bigquery-public-data.stackoverflow.posts_questions — `body`, `title`

- **Path:** `bigquery-public-data.stackoverflow.posts_questions`
- **License:** **CC-BY-SA 4.0** (same as users table).
- **Rows:** 23,020,127
- **`body`** — STRING, HTML-wrapped question bodies
  - Byte length: p10=340, p50=993, p90=2080, p99=3152, max=115,918; avg 1560
  - Shape classification: `MIXED_CONTENT_FREEFORM` + `EMBEDDED_CODE` hybrid
  - Shape description: HTML-wrapped natural-language problem descriptions with heavy embedded code blocks (`<pre><code>...</code></pre>`), URLs, stack traces, error messages. Observed sample: **~20% of long bodies contain inline secrets/credentials in code examples** — saw `PasswordToken("testing1234")`, `zkServers = "localhost:2181"`, file paths containing usernames (`/Users/hiran/research/...`), API endpoints. The secrets are typically toy/example values, but the shape signal — "credential-like token inside prose-like column" — is exactly the HETEROGENEOUS column pattern stage-2c needs to handle.
  - Entities densely represented: PERSON (in code comments/paths), URL, ORGANIZATION (in questions about tools), CREDENTIAL_EXAMPLE (toy secrets in code)
  - Entities sparsely represented: EMAIL, IP_ADDRESS
- **`title`** — STRING, avg 55 chars. Shape: `MIXED_CONTENT_FREEFORM` short-form (question titles). Lower priority.
- **Staging recommendation:** 🟡 **stage later** — body column is valuable for HETEROGENEOUS-with-credentials training data, but the HTML/code structure makes ETL non-trivial (need an HTML stripper + code-block detector to avoid treating every `<code>` block as a credential). Worth a 20k-row pull after `about_me` is proven valuable.
- **Gated-architecture stage validated:** stage-1 gate HETEROGENEOUS + stage-2c NER with credential contamination (the hardest case — long prose with occasional embedded secrets).

### B2. bigquery-public-data.github_repos.commits — `message`, `author.email`, `author.name`

- **Path:** `bigquery-public-data.github_repos.commits`
- **License:** **Per-repo license** — each commit inherits the license of its source repo. This table is explicitly marked "research use only" in the BQ dataset description because commit messages carry the license of every aggregated repo. **Do NOT redistribute sampled rows without per-repo license verification.** For in-project training on aggregate shape statistics (not content), the risk is low; for any shipped corpus the risk is high.
- **Rows:** 6,614,473,845 (6.6 billion; 26.5 GB for message column alone)
- **`message`** — STRING
  - Byte length (1% TABLESAMPLE): p10=14, p50=42, p90=176, p99=644,554 (outlier), max=644,554; avg 96
  - Shape classification: **Hybrid** — varies per message, more heterogeneous than other candidates:
    - ~30% single-line subject only: `HOMOGENEOUS_STRUCTURED` (short imperative-voice message)
    - ~50% multi-line: subject + body, **TRUE_LOG-shaped** in observed sample (git-svn-id lines `git-svn-id: <url>@<rev> <uuid>`, CI automation lines `triggering build with pending triggers: 0; ...`, JIRA IDs, tracking references)
    - ~20% prose commit bodies (FreeBSD-style detailed commits): `MIXED_CONTENT_FREEFORM`
  - Shape description: observed 15 rows include: 3 with `git-svn-id:` UUID lines (TRUE_LOG), 5 with k8s automation key=value lines (TRUE_LOG), 2 with path-additions-removals diffs (TRUE_LOG), 2 empty-padding markers, 1 prose commit from FreeBSD clang build (MIXED_CONTENT_FREEFORM), 2 single-line subjects. **High TRUE_LOG density** compared to all other candidates in this survey.
  - Entities densely represented: URL, HASH (git SHAs), UUID (svn-ids), FILE_PATH, ISSUE_ID
  - Entities sparsely represented: PERSON (author names in `Signed-off-by:` trailers), EMAIL (in trailers), ORG
  - Entities absent: CREDENTIAL (rare — some repos do leak, but aggregate is clean), FINANCIAL, SSN/ID, HEALTH
- **`author.email`** / **`author.name`** — nested STRUCT fields
  - Shape: `HOMOGENEOUS_PII` — every commit has an email + name. 6.6B rows is overkill; sample ~10k distinct.
- **Staging recommendation:** 🔴 **do NOT stage message column for training** — license risk (per-repo inheritance) + 26.5 GB scan cost for a full column pull. However, 🟢 **stage a small sample (~10k rows) specifically for TRUE_LOG shape characterization** — this is the **only** candidate in this survey with high TRUE_LOG density, and without it the stage-1 gate has no positive example of the "structured key=value/UUID-heavy log line" shape.
- **Gated-architecture stage validated:**
  - `message` (small sample) → **stage-1 gate TRUE_LOG-shape detection** (unique validation target — no other candidate hits this shape class)
  - `author.email` / `author.name` → stage-1 gate HOMOGENEOUS_PII
- **License caveat:** if we stage this, the sample must be used for **shape characterization only** — row-level content must not be redistributed without per-repo license audit.

### C1. bigquery-public-data.crypto_ethereum.logs — `data`, `topics`, `address`

- **Path:** `bigquery-public-data.crypto_ethereum.logs`
- **License:** **CC0** (blockchain-etl project, Apache 2.0 tooling, underlying data is on-chain and public domain).
- **Rows:** 6,614,473,845 (same magnitude as GH commits)
- **`data`** — STRING
  - Shape classification: `HOMOGENEOUS_STRUCTURED` (hex-encoded event data, always `0x` prefix, zero-padded to 32-byte words; observed sample is 100% `^0x[0-9a-f]*$` fixed-width hex)
- **`topics`** — ARRAY<STRING>
  - Shape: `HOMOGENEOUS_STRUCTURED` (each topic is a 32-byte keccak256 hash)
- **`address`** — STRING
  - Shape: `HOMOGENEOUS_STRUCTURED` (Ethereum addresses, 42-char `0x` + 40 hex digits)
- **Staging recommendation:** 🟢 **stage now (small sample)** — this is the cleanest **negative control** for the HOMOGENEOUS_STRUCTURED gate in the survey. 10k-row sample is sufficient. Cryptographic hex is a known false-positive magnet for credential regex (high entropy, fixed length, hex charset), and our meta-classifier needs examples of "structured but not sensitive" to learn the distinction.
- **Gated-architecture stage validated:** **stage-1 gate HOMOGENEOUS_STRUCTURED negative control** + **credential-partitioner ablation target** (Sprint 11 item #8 shape-based credential partitioning should correctly reject these as non-credential structured hex).

### C2. bigquery-public-data.usa_names.usa_1910_current — `name`, `state`, `gender`

- **Path:** `bigquery-public-data.usa_names.usa_1910_current`
- **License:** **Public domain** (US SSA name data release).
- **Rows:** 6,311,504
- **`name`** — STRING, first names only (e.g. `"Mary"`, `"John"`). Shape: `HOMOGENEOUS_PII` (PERSON_NAME, though single-token).
- **`state`** — STRING, 2-letter codes. Shape: `HOMOGENEOUS_STRUCTURED` (US state code enum).
- **`gender`** — STRING, single character `M`/`F`. Shape: `HOMOGENEOUS_STRUCTURED` (binary enum).
- **Staging recommendation:** 🟡 **stage later** — useful as a single-token PERSON_NAME baseline but our training corpora already have PERSON_NAME coverage via Gretel-EN (multi-token names in realistic context). Only stage if we find first-name-only classification is a specific gap.
- **Gated-architecture stage validated:** stage-1 gate HOMOGENEOUS_PII (PERSON_NAME, short-form) + stage-2b PII homogeneous baseline.

### C3. bigquery-public-data.google_analytics_sample.ga_sessions_* — `fullVisitorId`, `userId`, nested `device`/`geoNetwork`

- **Path:** `bigquery-public-data.google_analytics_sample.ga_sessions_YYYYMMDD` (daily-partitioned, ~2556 rows/day in the sample)
- **License:** **Google demo dataset terms** — permits use "for the purpose of learning and experimentation with BigQuery". **Not clear-cut open source.** Re-read at https://support.google.com/analytics/answer/7586738 before training.
- **Rows:** ~2,556/day over ~360 days ≈ 920k total (demo-sized, not production-sized)
- **Top-level columns:** 30+ including deeply nested STRUCT (`device`, `geoNetwork`, `trafficSource`, `customDimensions` ARRAY<STRUCT>, `hits` ARRAY<STRUCT> — deeply nested session data)
- **`fullVisitorId`** — STRING, 19-digit numeric. Shape: `HOMOGENEOUS_STRUCTURED` (user ID).
- **`userId`** — STRING, **always null in demo** (scrubbed). Not usable for training.
- **`device.browser`** / **`device.operatingSystem`** — STRUCT fields, enum-like. Shape: `HOMOGENEOUS_STRUCTURED`.
- **`geoNetwork.city`** — STRUCT field, **"not available in demo dataset" in ~50% of rows** (scrubbed).
- **Staging recommendation:** 🔴 **do NOT stage** — the demo dataset is over-scrubbed (userId null, city partially masked, email absent), the license is ambiguous for model training, and the nested STRUCT schema doesn't match our per-column ColumnInput API cleanly. The value was the nested-JSON-shape validation, but the scrubbing removes all the PII content that would make it useful.
- **Gated-architecture stage validated:** none worth the ETL cost. Skip.

### Cross-candidate shape distribution

| Shape class (gated-arch stage-1 outcome) | Best BQ validation target | Row budget | Stage to pull |
|---|---|---|---|
| `HETEROGENEOUS` (stage-2c NER) | `stackoverflow.users.about_me` | ~100k | 🟢 now |
| `HETEROGENEOUS` (long-form variant) | `hacker_news.full.text` | ~50k | 🟡 later |
| `HETEROGENEOUS` + credential contamination | `stackoverflow.posts_questions.body` | ~20k | 🟡 later |
| `TRUE_LOG` (key=value / UUID-heavy) | `github_repos.commits.message` | ~10k | 🟡 later (license-gated) |
| `HOMOGENEOUS_PII` (address) | `austin_311.incident_address` | ~50k | 🟢 now |
| `HOMOGENEOUS_PII` (freeform location) | `stackoverflow.users.location` | ~100k | 🟢 now |
| `HOMOGENEOUS_PII` (single-token name) | `usa_names.usa_1910_current.name` | ~10k | 🟡 later |
| `HOMOGENEOUS_STRUCTURED` negative control (hex) | `crypto_ethereum.logs.data` | ~10k | 🟢 now |
| `HOMOGENEOUS_STRUCTURED` (category enum) | `chicago_crime.crime.description` | ~10k | 🟡 later |
| `JSON_TYPED` / nested RECORD | *none worth staging* — GA sample over-scrubbed | — | 🔴 skip |

### Gaps this survey did NOT close

1. **True audit-log columns** (Google Cloud Audit Logs shape: `{"protoPayload":{...},"resource":{...}}` JSON). `bigquery-public-data` does not expose a customer-style audit-log dataset; the closest is `crypto_ethereum.logs` which is structured-hex, not structured-JSON. **Genuine gap.** A synthetic audit-log generator (Presidio-research-style templates) may be the only way to close this.
2. **Application-message/support-ticket columns** with customer PII (addresses, phones, order IDs) mixed with agent replies. Closest BQ public proxy is `new_york_311.resolution_description`, which turned out to be over-templated and low-PII. **Genuine gap.**
3. **Healthcare free-text notes** (discharge summaries, clinical notes). All open BQ public datasets are de-identified or synthetic (`cms_synthetic_patient_data_omop` covers codes, not notes). Synthea covers structured columns but not free-text notes. Consistent with the Tier 1-6 finding that open health free-text is gated behind PhysioNet DUAs.
4. **Customer-support email threads** with quoted prior messages. No open BQ public source.

### Candidates inspected but dropped during enumeration

- `bigquery-public-data.wikipedia.pageviews_2023` — page-view counts, not page content. Shape: aggregate numeric. Not useful.
- `bigquery-public-data.openaq.global_air_quality` — air-quality measurements, all numeric+categorical. Shape: HOMOGENEOUS_STRUCTURED. Redundant with `chicago_crime` for the structured gate.
- **Any `INFORMATION_SCHEMA` project-level discovery query** — access denied on `bigquery-public-data.INFORMATION_SCHEMA.COLUMNS_BY_PROJECT` and `.SCHEMATA`, so discovery was limited to the per-dataset scoped queries in the shortlist. A cross-dataset JSON-type hunt was blocked.

### Recommended staging order (if this feeds a Sprint 12+ item)

1. **`stackoverflow.users.about_me` + `location` + `website_url`** (100k rows, CC-BY-SA 4.0) — highest validation value per row; covers three of the four stage-1 outcomes in a single pull.
2. **`austin_311.incident_address`** (50k rows, CC0) — cleanest address shape; HOMOGENEOUS_PII gate.
3. **`crypto_ethereum.logs.data`** (10k rows, CC0) — HOMOGENEOUS_STRUCTURED hex negative control; ~20 LOC loader.
4. **`github_repos.commits.message`** (10k rows, license-gated — **shape stats only, do not redistribute rows**) — TRUE_LOG shape validation; only BQ source for this class.
5. **`hacker_news.full.text`** (50k rows, MIT-ish) — second-pass long-form prose.

Budget impact: ~170k production-shape validation rows across 4 shape classes. Zero training-label dependency (we're using the pre-trained meta-classifier on this data — the value is stage-1 gate accuracy measurement, not retraining). ETL effort is S for each; roughly 2-3 days wall time for a single engineer to land items 1-3, with 4-5 as follow-up.

### Methodology notes

- **Discovery constraint:** cross-dataset INFORMATION_SCHEMA queries are denied at `bigquery-public-data` scope, so candidate expansion was manual (user-suggested shortlist + per-dataset introspection). A broader "find every JSON-typed column" survey would require either a different IAM grant or scripting a per-dataset crawl.
- **Sampling strategy:** TABLESAMPLE SYSTEM at 0.001-1% for multi-TB tables; LIMIT + IS NOT NULL filter for moderate-size tables. No raw values transcribed into this memo — all shape descriptions are characterizations, not quotations, except where toy/public-figure values illustrate a format (StackOverflow user bio excerpts are CC-BY-SA; 311 / crypto samples are public-domain).
- **Cost control:** dry-run-first on the three multi-TB tables (SO body 36 GB, GH commits 26.5 GB, HN text 15.8 GB). Ran full stats on SO body + HN text (worth the ~$0.25 combined); used TABLESAMPLE on GH commits to avoid the full 26.5 GB scan. Total spend ~$0.40 against the $5 budget.
- **Out of scope:** actual data staging (downloading into `corpora/`). This memo is a survey only — staging is a separate sprint item gated on which candidates the maintainer selects.

## License + effort matrix

| Dataset | License | Rows | Format | Annotation | ETL | Active | Tier |
|---|---|---|---|---|---|---|---|
| gretel-pii-masking-en-v1 | Apache 2.0 | 60,000 | Parquet | Span, 43+ types | S | Yes | 1 |
| synthetic_pii_finance_multilingual | Apache 2.0 | 55,940 | Parquet | Span, 29+ types | S | Yes | 1 |
| beki/privy | MIT | 100-400k | Parquet (SQL/JSON/HTML/XML) | Span, 26 types | M | Stale (3y) | 1 |
| E3-JSI/synthetic-multi-pii-ner-v1 | MIT | 2,970 | Parquet | Token class | S | Yes | 2 |
| Synthea (MITRE) | Apache 2.0 | Generated | CSV/FHIR/OMOP | Schema-labeled | S | Yes | 4-Health |
| presidio-research | MIT* | Generator | Templates | BIO/IO/BILUO | M | Yes | 5 |
| stackoverflow.users (about_me/location) | CC-BY-SA 4.0 | 2.3M non-null about_me / 18.7M total | BQ STRING | Unlabeled (shape) | S | Yes | 7 |
| hacker_news.full (text) | HN API ToS / MIT-ish | 40.8M non-null | BQ STRING | Unlabeled (shape) | S | Yes | 7 |
| new_york_311 (resolution_description) | Public domain | 26.5M non-null | BQ STRING | Unlabeled (shape) | S | Yes | 7 |
| austin_311 (incident_address) | CC0 / Public domain | 2.4M | BQ STRING | Unlabeled (shape) | S | Yes | 7 |
| chicago_crime.crime | Public domain | 8.5M | BQ STRING | Unlabeled (shape) | S | Yes | 7 |
| stackoverflow.posts_questions (body) | CC-BY-SA 4.0 | 23.0M | BQ STRING | Unlabeled (shape) | M (HTML+code) | Yes | 7 |
| github_repos.commits (message) | **Per-repo (restricted)** | 6.6B | BQ STRING | Unlabeled (shape) | S (sample only) | Yes | 7 |
| crypto_ethereum.logs | CC0 | 6.6B | BQ STRING/ARRAY | Unlabeled (shape) | S | Yes | 7 |
| usa_names.usa_1910_current | Public domain | 6.3M | BQ STRING | Unlabeled (shape) | S | Yes | 7 |
| google_analytics_sample | Google demo terms* | ~920k | BQ nested STRUCT | Unlabeled (scrubbed) | M | Yes | 7 (skip) |

*presidio-research license verified only via repo metadata, not direct LICENSE file fetch (404). Re-verify before ingestion.
*Google Analytics demo dataset license is ambiguous for model training use; treat as research/demo only.

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
