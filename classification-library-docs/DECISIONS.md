# Classification Library — Decision Log

Chronological record of design decisions made during the architecture phase. Reference for Claude Code sessions and future discussions.

---

## D1: Tiered Cascade Architecture
**Decision:** 8-tier cascade ordered by cost/complexity: Regex → Cloud DLP → Dictionaries → Heuristics → GLiNER → Embeddings → SLM → LLM.
**Rationale:** Cheap/fast tiers first. Each tier only processes what previous tiers didn't classify.
**Revised:** Regex moved before Cloud DLP (free vs API cost). Heuristics promoted to early position.

## D2: GLiNER Over spaCy for NER
**Decision:** Use GLiNER for NER tier, not spaCy.
**Rationale:** Zero-shot — define entity labels at runtime without retraining. Customers define their own sensitive entity types. 81% F1 on PII benchmarks. Runs on CPU.

## D3: SLM Before LLM
**Decision:** SLM (small language model) tier before LLM API fallback.
**Rationale:** Local inference, no API cost, privacy-safe. Fine-tunable on customer data. A fine-tuned 4B model often outperforms a general-purpose LLM on specific classification tasks.

## D4: Fine-Tuning as Platform Capability
**Decision:** Support per-customer fine-tuning of GLiNER and SLM tiers.
**Rationale:** Customers have BigQuery/GCS access → labeled data accumulates → fine-tuned models get more accurate → earlier tiers catch more → less reaches expensive tiers. Product flywheel.

## D5: Library as Standalone Service (Not Embedded in Scanner)
**Decision:** Classification library is its own product/service. Scanner is one consumer. Third-party API consumers are another.
**Rationale:** Enables reuse across scanner, prompt leak detection, DLP pipelines, CI/CD gates, and external consumers.

## D6: Dual-Mode API
**Decision:** `/classify/column` for structured data, `/classify/text` for unstructured.
**Rationale:** Structured and unstructured classification are fundamentally different. Column mode leverages metadata (name, type, stats). Text mode leverages NER spans. Same tiers, different optimizations per mode.

## D7: Stateless Library
**Decision:** Library owns no persistence. Consumers inject dictionaries, patterns, configs. Consumer persists results, feedback, events.
**Rationale:** Zero infrastructure dependencies. Pure Python package. No database driver needed. Consumers control their own data.

## D8: Latency Budget
**Decision:** Per-request `budget_ms` parameter. Adaptive scheduling using live p95 latency. Fast tiers always run; slow tiers race in parallel under budget.
**Rationale:** Prompt interception needs 50-150ms. Batch scanning has no time pressure. Same engine, different constraints per consumer.

## D9: Gemma-First Model Strategy
**Decision:** Default to Google Gemma family: EmbeddingGemma (embeddings), Gemma 3/4 (SLM). Abstract interfaces for swappability.
**Rationale:** Apache 2.0 license. Natural GCP ecosystem fit. Full size range (270M-31B). Unsloth/LoRA day-one support. But don't hard-commit — model interfaces abstracted.

## D10: Out of the Box Without Customer Data
**Decision:** Library ships curated patterns (50+ regex), column name variants (400+), GLiNER labels (60+), embedding taxonomy (80+ categories). Customer dictionaries are enhancement, not prerequisite.
**Rationale:** Must deliver value immediately. Customer data improves accuracy over time but is not required for initial classification.

## D11: Cost/Performance Profiles
**Decision:** Four profiles: Free ($0, fast tiers), Standard (+DLP +GLiNER), Advanced (+embeddings +SLM), Maximum (+LLM). Customer selects via dashboard or per-request.
**Rationale:** Different customers have different resource constraints and cost tolerance. Profile system makes this explicit and configurable.

## D12: Event-Based Observability (No Pre-Aggregation)
**Decision:** Raw structured events (JSONL) via pluggable handler. No time windows, no pre-aggregated stats in the library. Consumer does all analysis.
**Rationale:** Pre-aggregation imposes the library's analysis choices on consumers. Raw events let consumers slice by environment, run, consumer, tier, time range — however they want.

## D13: Run Lifecycle
**Decision:** Lightweight runs with start/complete events. Consumer builds summaries from event logs.
**Rationale:** Runs are an event wrapper, not a persistence construct. Library stays stateless.

## D14: GLiNER2 as Unified Model
**Decision:** Replace GLiNER with GLiNER2 (205M) as the primary model. Does NER + text classification + structured extraction in one forward pass.
**Rationale:** Single model instance for content detection + intent classification + zone segmentation. 205M parameters, CPU, pip-installable. Reduces model inventory and memory footprint.

## D15: Prompt Analysis as Separate Module
**Decision:** Prompt analysis is a separate module (`prompt_analysis/`) that depends on the classification library, not a feature within it.
**Rationale:** Different consumers need different capabilities. Scanner needs content detection only. Prompt gateway needs content + intent + zones + risk. Separation keeps the classification library general-purpose.

## D16: Content and Intent Are Separate Concerns
**Decision:** Content detection and intent classification are parallel, independent analyses. They converge only at the risk cross-correlation layer.
**Rationale:** An SSN is an SSN regardless of intent. Content detection should produce identical results whether called from scanner, prompt module, or third-party consumer. GLiNER2 runs one forward pass (implementation optimization) but outputs route to separate streams (architectural separation).

## D17: Zone Segmentation
**Decision:** Prompts are segmented into structural zones (instruction, pasted_content, code_block, data_block, context, question). Entities found in different zones carry different risk weights.
**Rationale:** ICLR 2025 research validates instruction-data separation as a fundamental problem. A question mentioning SSN concepts is very different from pasted content containing actual SSNs. Zone-weighted risk scoring is the key differentiator.

## D18: NLI Model for Intent Cross-Verification
**Decision:** Add BART-MNLI (~400M) as an NLI-based intent verifier in the prompt module.
**Rationale:** Architecturally different from GLiNER2's approach (entailment vs span-matching). Provides ensemble robustness. Fires only when GLiNER2 intent confidence is below threshold.

## D19: Incremental Build Stages
**Decision:** Each tier is independently buildable and shippable. Orchestrator works from Stage 1 with one tier.
**Rationale:** Start delivering value immediately (regex). Add capabilities over time. No big-bang release. Each stage has its own tests and acceptance criteria.

## D20: Resource Budget (Separate from Latency Budget)
**Decision:** Track both latency budget (per-request time) and resource budget (memory, CPU, API cost). Profiles encode resource constraints. Per-request budget_ms encodes latency constraints.
**Rationale:** Orthogonal constraints. A deployment can have tight latency but generous resources (prompt gateway on GPU) or relaxed latency but tight resources (scanner on shared VM).

## D21: Unified Orchestrator with Mode Flag
**Decision:** Single orchestrator with `mode=structured|unstructured|prompt` instead of separate orchestrators per pipeline.
**Rationale:** Reduces code duplication. Engine selection, budget scheduling, and event emission are identical across modes — only which engines are eligible changes. Mode flag enables/disables engines: Column Name and Heuristic Statistics only for `structured`, NLI only for `prompt`, etc. The orchestrator owns the cascade logic once.

## D22: Dual Model Default (GLiNER2 + PII Base)
**Decision:** Load both GLiNER2 (205M) and the PII-specialized model (`gliner-pii-base-v1.0`, ~500M) by default in Standard+ profiles. GLiNER2 handles intent classification and zone extraction. PII base handles NER for content detection.
**Rationale:** PII base has higher NER accuracy (81% F1) for entity detection — the most critical task for content classification. GLiNER2's multi-task capability is needed for intent and zones but its NER accuracy is lower than the specialized model. Loading both costs ~700MB combined but gives best-of-both: specialized NER accuracy + multi-task flexibility.

## D23: Structural Content Classifier as ML Model (Multi-Model Benchmark)
**Decision:** Train multiple candidates (XGBoost, LightGBM, CatBoost, Random Forest) on 40 engineered features. Benchmark all with Optuna hyperparameter search. Select winner by weighted F1. Export as decision rules for zero-dependency deployment. Framework: scikit-learn + Optuna.
**Rationale:** Hand-tuning weights for 40 features across 7 classes is error-prone. ML finds optimal decision boundaries. Tree models handle feature interactions that linear weights miss. Multi-model benchmarking avoids premature commitment to one algorithm — data determines the winner. Decision rule export means no ML runtime in production.

## D24: Boundary Detection via Sliding Window
**Decision:** Detect content-type boundaries by running the structural classifier on overlapping N-line windows. Boundary = classification change between adjacent windows.
**Rationale:** Reuses the structural classifier. Window-based approach naturally smooths single-line noise. Simpler than a separate sequence model.

## D25: Structured Secret Scanner as Deterministic Engine with ML-Optimized Parameters
**Decision:** Secret detection runtime is always deterministic: parse → extract key-value → score via dictionary + entropy + anti-indicators. No ML model at inference time. However, the scoring parameters (dictionary weights, entropy thresholds, anti-indicator adjustments, structure-type boosts, feature interaction weights) are optimized offline via ML training (XGBoost on ~15-20 features extracted from labeled secret datasets like StarPii's 20,961 annotated secrets). ML output = optimized parameter values baked into the deterministic code.
**Rationale:** Runtime remains interpretable, fast (<5ms), and zero-dependency. ML finds optimal decision boundaries that hand-tuning misses — especially for borderline cases, feature interactions (key-name × structure-type × entropy), and novel key-name patterns. Same pattern as D26: ship hand-tuned first, ML-optimize the parameters later.

## D26: Start with Heuristics, Replace with ML
**Decision:** Ship structural detection and boundary detection with hand-tuned heuristics first. Train ML replacements offline. Keep heuristics as fallback.
**Rationale:** Delivers value immediately. ML accuracy comes later without blocking initial release.

## D27: Neural Feature Discovery Using Four Architecture Families (Proposed)
**Decision:** Evaluate CNN, RNN, Attention, and SSM architectures for learning features that complement engineered features. Phase 2 research — not blocking Phase 1 tree model.
**Rationale:** Engineered features capture known patterns. Neural models can discover patterns we didn't think of (e.g., CNNs discovering character n-grams that distinguish code from prose).

## D28: CNN+Attention Hybrid as Primary Architecture Candidate (Proposed)
**Decision:** CNN for local pattern discovery + Attention for cross-region relationships is the leading architectural hypothesis.
**Rationale:** CNN captures local patterns (keyword sequences, bracket patterns). Attention captures long-range dependencies (opening brace on line 1 relates to closing brace on line 50). RNN/SSM are sequential alternatives for boundary detection specifically.

## D29: ModernBERT as Primary Pre-Trained Candidate (Proposed)
**Decision:** ModernBERT-base as primary pre-trained model to evaluate; StarEncoder as code-specific backup. Distillation to lightweight student model for deployment.
**Rationale:** ModernBERT (December 2024) outperforms older BERT variants, handles 8K tokens, Apache 2.0. StarEncoder is trained specifically on code. Both are worth probing before training from scratch.

## D30: Pre-Trained Model Exploration as Phase 3 (Proposed)
**Decision:** Don't skip pre-trained model evaluation — ModernBERT and StarEncoder are too promising. But run after Phase 2 neural feature discovery.
**Rationale:** Pre-trained models may already know code vs. prose distinction from training data. Probing + distillation is cheaper than training from scratch if it works.

## D31: ONNX Runtime for Neural Deployment If Needed (Proposed)
**Decision:** If neural models significantly beat expanded tree models, deploy via ONNX Runtime (~30MB, C++ inference, no PyTorch).
**Rationale:** Classification library consumers shouldn't need PyTorch. ONNX Runtime adds ~30MB but provides fast inference without the full ML stack.

## D32: SSM Exploration Conditional on Phase 2 RNN Results (Proposed)
**Decision:** SSM/Mamba deep dive only if Phase 2 shows sequential models outperform attention for boundary detection.
**Rationale:** SSMs are theoretically ideal for boundary detection (state transitions = boundaries) but the tooling is immature (Mamba released Dec 2023, CodeSSM at EMNLP 2025). Track but don't invest until proven necessary.

## D33: Concurrency Strategy — Workers First, Compile Later (Decided)
**Decision:** Scale throughput with multiple uvicorn workers (Phase 1). Vectorize feature extraction with numpy for batch endpoints (Phase 2). Compile feature extraction with Cython for high-concurrency gateways (Phase 3). Rust/PyO3 only if Cython is insufficient. Most deployments never need Phase 2+.
**Rationale:** Multiple workers solve the GIL problem without code changes. Each subsequent phase increases complexity — only invest when measured throughput proves it necessary. The classification library is stateless, so worker scaling is linear.

## D34: Google RE2 for Regex Engine (Decided)
**Decision:** Use Google RE2 (`google-re2` Python package) instead of Python's `re` module. Two-phase matching: RE2 Set compiles all 50+ patterns into a single automaton for one-pass screening (C++, releases GIL), then extract positions only for matched patterns. Secondary validators (Luhn, format checks) run post-match. Intel Hyperscan as future option if >10K req/s needed.
**Rationale:** Three requirements met simultaneously: (1) Security — linear-time guarantee prevents ReDoS attacks on prompt gateway. (2) Performance — single-pass matching vs 50 separate scans. (3) Concurrency — C++ backend releases GIL, enabling true multi-threaded parallelism. Python `re` fails all three.
