# data_classifier — Roadmap

> Living document. Updated each sprint.
> Last updated: 2026-04-10 (Sprint 2 planning)

## Iteration 1: Foundation + Regex Engine (Complete)

**Theme:** Standalone library with regex-based classification, fixture-based testing, CI green.

| Deliverable | Status | Notes |
|---|---|---|
| Project bootstrap (git, pyproject, CI, Dockerfile) | Done | 2 commits on main |
| Core types (ColumnInput, ClassificationFinding, etc.) | Done | With `category` dimension |
| Engine interface (ClassificationEngine base class) | Done | Full interface for extensibility |
| RE2 two-phase regex engine | Done | Set screening + extraction + validators |
| Pattern library (43 content patterns, JSON) | Done | Benchmarked against Presidio |
| Validators (Luhn, SSN zeros, IPv4) | Done | IBAN mod-97 stub |
| Event telemetry (EventEmitter + TierEvent) | Done | Pluggable handlers |
| Orchestrator (engine cascade) | Done | Budget-aware, mode-based |
| Bundled standard profile (15 rules, 4 categories) | Done | With `category` field |
| Client integration guide | Done | Shared with BQ team |
| Pattern HTML reference | Done | Generated from JSON |
| Golden-set fixture tests (26 column name + 4 rollup) | Done | Parameterized contract tests |
| 234 tests (patterns, engine, golden, rollups, confidence) | Done | 0.31s local, CI green |

## Iteration 2: Regex Hardening + Content Engines + Testing

**Theme:** Expand and harden the regex engine, add first deterministic engines, establish accuracy measurement.

### Pattern Expansion

| Deliverable | Scope |
|---|---|
| PII pattern expansion | US NPI (+Luhn), US DEA (+check digit), US MBI, VIN (+check digit mod-11), US EIN (+prefix validation), additional DOB formats (DD/MM/YYYY, DD MMM YYYY, Month DD YYYY) |
| Financial pattern expansion | SWIFT/BIC, Bitcoin (P2PKH/P2SH/Bech32), Ethereum (0x + 40 hex), ABA routing (+checksum 3-7-1), IBAN mod-97 completion |
| Canadian SIN pattern + Luhn validator | 9-digit Luhn-validated |
| Credential pattern expansion (small batch) | Discord bot token, npm token, Hashicorp Vault (hvs.), Pulumi (pul-) |

### Regex Engine Quality Enhancements

| Deliverable | Scope | Inspired By |
|---|---|---|
| Context window confidence boosting | Per-pattern context words with directional proximity window; boost confidence when context matches ("SSN:" before 9 digits), suppress when negative context matches ("order #") | Presidio LemmaContextAwareEnhancer, Cloud DLP HotwordRules |
| Stopword / anti-indicator suppression | Known placeholder values ("changeme", "AKIAIOSFODNN7EXAMPLE", test card numbers 4111111111111111) → hard zero confidence | gitleaks stopwords |
| Allowlist / FP suppression mechanism | Per-pattern allowlist regex targeting value, match, or line scope; boolean combinator (AND/OR) | gitleaks allowlists |
| Phone number library integration | Delegate phone detection to `phonenumbers` library (170+ countries, format normalization, range validation) instead of regex-only | Presidio PhoneRecognizer |

### New Engines

| Deliverable | Scope |
|---|---|
| Column name semantics engine | 400+ sensitive name variants, fuzzy matching (lowercase + strip separators), abbreviation expansion (dob → date_of_birth), multi-token matching |
| Heuristic statistics engine | Cardinality, length distribution, entropy, character class ratios, pattern consistency. Confidence booster/reducer, not standalone |
| Structured secret scanner | Parse JSON/YAML/env/code → key-value extraction → key-name dictionary + Shannon entropy scoring + anti-indicators |

### Testing & Benchmarking

| Deliverable | Scope |
|---|---|
| Synthetic corpus generator (Faker-based) | Generate labeled columns per entity type, parametrized by locale, with adversarial near-misses |
| Accuracy benchmark harness | Measures precision/recall/F1 per entity type; runs as separate command, not in CI |
| FP test corpus | Negative lookalikes (order numbers that look like SSNs, random strings that look like API keys) + synthetic near-misses |
| Property-based testing (Hypothesis) | Edge case generation for pattern matching — malformed inputs, boundary values, unicode |
| Performance benchmark tests | Latency regression baseline, throughput measurement per pattern count |

### Documentation

| Deliverable | Scope |
|---|---|
| Auto-generated client docs (mkdocs + mkdocstrings) | `docs-public/` source, `site/` output, GitHub Pages deploy via CI |
| API reference (auto-generated) | All public functions + types from docstrings and type hints |
| Entity/pattern/profile catalog (auto-generated) | `scripts/generate_catalog.py` → catalog pages from introspection APIs |
| Integration guide + examples (hand-written) | Moved from `docs/CLIENT_INTEGRATION_GUIDE.md` to `docs-public/guides/` |

### Other

| Deliverable | Scope |
|---|---|
| `/classify/text` endpoint (unstructured) | NER-independent text classification using regex + patterns |
| Event-based observability | Structured JSONL output, `/stats` endpoint, latency tracker |

## Iteration 3: ML Engines + International Coverage

**Theme:** Add ML-based classification, international ID patterns, consumer extensibility.

### ML Engines

| Deliverable | Scope |
|---|---|
| GLiNER2 engine (205M) | NER + text classification, lazy loading via ModelRegistry |
| PII Base NER engine (~500M) | Entity detection (names, medical, addresses) — highest PII accuracy |
| EmbeddingGemma engine (308M) | Semantic similarity, topic sensitivity, taxonomy matching |
| Model registry + lazy loading | Shared instances, load on first use |
| Budget-aware parallel execution | Live p95 latency tracking, parallel slow-tier scheduling |
| Standard + Advanced profiles | Profile-driven engine selection |

### Pattern & Engine Expansion

| Deliverable | Scope |
|---|---|
| Country-specific IDs phase 1 | UK (NHS+mod-11, passport, postcode), DE (tax ID, passport, ID card), AU (ABN+mod-89, TFN+mod-11, Medicare), IN (PAN, Aadhaar+Verhoeff) |
| Financial identifiers | CUSIP (+check digit, context-dependent), ISIN (+Luhn), EU VAT (per-country formats) |
| Dictionary lookup engine | Consumer-provided value lists (hash-set, case-insensitive, prefix match) |
| Custom pattern injection via config | Consumer-injected patterns compiled into RE2 Set |

### Testing

| Deliverable | Scope |
|---|---|
| External corpus: Nemotron-PII ETL | Extract column values from 100K structured records, 55+ types (CC BY 4.0) |
| External corpus: SecretBench + FPSecretBench | Data agreement + ETL for 97K labeled secrets + FP corpus from 9 tools (MIT + agreement) |
| External corpus: Ai4Privacy pii-masking-300k | NER spans → column values ETL, 225K rows, 27+ PII types (custom license, research OK) |
| External corpus: StarPII | 20K annotated secrets in code snippets, credential testing (gated access) |
| External corpus: Nightfall samples | Curated CSVs for PII + credentials + explicit negative lookalikes (free eval) |
| Presidio cross-validation comparison | Run same inputs through Presidio + us, compare precision/recall |

### Infrastructure

| Deliverable | Scope |
|---|---|
| `/classify/column` HTTP endpoint | FastAPI wrapper over Python API |
| `/health` endpoint | Service health check |
| Dockerfile for standalone deployment | Production-ready container |

## Iteration 4: Prompt Analysis + Advanced

**Theme:** Zone segmentation, intent classification, risk scoring for LLM prompt gateways.

| Deliverable | Scope |
|---|---|
| Prompt analysis module | Zone segmentation + intent classification + risk cross-correlation |
| `/analyze/prompt` endpoint | Full prompt risk analysis |
| NLI engine (BART-MNLI, 400M) | Entailment-based intent cross-verification |
| SLM engine (Gemma 3/4, 4B) | Chain-of-thought reasoning for ambiguous cases |
| Structural content classifier | ML-trained code/config/query/log/CLI/markup detection |
| Boundary detector | Content-type transition detection in mixed text |
| Financial density scorer | Currency + percentage + financial term clustering |
| Maximum profile | All engines, LLM fallback |

## Future (Iteration 5+)

| Area | Scope |
|---|---|
| LLM API fallback engine | Gemini Flash / Claude Haiku for genuinely novel types |
| Country-specific IDs phase 2 | 20+ countries (KR, IT, ES, PL, FI, SE, TH, NG, SG, etc.) per Presidio coverage |
| Tier 3 patterns | GPS coordinates, US NDC drug codes, CPT/HCPCS (strong context), US DL per-state, credit card track 2 data |
| Cloud DLP integration | Google Cloud DLP engine, zone-focused scanning |
| ML training pipeline | Offline: data collection, feature engineering, model training, export |
| Feedback loop | Runtime corrections → retraining → improved accuracy |
| PyPI publishing | `pip install data_classifier` from PyPI |
| RE2 to Hyperscan migration | Only if >10K req/s; SIMD-accelerated DFA matching |

## Presidio Coverage Parity

Current gap analysis vs Microsoft Presidio (~60 regex recognizers):

| Category | Presidio | Ours (iter 1) | Iter 2 Target | Iter 3 Target |
|---|---|---|---|---|
| US PII (SSN, CC, email, phone, IP) | 9 recognizers | 15 patterns | +6 (NPI, DEA, MBI, VIN, EIN, DOB) | Parity |
| Financial (IBAN, ABA, SWIFT, crypto) | 3 recognizers | 6 patterns | +5 (SWIFT, BTC, ETH, ABA, IBAN done) | +3 (CUSIP, ISIN, EU VAT) |
| Credentials (API keys, tokens) | 0 (ML only) | 20 patterns | +4 (Discord, npm, Vault, Pulumi) | **We lead** |
| Medical (NPI, MBI, DEA, NHS) | 3 recognizers | 2 patterns | +3 (NPI, DEA, MBI) | +1 (NHS) |
| Country-specific IDs | ~40 recognizers | 2 (ITIN, NINO) | +1 (Canadian SIN) | +12 (UK, DE, AU, IN) |
| Crypto wallet | 1 recognizer | 0 | +2 (BTC, ETH) | Parity+ |

Our differentiators vs Presidio:
- RE2 two-phase set matching (Presidio uses Python `re`)
- Context window confidence boosting (comparable to Presidio's LemmaContextAwareEnhancer)
- Shannon entropy gating for credentials (Presidio has none)
- Stopword / allowlist FP suppression (comparable to gitleaks)
- Phone number library integration (comparable to Presidio PhoneRecognizer)
- Category dimension (PII/Financial/Credential/Health)
- Sample-based confidence + prevalence model
- Budget-aware orchestrator
- Structured secret scanner (key-name + entropy — Presidio has nothing like this)
