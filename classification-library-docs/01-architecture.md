# Classification Library — Architecture

## Overview

The Classification Library is a general-purpose, API-first ecosystem for detecting and classifying sensitive data. It consists of two modules that share infrastructure but serve different analysis needs:

**Classification Library** — Tiered content detection engine. Detects PII, PHI, PCI, credentials, and sensitive topics in both structured data (database columns) and unstructured text. Consumed by data platform scanners, DLP pipelines, CI/CD gates, and third-party integrations.

**Prompt Analysis Module** — Analyzes prompts sent to public LLMs (ChatGPT, Copilot, Claude, Gemini) for data leakage risk. Performs three independent analyses — zone segmentation, intent classification, and content detection (delegated to the classification library) — and converges them at a risk cross-correlation layer.

Both modules run as a stateless service or embedded Python package.

## Core Design Principles

**Stateless compute.** The library owns no persistence. Consumers provide configuration (dictionaries, custom patterns, model paths) at initialization or per-request, and persist results, events, and feedback on their side.

**Dual-mode classification.** Two distinct content entry points: column mode (`/classify/column`) for structured data with metadata and sample values, text mode (`/classify/text`) for unstructured content. The prompt module adds a third entry point (`/analyze/prompt`) that combines content detection with zone segmentation, intent classification, and risk assessment.

**Tiered cascade.** A unified orchestrator with mode flag (`structured|unstructured|prompt`) controls engine selection. Cheap, fast engines (regex, heuristics) execute first. Expensive engines (SLM, LLM) only fire if earlier engines didn't classify. The mode flag enables/disables engines per pipeline — Column Name and Heuristic Statistics only for `structured`, NLI only for `prompt`. One orchestrator, one cascade logic, three behaviors.

**Budget-aware execution.** Two budget types. Latency budget: per-request `budget_ms` triggers adaptive parallel execution using live p95 latency. Resource budget: profiles control memory, CPU, and API cost. Both are consumer-configurable.

**Separation of concerns.** Content detection and intent classification are parallel, independent analyses. An SSN is an SSN regardless of intent. They converge only at the prompt module's risk layer — the single point where content, intent, and zones combine into a risk score.

**Works out of the box.** Ships with curated regex patterns (50+), column name variants (400+), GLiNER2 entity labels (60+), pre-computed embedding taxonomies (80+ categories), and intent labels (10 structural intents). No customer data required.

## System Architecture

![System Architecture](diagrams/01_system_architecture.png)

## Deployment Modes

| Mode | Description | Latency | Use Case |
|------|------------|---------|----------|
| **Embedded** | Import as Python package, runs in-process | Lowest | Scanner images, tight coupling |
| **Sidecar** | Co-deployed container, localhost HTTP | Low | Scanner + local consumers |
| **Standalone** | Independent service, network HTTP | Medium | Multi-consumer, shared infra |
| **Serverless** | Cloud Run / Lambda, per-request | Variable | Burst workloads, pay-per-use |

## Engine Stack

Engines grouped by speed class. The unified orchestrator enables/disables engines per mode (structured | unstructured | prompt).

| Speed Class | Engine | Latency | Modes |
|-------------|--------|---------|-------|
| **Fast** (always run) | Structural Content Classifier (ML-trained) | <1ms | All — identifies code/config/query/log/CLI/markup |
| | Boundary Detector (sliding window) | <2ms | All — finds content-type transitions in mixed text |
| | Column Name Semantics | <1ms | Structured only |
| | Regex Patterns (PII + known-format secrets) | <1ms | All |
| | Structured Secret Scanner (parse → key-name + entropy) | <5ms | All — secrets in JSON/YAML/env/code/SQL/CLI |
| | Heuristic Statistics | <1ms | Structured only |
| | Financial Density Scorer | <1ms | All — currency + percentage + financial term density |
| | Dictionary Lookup | <1ms | All |
| **Slow** (parallel) | Cloud DLP | 50-200ms | All |
| | PII Base NER (~500M) | 10-30ms | All — entity detection (names, medical, addresses) |
| | GLiNER2 (205M) | 10-30ms | Prompt — intent classification + zone extraction |
| | EmbeddingGemma (308M) | 5-20ms | All — topic sensitivity + intent similarity |
| | NLI / BART-MNLI (400M) | 10-30ms | Prompt only — intent cross-verification |
| **Heavy** (optional) | SLM / Gemma (3-4B) | 50-200ms | All — reasoning for ambiguous cases |
| | LLM API | 200ms+ | Fallback |

The Structural Classifier ships as heuristics first, then is replaced by ML-trained decision rules from an offline training pipeline (XGBoost on 40 engineered features → exported as Python if/else). See doc 09 for full spec.

## Prompt Analysis Tiers

Zone segmentation and intent classification each have their own tiered cascades:

| Analysis | Tiers | Latency |
|----------|-------|---------|
| **Zone segmentation** | Heuristic boundaries → GLiNER2 extraction → SLM reasoning | 1ms → 20ms → 200ms |
| **Intent classification** | Keywords → GLiNER2 → Embeddings → NLI → SLM → LLM | 1ms → 20ms → 15ms → 30ms → 200ms → 500ms+ |
| **Risk cross-correlation** | Content × intent × zones → weighted score | <1ms |

## Cost / Performance Profiles

| Profile | Active Engines | API Cost | Memory |
|---------|---------------|----------|--------|
| **Free** | Regex, Column Name, Heuristics, Dictionaries | $0 | <256 MB |
| **Standard** | Free + Cloud DLP + PII Base (NER) + GLiNER2 (intent/zones) | Low (DLP) | ~1.2 GB |
| **Advanced** | Standard + Embeddings + SLM | Low (DLP) | ~4-5 GB |
| **Maximum** | Advanced + NLI + LLM fallback | Medium (DLP + LLM) | ~5-6 GB |

All profiles run on CPU. GPU is optional.

## Observability

Structured JSONL events via pluggable handler for every operation. No pre-aggregation — consumers persist and analyze. Event types: `TierEvent`, `ClassificationEvent`, `FeedbackEvent`, `RunEvent`, `PromptAnalysisEvent`, `ZoneSegmentationEvent`, `IntentClassificationEvent`.

In-memory latency tracker powers runtime budget decisions. `GET /stats` exposes live engine latency.

## Technology Choices

| Component | Default Model | Parameters | Role |
|-----------|-------------|-----------|------|
| PII NER (content detection) | GLiNER PII base | ~500M | Primary NER for entity detection — 81% F1 on PII benchmarks |
| Intent + zones (prompt module) | GLiNER2 | 205M | Text classification + structured extraction for intent/zones |
| Embeddings | EmbeddingGemma | 308M | Semantic similarity, 100+ languages, Matryoshka dimensions |
| NLI verification | BART-MNLI | ~400M | Entailment-based intent cross-check (prompt mode) |
| SLM | Gemma 3 4B-IT | 4B (2GB quantized) | Reasoning for content + intent + zones |
| LLM fallback | Gemini Flash API | — | Cheapest capable, GCP ecosystem |
| Cloud DLP | Google Cloud DLP | — | 150+ InfoTypes, native BigQuery integration |

**Dual model strategy:** Both PII base and GLiNER2 load by default in Standard+ profiles. PII base handles entity detection (highest NER accuracy). GLiNER2 handles intent classification and zone extraction (multi-task capability). Combined ~700MB. Model interfaces are abstracted — consumers can substitute any compatible model.
