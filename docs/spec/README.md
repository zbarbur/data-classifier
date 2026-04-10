# Specification Documents — Index & Roadmap Mapping

> These are the architectural specification documents for the full classification library vision.
> They were created during the design phase and serve as the source of truth for what the library
> will eventually become. Not everything is implemented yet — see the Roadmap Mapping below.

## Document Index

| # | Document | Scope | Iteration |
|---|---|---|---|
| — | `CLAUDE.md` | Project overview, build stages, key patterns | Reference |
| — | `DECISIONS.md` | 34 architectural decisions with rationale | Reference |
| — | `classification-library-spec.md` | Master implementation spec | Reference |
| 01 | `01-architecture.md` | System architecture, deployment modes, engine stack | 1-4 |
| 02 | `02-api-reference.md` | HTTP API contract (frozen for iteration 1) | 1 (Python), 3 (HTTP) |
| 03 | `03-integration-guide.md` | Quick start, integration patterns, deployment | 3+ |
| 04 | `04-engines.md` | All 14 engines: capabilities, limitations, pipeline scope | 1-4 |
| 05 | `05-pipelines.md` | Structured/unstructured/prompt pipelines, budget execution | 1-4 |
| 06 | `06-use-cases.md` | BigQuery scanner, prompt gateway, CI/CD gate scenarios | Reference |
| 07 | `07-performance-resource-management.md` | Latency budget, resource budget, profiles, scaling | 2-4 |
| 08 | `08-prompt-analysis-module-spec.md` | Zone segmentation, intent classification, risk scoring | 4 |
| 09 | `09-structural-detection-spec.md` | Structural classifier, boundary detector, secret scanner | 2-4 |
| 10 | `10-ml-architecture-exploration.md` | CNN/RNN/Attention/SSM analysis, ModernBERT, distillation | 5+ |
| 14 | `14-regex-engine-reference.md` | RE2 architecture, two-phase matching, performance | 1 (implemented) |
| — | `research-summary-prompt-intent-classification.md` | Academic research on prompt analysis | Reference |

## Roadmap Mapping

### Iteration 1 (Complete) — Foundation + Regex

| Spec Section | Implementation Status |
|---|---|
| 01: Deployment modes (embedded) | Done — Python package |
| 01: Engine stack (regex) | Done — RE2 two-phase |
| 02: POST /classify/column (Python API only) | Done — `classify_columns()` |
| 04: Regex engine | Done — 43 patterns, validators, RE2 Set |
| 04: Engine base class | Done — `ClassificationEngine` interface |
| 05: Structured pipeline (regex tier only) | Done — orchestrator + single engine |
| 07: Latency budget (accepted, not enforced) | Done — `budget_ms` parameter |
| 14: RE2 architecture | Done — Set screening + extraction |
| DECISIONS: D7 (stateless), D19 (incremental), D34 (RE2) | Done |

### Iteration 2 — Content Engines

| Spec Section | What to Build |
|---|---|
| 04: Column Name Semantics engine | 400+ name variants, fuzzy matching |
| 04: Heuristic Statistics engine | Cardinality, entropy, length distribution |
| 04: Customer Dictionaries engine | Hash-set lookup, consumer-provided |
| 05: Structured pipeline (full fast tier) | All fast engines running in sequence |
| 07: Latency profiling | Measure per-engine latency, report via events |
| 09: Structured Secret Scanner | JSON/YAML/env parse → key-value → entropy |

### Iteration 3 — ML Engines

| Spec Section | What to Build |
|---|---|
| 01: Engine stack (slow tier) | GLiNER2, PII Base, EmbeddingGemma |
| 02: POST /classify/column (HTTP) | FastAPI wrapper |
| 03: Integration patterns | Docker, sidecar, standalone modes |
| 04: GLiNER2 engine | NER + text classification, lazy loading |
| 04: PII Base NER | Entity detection (~500M model) |
| 04: EmbeddingGemma | Semantic similarity, taxonomy matching |
| 05: Budget-aware parallel execution | p95 latency tracking, parallel slow tiers |
| 07: Resource budget (profiles) | Standard, Advanced profile definitions |
| CLAUDE.md: ModelRegistry | Lazy loading, shared instances |

### Iteration 4 — Prompt Analysis

| Spec Section | What to Build |
|---|---|
| 05: Prompt pipeline | Zone segmentation + intent + content + risk |
| 08: Full prompt analysis module | Zone segmenter, intent classifier, risk engine |
| 04: NLI engine (BART-MNLI) | Entailment-based intent verification |
| 04: SLM engine (Gemma) | Chain-of-thought reasoning |
| 09: Structural classifier | ML-trained code/config detection |
| 09: Boundary detector | Content-type transitions |

### Iteration 5+ — Advanced

| Spec Section | What to Build |
|---|---|
| 01: Engine stack (heavy tier) | LLM API fallback |
| 04: Cloud DLP engine | Google Cloud DLP integration |
| 07: Scaling (workers, vectorization) | Multi-worker, numpy batch |
| 09: ML training pipeline | Offline training, decision rule export |
| 10: Neural feature discovery | CNN/RNN/Attention architecture research |

## What's NOT in Scope (Study Material)

These documents exist for learning/research, not implementation:

- `10-ml-architecture-exploration.md` — architecture analysis (CNN, RNN, SSM)
- `research-summary-prompt-intent-classification.md` — academic papers review

Referenced docs that don't exist in this repo (study guides):
- `11-ssm-reference-guide.md` — SSM mathematics
- `12-ssm-learning-guide.md` — what each matrix learns
- `13-study-program.md` — 12-week curriculum
