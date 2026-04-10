# Sprint 2 Handover — Regex Hardening, Column Name Engine, Testing & Docs

> **Date:** 2026-04-10
> **Theme:** Regex engine hardening, pattern expansion, column name semantics engine, deep benchmark suite, auto-generated docs
> **Branch:** sprint2/main (8 commits)

## Delivered

### Pattern Expansion (43 → 59 patterns)
- **PII:** US NPI (+Luhn), DEA (+check digit), MBI, VIN (+mod-11), EIN (+prefix), European DOB, long-format DOB
- **Financial:** SWIFT/BIC, Bitcoin (P2PKH/P2SH/Bech32), Ethereum (0x+40hex), ABA routing (+checksum 3-7-1), IBAN mod-97 completed
- **PII:** Canadian SIN (+Luhn)
- **Credential:** Discord bot token, npm token, HashiCorp Vault (hvs.), Pulumi (pul-)

### Validators (4 → 11)
- New: `npi_luhn`, `dea_checkdigit`, `vin_checkdigit`, `ein_prefix`, `aba_checksum`, `phone_number` (phonenumbers library)
- Completed: `iban_checksum` (was stub)

### Column Name Semantics Engine (NEW — 2nd engine)
- 400+ sensitive field name variants across 32 entity types
- Three matching strategies: direct lookup, abbreviation expansion (0.95x), multi-token subsequence (0.85x)
- Normalization: camelCase splitting, lowercase, strip separators
- Registered as engine order=1 (before regex order=2)
- 60+ tests

### Regex Engine Quality (Stream 2)
- **Context window confidence boosting** — per-pattern context_words_boost/suppress, scans tokens near matches, adjusts confidence ±0.30
- **Stopword suppression** — global stopwords.json + per-pattern stopwords, known placeholders → hard zero
- **Allowlist mechanism** — per-pattern allowlist regex, known FP patterns → suppress
- **Phone number library** — `phonenumbers` (170+ countries) as phone validator, validates structure + range

### Entity Type Naming Fixes
- IBAN separated from BANK_ACCOUNT (own entity type + profile rule)
- MAC_ADDRESS separated from DEVICE_ID (own entity type + profile rule)
- 32 entity types in column_names.json (was 30)

### Deep Benchmark Suite (NEW)
- **Pattern benchmark** (`pattern_benchmark.py`) — tests regex engine directly on 12,500 raw values, per-sample TP/FP/FN, per-pattern match rates, cross-pattern collision matrix
- **Column benchmark** (`accuracy_benchmark.py`) — tests full pipeline on 18,500 samples across 37 columns, per-engine breakdown, sample-level summary
- **Performance benchmark** (`perf_benchmark.py`) — throughput, per-engine latency, RE2 string-length scaling (50B→50KB), sample-count scaling
- **Report generator** (`generate_report.py`) — produces `docs/sprints/SPRINT{N}_BENCHMARK.md` for sprint-over-sprint comparison
- **Corpus generator** — 22 entity types with valid check digits, format variations, embedded-in-text, 10 negative categories
- **FP corpus** — static negative lookalikes + synthetic near-misses
- **Property-based tests** (Hypothesis) — SSN, email, credit card property tests

### Auto-Generated Client Docs (NEW)
- mkdocs + Material theme + mkdocstrings
- `docs-public/` with API reference (auto from docstrings), catalog (auto from introspection), guides, changelog
- `scripts/generate_catalog.py` generates pattern/entity/profile/validator pages
- `mkdocs serve` for local preview, `mkdocs build` for static site

### Tests
- **398 tests passing** in 0.94s (up from 234)
- Pattern self-tests: 236 (59 patterns × 4 checks)
- Column name engine: 60+ tests
- Hypothesis property tests: 4 test classes
- Golden fixtures: 26 column name + 4 rollup (unchanged)
- Engine behavior: 30+ tests (unchanged)

### Dependencies Added
- **Runtime:** `phonenumbers>=8.13` (phone validation)
- **Dev:** `faker>=25.0`, `hypothesis>=6.100`, `mkdocs>=1.6`, `mkdocs-material>=9.5`, `mkdocstrings[python]>=0.25`

## Benchmark Results (Sprint 2 Final)

### Pattern-Level (12,500 raw samples, regex only)

| Metric | Value |
|---|---|
| Precision | 0.831 |
| Recall | 0.758 |
| **F1** | **0.793** |
| TP / FP / FN | 8,336 / 1,690 / 2,664 |

### Column-Level (18,500 samples, full pipeline)

| Metric | Value |
|---|---|
| Precision | 0.634 |
| Recall | 0.963 |
| **F1** | **0.765** |
| TP / FP / FN | 26 / 15 / 1 |

### Performance

| Metric | Value |
|---|---|
| Throughput | 764K samples/sec |
| Per sample (p50) | 1.3 μs |
| Column name engine | 1% of pipeline |
| Regex engine | 97% of pipeline |
| RE2 scaling | Linear (50B=2μs → 50KB=147μs) |

### Known Collision Pairs
- SSN↔ABA: 524 samples (9-digit structural overlap)
- NPI↔PHONE: 500 samples (10-digit overlap)
- DEA↔IBAN: 10 samples (alphanumeric overlap)

## Deferred to Sprint 3

### From Original Sprint 2 Scope
- **Heuristic statistics engine** — cardinality, entropy, length distribution. Would directly help SSN↔ABA disambiguation via cardinality signal
- **Structured secret scanner** — JSON/YAML/env parsing + key-name + Shannon entropy

### New Items Identified During Sprint
- **Extend ColumnInput with table_name, schema_name, dataset_name** (P1) — enables table/schema-level disambiguation
- **BQ connector coordination** (P1) — surface table/schema context from connector to classifier
- **SSN vs ABA collision resolution strategy** (P1) — structural overlap needs multi-signal approach
- **Adaptive sampling** (P2) — two-pass classification, request more samples for ambiguous columns
- **Sibling column analysis** (P2) — use adjacent columns to disambiguate
- **Credit card patterns: JCB, Diners, 19-digit Visa** (P2)
- **Phone format expansion: extensions, dot-separated** (P2)
- **VIN corpus fix: invalid check digit** (P2 bug)
- **Canadian SIN: Luhn on unformatted values** (P2 bug)

## Decisions Made

1. **Benchmark-driven development** — invested heavily in testing infrastructure before adding features. Found naming mismatches (IBAN, MAC_ADDRESS) and collision patterns that would have been invisible without deep benchmarks.
2. **Two benchmark levels** — pattern-level (raw regex, no column names) and column-level (full pipeline). Both needed because column names mask regex weaknesses.
3. **Global stopwords kept minimal** — broad words like "test", "example" suppressed too much real data. Only clearly placeholder values (test card numbers, AKIAIOSFODNN7EXAMPLE) in global list; common words go in per-pattern stopwords.
4. **phonenumbers as runtime dependency** — first non-dev external dependency beyond RE2. Justified by 170+ country support vs maintaining phone regex.
5. **Context boosting is per-sample, not per-column** — scans tokens within each sample value. Works well for free-text columns, limited value for bare-value structured columns.
6. **Entity type naming matters** — IBAN≠BANK_ACCOUNT, MAC_ADDRESS≠DEVICE_ID. Benchmark caught these mismatches.

## Open Threads (Carry to Sprint 3)

### 1. Table/Schema Context for Classification
The BQ connector has table_name, schema_name, dataset_name — but ColumnInput doesn't expose them. Adding these fields lets the column name engine do compound matching (`employees.ssn` → SSN with higher confidence). **Action:** extend ColumnInput, coordinate with BQ team on what metadata to pass.

### 2. Adaptive Sampling
When the classifier is uncertain (SSN vs ABA on bare 9-digit values), it could request more samples from the connector. Two-pass API: classify → identify ambiguous → request more → reclassify. **Design question:** callback vs batch API?

### 3. Heuristic Statistics Engine
Fully spec'd in doc 04 but not built. Cardinality is the key signal for SSN↔ABA (28K valid ABA numbers vs 900M valid SSNs). Sprint 3 priority.

### 4. Pattern-Level Precision
SSN precision is 0.436 at the pattern level (bare values). The column name engine compensates (column-level recall 96.3%), but raw regex precision needs improvement. Context boosting helps in free-text mode but not for bare structured values.

### 5. Benchmark Corpus Gaps
- No credential samples in benchmark (XOR encoding makes generation complex)
- VIN has only 2 unique valid test values (need more)
- Canadian SIN Luhn failing on unformatted values (bug)
- No embedded-in-text benchmark for all entity types (only SSN, EMAIL, PHONE, CC, NPI)

## Commits

| # | Hash | Description |
|---|---|---|
| 1 | 16a9434 | feat: Sprint 2 batch 1 — patterns, column name engine, testing, docs |
| 2 | 93a0eb8 | fix: expand corpus generator to 22 entity types |
| 3 | 57caa3c | feat: deep benchmark suite — per-sample, per-engine, collision matrix |
| 4 | db176a9 | feat: massive benchmark expansion — 18.5K samples, length scaling |
| 5 | 3c31edc | fix: entity type naming — IBAN, MAC_ADDRESS separation |
| 6 | f903732 | feat: pattern_benchmark.py — per-sample regex detection |
| 7 | 3f425d9 | feat: benchmark report generator + Sprint 2 baseline |
| 8 | b0a590c | feat: Stream 2 — context boosting, stopwords, allowlists, phonenumbers |
