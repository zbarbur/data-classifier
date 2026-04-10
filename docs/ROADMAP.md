# data_classifier — Roadmap

> Living document. Updated each sprint.
> Last updated: 2026-04-10 (Sprint 1 bootstrap)

## Iteration 1: Foundation + Regex Engine (Current)

**Theme:** Standalone library with regex-based classification, fixture-based testing, CI green.

| Deliverable | Status | Notes |
|---|---|---|
| Project bootstrap (git, pyproject, CI, Dockerfile) | Done | 2 commits on main |
| Core types (ColumnInput, ClassificationFinding, etc.) | Done | With `category` dimension |
| Engine interface (ClassificationEngine base class) | Done | Full interface for extensibility |
| RE2 two-phase regex engine | Done | Set screening + extraction + validators |
| Pattern library (26 content patterns, JSON) | Done | Benchmarked against Presidio |
| Validators (Luhn, SSN zeros, IPv4) | Done | IBAN mod-97 stub |
| Event telemetry (EventEmitter + TierEvent) | Done | Pluggable handlers |
| Orchestrator (engine cascade) | Done | Budget-aware, mode-based |
| Bundled standard profile (15 rules, 4 categories) | Done | With `category` field |
| Client integration guide | Done | Shared with BQ team |
| Pattern HTML reference | Done | Generated from JSON |
| Port BQ connector test fixtures | Pending | Golden-set behavioral contract |
| Parameterized tests (golden fixtures) | Pending | Sprint 27 migration guarantee |
| Contract review (all BQ consumers mapped) | Pending | Migration plan doc |
| Backlog initialization | Pending | This sprint |

## Iteration 2: Content Engines + Coverage

**Theme:** Add engines that analyze sample values and column content. Expand pattern library.

| Deliverable | Scope |
|---|---|
| Column name semantics engine | 400+ sensitive name variants, fuzzy matching, abbreviation expansion |
| Heuristic statistics engine | Cardinality, length distribution, entropy, character class analysis |
| Dictionary lookup engine | Consumer-provided value lists (hash-set, case-insensitive, prefix match) |
| Pattern library expansion to 50+ | URL, crypto wallet, ABA routing, NPI, US ITIN, GCP/Stripe keys |
| IBAN mod-97 validator | Complete the stub |
| `/classify/text` endpoint (unstructured) | NER-independent text classification using regex + patterns |
| Structured secret scanner | Parse JSON/YAML/env → key-value → key-name + entropy scoring |
| Event-based observability | Structured JSONL, `/stats` endpoint, latency tracker |
| `load_profile()` with custom patterns | Consumer-injected patterns compiled into RE2 Set |
| Country-specific ID patterns (phase 1) | US (SSN, ITIN, passport, DL per state) + EU (IBAN, GDPR IDs) |

## Iteration 3: ML Engines

**Theme:** Add ML-based classification for content that regex can't detect.

| Deliverable | Scope |
|---|---|
| GLiNER2 engine (205M) | NER + text classification, lazy loading via ModelRegistry |
| PII Base NER engine (~500M) | Entity detection (names, medical, addresses) — highest PII accuracy |
| EmbeddingGemma engine (308M) | Semantic similarity, topic sensitivity, taxonomy matching |
| Model registry + lazy loading | Shared instances, load on first use |
| Budget-aware parallel execution | Live p95 latency tracking, parallel slow-tier scheduling |
| Standard + Advanced profiles | Profile-driven engine selection |
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
| Country-specific ID library (phase 2) | 20+ countries (AU, IN, KR, DE, IT, UK, etc.) per Presidio coverage |
| Cloud DLP integration | Google Cloud DLP engine, zone-focused scanning |
| ML training pipeline | Offline: data collection, feature engineering, model training, export |
| Feedback loop | Runtime corrections → retraining → improved accuracy |
| PyPI publishing | `pip install data_classifier` from PyPI |
| Performance benchmarking | Latency benchmarks, throughput testing, profiling |

## Presidio Coverage Parity

Current gap analysis vs Microsoft Presidio (~60 regex recognizers):

| Category | Presidio | Ours (iter 1) | Target |
|---|---|---|---|
| US PII (SSN, CC, email, phone, IP) | 9 recognizers | 26 patterns | Parity in iter 1 |
| Financial (IBAN, ABA routing) | 3 recognizers | 2 patterns (IBAN stub) | Iter 2 |
| Credentials (API keys, tokens) | 0 (ML only) | 6 patterns | **We lead** |
| Medical (NPI, MBI, NHS) | 3 recognizers | 2 patterns | Iter 2 |
| Country-specific IDs | ~40 recognizers | 0 | Iter 2-5 (phased) |
| Crypto wallet | 1 recognizer | 0 | Iter 2 |

Our differentiators vs Presidio:
- RE2 two-phase set matching (Presidio uses Python `re`)
- Connection string detection
- Generic API key patterns
- GitHub token detection
- Category dimension (PII/Financial/Credential/Health)
- Sample-based confidence + prevalence model
- Budget-aware orchestrator
