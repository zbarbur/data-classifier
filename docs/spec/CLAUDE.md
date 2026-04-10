# CLAUDE.md — Classification Library

## Project Overview

General-purpose, API-first data classification engine. Detects and classifies sensitive data in structured (database columns) and unstructured (free text, prompts) content. Stateless library — consumers own persistence.

Two modules:
1. **Classification Library** — tiered content detection (PII, PHI, PCI, credentials)
2. **Prompt Analysis Module** — zone segmentation + intent classification + risk scoring for LLM prompt leak detection

## Architecture Decisions (Settled)

- **Stateless** — library never connects to a database, never writes to disk. Consumers inject config (dictionaries, patterns, model paths) at init or per-request.
- **Dual-mode API** — `/classify/column` for structured data, `/classify/text` for unstructured, `/analyze/prompt` for prompt analysis.
- **Tiered cascade** — 8 content tiers: regex → heuristics → Cloud DLP → dictionaries → GLiNER2 → embeddings → SLM → LLM. Cheap/fast first, expensive last.
- **Budget-aware orchestrator** — per-request `budget_ms` triggers adaptive parallel execution using live p95 latency tracking. No budget = sequential cascade.
- **Profiles** — Free (fast tiers only), Standard (+DLP +GLiNER2), Advanced (+embeddings +SLM), Maximum (+LLM).
- **Event-based observability** — structured JSONL events via pluggable handler. Library emits, consumer persists and analyzes.
- **Separation of concerns** — content detection and intent classification are parallel, independent analyses. They converge only at the risk cross-correlation layer.
- **GLiNER2 as unified model** — single 205M model for NER + text classification + structured extraction. Shared instance between classification library and prompt module.
- **Gemma-first for ML tiers** — EmbeddingGemma (308M) for embeddings, Gemma 3 4B-IT default SLM. Model interfaces abstracted for swappability.
- **Lazy model loading** — ML models load on first invocation, not at startup.

## Technology Stack

- **Python 3.11+**
- **FastAPI** — API service wrapper
- **GLiNER2** (205M) — NER + text classification + structured extraction
- **GLiNER PII base** (500M) — optional PII-specialized NER (higher PII accuracy)
- **EmbeddingGemma** (308M) — semantic similarity
- **BART-MNLI** (400M) — NLI-based intent verification (prompt module)
- **Gemma 3 4B-IT** — SLM tier (quantized 4-bit via llama.cpp or similar)
- **Google Cloud DLP** — Cloud DLP tier (pluggable interface)
- **pydantic** — request/response models
- **numpy** — latency tracker percentile calculations
- **ONNX Runtime** — quantized model inference

## Project Structure

```
classification-library/
├── CLAUDE.md                          # this file
├── pyproject.toml
├── README.md
├── docs/                              # implementation docs (15 docs + 12 diagrams)
│   ├── 01-architecture.md
│   ├── 02-api-reference.md
│   ├── 03-integration-guide.md
│   ├── 04-engines.md
│   ├── 05-pipelines.md
│   ├── 06-use-cases.md
│   ├── 07-performance-resource-management.md
│   ├── 08-prompt-analysis-module-spec.md
│   └── classification-library-spec.md  # master implementation spec
│
├── src/
│   ├── classification_library/
│   │   ├── __init__.py                # Classifier, Profile, ColumnInput exports
│   │   ├── models.py                  # ClassificationResult, ClassificationResponse, ColumnInput, Span
│   │   ├── config.py                  # Profile definitions, engine registry, mode definitions
│   │   ├── orchestrator.py            # UNIFIED orchestrator: mode=structured|unstructured|prompt
│   │   ├── engines/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                # ClassificationEngine base class
│   │   │   ├── structural_classifier.py  # NEW: ML-trained code/config/query/log/CLI/markup detection
│   │   │   ├── boundary_detector.py      # NEW: sliding window content-type boundary detection
│   │   │   ├── regex_engine.py        # Formatted PII + known-format secrets (AKIA, JWT, PEM)
│   │   │   ├── structured_secret_engine.py # NEW: parse structure → key-value → key-name + entropy scoring
│   │   │   ├── column_name_engine.py  # Structured mode only
│   │   │   ├── heuristic_engine.py    # Structured mode only (statistics)
│   │   │   ├── cloud_dlp_engine.py    # Google Cloud DLP
│   │   │   ├── dictionary_engine.py   # Consumer-provided value lists
│   │   │   ├── pii_ner_engine.py      # PII Base (~500M) for NER
│   │   │   ├── gliner2_engine.py      # GLiNER2 (205M) for intent + zones
│   │   │   ├── embedding_engine.py    # EmbeddingGemma — topic sensitivity + intent similarity
│   │   │   ├── nli_engine.py          # NLI/BART-MNLI — prompt mode only
│   │   │   ├── slm_engine.py          # Gemma 3-4B — reasoning
│   │   │   └── llm_engine.py          # API fallback
│   │   ├── patterns/
│   │   │   ├── default_patterns.json  # 50+ regex patterns (PII + secrets)
│   │   │   ├── column_names.json      # 400+ sensitive field name variants
│   │   │   ├── secret_key_names.json  # Secret-indicating key names with scores
│   │   │   ├── taxonomy_embeddings.npz # pre-computed reference taxonomy
│   │   │   └── structural_rules.py    # ML-exported decision rules (or .xgb model)
│   │   └── labels/
│   │       ├── pii_labels.json
│   │       ├── phi_labels.json
│   │       ├── pci_labels.json
│   │       └── credential_labels.json
│   │
│   ├── prompt_analysis/
│   │   ├── __init__.py                # PromptAnalyzer export
│   │   ├── models.py                  # Zone, Intent, RiskScore, PromptAnalysisResponse
│   │   ├── prompt_orchestrator.py     # Coordinates zones + intent + content + risk
│   │   ├── zone_segmenter.py
│   │   │   ├── heuristic_zones.py
│   │   │   └── model_zones.py         # GLiNER2 structured extraction
│   │   ├── intent_classifier.py
│   │   │   ├── heuristic_intent.py
│   │   │   ├── gliner2_intent.py
│   │   │   ├── embedding_intent.py
│   │   │   ├── nli_intent.py
│   │   │   └── slm_intent.py
│   │   ├── risk_engine.py
│   │   └── intent_labels/
│   │       └── default_intents.json
│   │
│   └── shared/
│       ├── __init__.py
│       ├── model_registry.py          # Lazy loading, shared instances
│       ├── event_emitter.py           # Pluggable event handlers
│       ├── events.py                  # Event dataclasses
│       ├── latency_tracker.py         # Rolling window p50/p95/p99
│       └── budget.py                  # Budget-aware scheduling logic
│
├── api/
│   ├── __init__.py
│   ├── app.py                         # FastAPI app
│   ├── routes_classify.py             # /classify/column, /classify/table, /classify/text
│   ├── routes_prompt.py               # /analyze/prompt
│   ├── routes_utility.py              # /profiles, /labels, /stats, /health
│   └── request_models.py             # Pydantic request/response schemas
│
├── tests/
│   ├── test_regex_tier.py
│   ├── test_column_name_tier.py
│   ├── test_heuristic_tier.py
│   ├── test_orchestrator.py
│   ├── test_zone_segmenter.py
│   ├── test_intent_classifier.py
│   ├── test_risk_engine.py
│   ├── test_api_classify.py
│   ├── test_api_prompt.py
│   ├── fixtures/
│   │   ├── sample_columns.json        # test column inputs
│   │   ├── sample_prompts.json        # test prompt inputs
│   │   └── expected_results.json      # expected outputs
│   └── benchmarks/
│       ├── bench_latency.py
│       └── bench_accuracy.py
│
└── Dockerfile

ml_pipeline/                             # OFFLINE training pipeline (separate repo or directory)
├── data/
│   ├── collectors/                      # Fetch training data from GitHub, LogHub, etc.
│   ├── generators/                      # Synthetic mixed-content generator
│   └── loaders/                         # Unified dataset loading
├── features/
│   ├── block_features.py                # 40 features for structural classifier
│   └── line_features.py                 # Per-line features for boundary detection
├── training/
│   ├── structural_trainer.py            # Train block classifier (XGBoost/LightGBM)
│   ├── boundary_trainer.py              # Train boundary detector
│   └── hyperparameter_search.py         # Bayesian HP optimization
├── evaluation/
│   ├── block_evaluator.py               # Per-class precision/recall/F1
│   ├── boundary_evaluator.py            # Boundary accuracy within N lines
│   └── report_generator.py              # Evaluation report
├── export/
│   ├── decision_rules_exporter.py       # XGBoost → Python if/else
│   └── weights_exporter.py              # Key-name weights → JSON
└── scripts/
    ├── train_all.py                     # Full pipeline: collect → train → export
    └── retrain_with_feedback.py         # Incremental retrain with runtime data
```

## Build Stages

Build incrementally. Each stage is independently shippable and testable.

### Stage 1: Foundation + Regex (start here)
Files: models.py, config.py, orchestrator.py, base.py, regex_tier.py, default_patterns.json
- ClassificationResult, ClassificationResponse, ColumnInput data models
- Profile enum and tier registry
- Orchestrator with cascade logic (works with 1 tier)
- Regex tier with 50+ curated patterns (SSN, CC+Luhn, email, phone, JWT, AWS keys, etc.)
- FastAPI: /classify/column, /classify/text, /health
- Tests: pattern accuracy suite
Goal: `classifier.classify_text("SSN: 123-45-6789")` works end-to-end.

### Stage 2: Column Name + Heuristics
Files: column_name_tier.py, heuristic_tier.py, column_names.json
- Column name semantic matching (400+ variants)
- Statistical heuristics (length, cardinality, entropy, character classes)
- Free profile fully functional
Goal: `classifier.classify_column(ColumnInput(column_name="customer_ssn"))` classified in <1ms.

### Stage 3: Cloud DLP
Files: cloud_dlp_tier.py
- Google Cloud DLP inspect_content integration
- Pluggable provider interface
- Standard profile partially functional
Goal: columns that regex misses get caught by DLP.

### Stage 4: Dictionaries
Files: dictionary_tier.py
- Hash-set lookup (exact, case-insensitive, prefix)
- Consumer injects dictionaries at init
Goal: customer-specific terms detected.

### Stage 5: GLiNER2
Files: gliner_tier.py, model_registry.py (shared lazy loading), pii/phi/pci/credential labels
- GLiNER2 for NER (content detection)
- GLiNER2 for text classification (used later by prompt module)
- Lazy loading, ONNX quantization
- Standard profile fully functional
Goal: `classify_text("Patient John Smith diagnosed with diabetes")` detects person name + medical condition.

### Stage 6: Embeddings
Files: embedding_tier.py, taxonomy_embeddings.npz
- EmbeddingGemma loading
- Pre-computed reference taxonomy (80+ categories)
- Cosine similarity matching
- Matryoshka dimension selection
Goal: `classify_column(ColumnInput(column_name="remuneration_pkg"))` → salary.

### Stage 7: SLM
Files: slm_tier.py
- Gemma 3 4B-IT with structured prompt
- 4-bit quantization
- Model size selector in config
- Advanced profile fully functional
Goal: ambiguous columns classified through contextual reasoning.

### Stage 8: LLM + Budget Engine
Files: llm_tier.py, budget.py, latency_tracker.py
- LLM API fallback (Gemini/Claude/OpenAI)
- Latency tracker with rolling window
- Budget-aware parallel execution
- Maximum profile fully functional
Goal: budget_ms=100 correctly schedules parallel tiers.

### Stage 9: Events + Observability
Files: event_emitter.py, events.py
- Structured event types (TierEvent, ClassificationEvent, FeedbackEvent, RunEvent)
- Pluggable handlers (Null, Stdout, JSONL, Callback, Multi)
- Run lifecycle (start/complete)
- /stats endpoint
Goal: every classification emits structured JSONL events.

### Stage 10: Prompt Module MVP
Files: prompt_analysis/ (heuristic zones + keyword intent + risk engine + API)
- Heuristic zone segmenter
- Keyword intent classifier
- Risk cross-correlation engine
- /analyze/prompt endpoint
Goal: prompt analysis works with heuristics only, no ML dependency.

### Stage 11: Prompt Module ML Tiers
Files: model_zones.py, gliner2_intent.py, embedding_intent.py, nli_intent.py, slm_intent.py
- GLiNER2 zone extraction + intent classification
- Embedding intent matching
- NLI cross-verification (BART-MNLI)
- SLM reasoning
Goal: full prompt analysis stack operational.

### Stage 12: Structural Detection (Heuristic)
Files: structural_classifier.py, boundary_detector.py, structured_secret_engine.py
- Heuristic structural classifier (code/config/query/log/CLI/markup detection)
- Heuristic boundary detector (code fences, delimiters, structural shifts)
- Structured secret scanner (parsers + key-name dictionary + entropy scoring)
- Structure parsers: JSON, YAML, env, XML, SQL position, CLI argument, HTTP header
- String literal extraction from code (any language: `identifier = "value"` patterns)
Goal: `classify_text("DB_PASSWORD=secret123")` detects secret via key-name + entropy without regex match.

### Stage 13: ML Training Pipeline (Offline)
Files: ml_pipeline/ (separate directory)
- Data collectors for GitHub code, config files, LogHub, prose corpora
- Synthetic mixed-content prompt generator with labeled boundaries
- Feature extractor (40 features for block classification)
- XGBoost/LightGBM trainer with cross-validation
- Decision rules exporter (model → Python if/else)
Goal: trained structural classifier with >0.90 weighted F1 across 7 classes.

### Stage 14: ML-Trained Structural Detection
Files: structural_rules.py (exported from ML pipeline)
- Replace heuristic classifier with ML-trained decision rules
- Replace heuristic boundary detector with sliding-window ML classification
- Evaluate precision/recall per class, boundary accuracy within ±2 lines
- Keep heuristics as fallback
Goal: measurable accuracy improvement over heuristics on held-out test set.

### Stage 15: Runtime Feedback Loop
Files: event_collector.py, retrain_with_feedback.py
- Collect structural classification events with features
- Consumer feedback integration (correct/incorrect labels)
- Periodic retraining with runtime data
- Model versioning and A/B comparison
Goal: continuous improvement — each retrain cycle improves on the previous model.

## Key Patterns

### Engine Base Class
```python
class ClassificationEngine:
    name: str
    order: int
    min_confidence: float
    supported_modes: set[str]  # {"structured", "unstructured", "prompt"}

    def classify_column(self, column: ColumnInput) -> list[ClassificationResult]:
        return []  # override if engine supports structured mode

    def classify_text(self, text: str) -> list[ClassificationResult]:
        return []  # override if engine supports text/prompt mode
```

### Lazy Model Loading
```python
class ModelRegistry:
    _instances = {}

    @classmethod
    def get(cls, model_name: str, loader_fn):
        if model_name not in cls._instances:
            cls._instances[model_name] = loader_fn()
        return cls._instances[model_name]
```

### Event Emission
```python
# Every tier wraps execution with event emission
t0 = time.monotonic()
results = tier.classify_text(text)
elapsed = (time.monotonic() - t0) * 1000
self.latency.record(tier.name, elapsed)
self.events.emit(TierEvent(tier=tier.name, latency_ms=elapsed, outcome="hit" if results else "miss"))
```

## Conventions

- Type hints on all public interfaces
- Pydantic for API request/response models
- Dataclasses for internal models
- Tests for every tier: accuracy suite (known PII → detected, known non-PII → not detected)
- No print statements — use Python logging
- Config injection pattern — never hardcode paths, model names, or thresholds

## Reference Docs

All design decisions, API contracts, tier details, and use cases are documented in `docs/`. Read the relevant doc before implementing each stage:

- Stage 1-8: `docs/classification-library-spec.md` (master spec)
- Engines: `docs/04-engines.md` + `docs/05-pipelines.md`
- API: `docs/02-api-reference.md`
- Performance: `docs/07-performance-resource-management.md`
- Stage 10-11: `docs/08-prompt-analysis-module-spec.md`
- Stage 12-15: `docs/09-structural-detection-spec.md` (structural classifier, secret scanner, ML pipeline)
- ML architecture: `docs/10-ml-architecture-exploration.md` (CNN/RNN/Attention/SSM analysis, ModernBERT, distillation, feature harvesting, architecture search)

**Learning references (not part of implementation pack — for human study only):**
- SSM deep dive: `11-ssm-reference-guide.md` (step-by-step from first principles through Mamba-3)
- SSM learning: `12-ssm-learning-guide.md` (how every matrix is initialized, what it learns, gradient flow)
- Study program: `13-study-program.md` (12-week curriculum: attention → transformers → SSMs → hybrids)
- Use cases: `docs/06-use-cases.md`
- Regex engine: `docs/14-regex-engine-reference.md` (RE2 architecture, two-phase matching, set matching, pattern library, performance, Hyperscan future option)
- Research: `docs/research-summary-prompt-intent-classification.md`
