# External Corpora Research — PII & Secret Detection

> **Date:** 2026-04-11
> **Sprint:** 4 (Stream B — Benchmarks)
> **Purpose:** Document available external corpora for benchmarking data_classifier accuracy against real-world data.

## 1. Ai4Privacy pii-masking-300k

| Field | Value |
|---|---|
| **Source** | [HuggingFace: ai4privacy/pii-masking-300k](https://huggingface.co/datasets/ai4privacy/pii-masking-300k) |
| **License** | Apache 2.0 |
| **Size** | ~225K rows |
| **Format** | Parquet / JSON Lines via HuggingFace `datasets` library |
| **Entity Types** | 27+ PII types: FIRSTNAME, LASTNAME, EMAIL, PHONE, SSN, CREDITCARDNUMBER, IBAN, IP_ADDRESS, DATE, STREET_ADDRESS, CITY, STATE, ZIPCODE, COUNTRY, USERNAME, PASSWORD, URL, COMPANYNAME, JOBTITLE, VEHICLEIDENTIFICATIONNUMBER, BITCOIN_ADDRESS, and more |
| **Content** | Synthetic text passages with inline PII annotations (masked spans) |
| **Language** | Primarily English, some multilingual |

### ETL to Our Format

The dataset contains text passages with PII annotations as masked spans. To convert:

1. Download via `datasets` library: `load_dataset("ai4privacy/pii-masking-300k", split="train")`
2. Each row has `source_text`, `masked_text`, and `privacy_mask` (list of span annotations)
3. Extract individual PII values from `privacy_mask` spans
4. Group by entity type, create `ColumnInput` objects with extracted values as `sample_values`
5. Map entity types: `CREDITCARDNUMBER` -> `CREDIT_CARD`, `FIRSTNAME`/`LASTNAME` -> `PERSON_NAME`, `PHONE_NUMBER` -> `PHONE`, `STREET_ADDRESS` -> `ADDRESS`, `SOCIALINSURANCE` -> `CANADIAN_SIN`, `VEHICLEIDENTIFICATIONNUMBER` -> `VIN`

### Entity Type Mapping

| Ai4Privacy Type | Our Entity Type |
|---|---|
| EMAIL | EMAIL |
| PHONE_NUMBER / PHONENUMBER | PHONE |
| CREDITCARDNUMBER | CREDIT_CARD |
| SSN | SSN |
| IBAN | IBAN |
| IP_ADDRESS / IPADDRESS | IP_ADDRESS |
| URL | URL |
| FIRSTNAME, LASTNAME | PERSON_NAME |
| STREET_ADDRESS | ADDRESS |
| DATE | DATE_OF_BIRTH |
| BITCOIN_ADDRESS | BITCOIN_ADDRESS |
| VEHICLEIDENTIFICATIONNUMBER | VIN |
| MAC_ADDRESS | MAC_ADDRESS |

## 2. Nemotron-PII (NVIDIA)

| Field | Value |
|---|---|
| **Source** | [HuggingFace: nvidia/Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII) |
| **License** | CC BY 4.0 |
| **Size** | ~100K records |
| **Format** | Parquet / JSON Lines via HuggingFace `datasets` library |
| **Entity Types** | 55+ types including: PERSON, EMAIL, PHONE, CREDIT_CARD, SSN, IBAN, IP_ADDRESS, URL, ADDRESS, DATE_OF_BIRTH, PASSPORT, DRIVER_LICENSE, BANK_ACCOUNT, SWIFT_CODE, and many more |
| **Content** | Synthetic text with inline PII entity annotations |
| **Language** | English |

### ETL to Our Format

1. Download via `datasets` library: `load_dataset("nvidia/Nemotron-PII", split="train")`
2. Each row has text with annotated PII spans (entity type + start/end positions)
3. Extract PII values from span annotations
4. Group by entity type, build `ColumnInput` objects
5. Map entity types to our schema

### Entity Type Mapping

| Nemotron Type | Our Entity Type |
|---|---|
| EMAIL_ADDRESS | EMAIL |
| PHONE_NUMBER | PHONE |
| CREDIT_CARD_NUMBER | CREDIT_CARD |
| SOCIAL_SECURITY_NUMBER | SSN |
| IBAN_CODE | IBAN |
| IP_ADDRESS | IP_ADDRESS |
| URL | URL |
| PERSON_NAME | PERSON_NAME |
| STREET_ADDRESS | ADDRESS |
| DATE_OF_BIRTH | DATE_OF_BIRTH |
| SWIFT_CODE | SWIFT_BIC |

## 3. SecretBench (GitHub)

| Field | Value |
|---|---|
| **Source** | [GitHub: setu4993/SecretBench](https://github.com/setu4993/SecretBench) |
| **License** | MIT |
| **Size** | ~97K labeled secrets |
| **Format** | CSV/JSON — file path, line number, secret type, secret value |
| **Entity Types** | API keys, tokens, passwords, private keys, connection strings, OAuth tokens, webhook URLs, etc. |
| **Content** | Real secrets found in public repositories (values are hashed/redacted in the public dataset, but type labels and context are available) |

### ETL to Our Format

1. Clone the repository or download CSV files
2. Parse CSV rows — each has `type`, `value` (or context), and label
3. Filter to types we detect: API keys (-> CREDENTIAL), passwords (-> CREDENTIAL), tokens (-> CREDENTIAL)
4. Create `SampleCase` objects for secret_benchmark.py
5. All secret types map to our `CREDENTIAL` entity type

### Relevant Secret Types

| SecretBench Type | Our Detection Layer |
|---|---|
| aws_access_key | regex (known-prefix) |
| github_token | regex (known-prefix) |
| generic_api_key | scanner_definitive |
| password | scanner_definitive |
| private_key | scanner_definitive |
| connection_string | known_limitation (needs URI parser) |

## 4. Gitleaks Test Fixtures

| Field | Value |
|---|---|
| **Source** | [GitHub: gitleaks/gitleaks](https://github.com/gitleaks/gitleaks) — `cmd/generate/config/rules/` and test fixtures |
| **License** | MIT |
| **Size** | ~200+ test cases across rule files |
| **Format** | TOML rule files with embedded test strings (allowlist/denylist) |
| **Entity Types** | 100+ secret types: AWS, GCP, Azure, GitHub, GitLab, Slack, Stripe, Twilio, SendGrid, and many more |
| **Content** | Regex rules with positive/negative test cases embedded in rule definitions |

### ETL to Our Format

1. Clone gitleaks repo, navigate to `cmd/generate/config/rules/`
2. Parse TOML rule files — each has `regex`, `keywords`, and embedded test examples
3. Extract test strings from rule definitions (positive matches and negative cases)
4. Map to our format: all map to CREDENTIAL entity type
5. Tag with detection layer based on whether our regex patterns cover the prefix

### Extraction Strategy

- Parse each `.toml` rule file for `secret` and `regex` fields
- Extract example secrets from test fixtures in `cmd/generate/config/gitleaks.toml`
- Use the known-good test strings as additional benchmark cases

## 5. detect-secrets Test Suite (Yelp)

| Field | Value |
|---|---|
| **Source** | [GitHub: Yelp/detect-secrets](https://github.com/Yelp/detect-secrets) — `testing/` and `tests/` directories |
| **License** | Apache 2.0 |
| **Size** | ~100+ test cases |
| **Format** | Python test files with embedded test strings |
| **Entity Types** | AWS keys, Slack tokens, Stripe keys, Twilio keys, basic auth, high entropy strings, private keys, JSON web tokens |
| **Content** | Unit test fixtures with known-positive and known-negative secret values |

### ETL to Our Format

1. Clone detect-secrets repo
2. Parse test files in `tests/plugins/` — each plugin has test cases with known secrets
3. Extract test strings from test assertions
4. Map to our format: all map to CREDENTIAL entity type
5. Some overlap with gitleaks — deduplicate

### Relevant Test Files

| File | Secret Type | Our Layer |
|---|---|---|
| `test_aws.py` | AWS access keys, secret keys | regex |
| `test_slack.py` | Slack tokens | regex |
| `test_stripe.py` | Stripe keys | regex |
| `test_twilio.py` | Twilio keys | regex |
| `test_basic_auth.py` | Basic auth headers | scanner_strong |
| `test_jwt.py` | JSON web tokens | scanner_strong |
| `test_high_entropy.py` | High entropy strings | scanner_contextual |

## Integration Priority

| Corpus | Priority | Rationale |
|---|---|---|
| Ai4Privacy | **High** | Largest PII corpus, good entity type coverage, Apache 2.0 license |
| Nemotron-PII | **High** | Complementary types, CC BY 4.0, NVIDIA quality |
| gitleaks fixtures | **High** | Direct secret detection test cases, MIT, well-maintained |
| detect-secrets | **Medium** | Good overlap with gitleaks, Apache 2.0, Yelp-maintained |
| SecretBench | **Medium** | Large but values are often redacted in public version |

## Sample Data Strategy

For offline benchmarking, we ship representative subsets in `tests/fixtures/corpora/`:

- `ai4privacy_sample.json` — 500 rows, stratified by entity type
- `nemotron_sample.json` — 500 rows, stratified by entity type
- `gitleaks_fixtures.json` — all extracted test cases (~100-200 cases)
- `detect_secrets_fixtures.json` — all extracted test cases (~100 cases)
- `secretbench_sample.json` — 200 rows of labeled secret types

Total offline corpus: ~1,500 rows covering PII + secrets.
