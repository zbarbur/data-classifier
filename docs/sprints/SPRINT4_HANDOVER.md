# Sprint 4 Handover — Benchmarks, Collisions & ML Prep

> **Date:** 2026-04-11
> **Theme:** Iteration 2 closure — benchmark methodology, real-world corpora, collision resolution, model registry
> **Branch:** sprint4/main (6 commits, 3 parallel worktree streams)

## Delivered

### Stream A: Collision Resolution + AWS Pattern (5 items)

#### Three-way SSN/ABA/SIN Collision Resolution
- `_resolve_three_way_collisions()` runs before pairwise resolution
- Priority: column name engine signal → heuristic (cardinality) → confidence gap
- Eliminates the most common FP in synthetic benchmarks

#### NPI vs PHONE Collision Resolution
- Column name keywords (npi, provider, prescriber) → NPI wins
- NPI validator confirmation → NPI wins
- Default: PHONE wins (far more common in real data)

#### DEA vs IBAN Collision Resolution
- Sample length analysis (<=10 chars → DEA, >=15 chars → IBAN)
- Validator confirmation as secondary signal
- Column name keywords as tiebreaker

#### Collision Pair Unit Tests
- `tests/test_collision_resolution.py` — 49 tests across 7 test classes
- Parameterized tests for all 5 pairwise collision pairs
- Three-way SSN/ABA/SIN, NPI/PHONE, DEA/IBAN dedicated tests
- Edge cases: equal confidence, threshold boundaries

#### AWS Secret Key Pattern Redesign
- Base confidence lowered to 0.35 (below min_confidence threshold)
- Only surfaces when context-boosted by AWS-specific keywords
- Prevents FPs on git SHAs, checksums, random base64

### Stream B: Benchmark Overhaul + Corpus (5 items)

#### Benchmark Methodology
- **Macro F1**: average of per-entity F1 (weights all types equally)
- **Micro F1**: aggregate TP/FP/FN (dominated by frequent types)
- **Primary-label accuracy**: is the top-1 prediction correct?
- `BenchmarkResult` dataclass encapsulating all metrics
- `docs/BENCHMARK_METHODOLOGY.md` documenting definitions and interpretation

#### Benchmark Reporting
- Unified report includes macro F1, primary-label, per-entity breakdown
- `--corpus` flag for corpus selection (synthetic/ai4privacy/nemotron/all)
- Secret benchmark integrated into unified report

#### Real-World PII Corpus Integration
- `tests/benchmarks/corpus_loader.py` — loader for Ai4Privacy, Nemotron, synthetic
- Entity type mappings verified against actual dataset labels
- `scripts/download_corpora.py` — downloads from HuggingFace and GitHub
- **Ai4Privacy**: 438,960 records, 8 entity types (29.7 MB)
- **Nemotron**: 155,341 records, 13 entity types (11.5 MB)

#### External Secret Corpora
- **SecretBench**: 1,068 real annotated samples (516 TP, 552 TN) from brendtmcfeeley/SecretBench
- **Gitleaks**: 171 real test fixtures (30 TP, 141 TN) extracted from Go rule files
- Fixed `is_secret` field mapping in secret benchmark loader
- `docs/research/SECRET_CORPORA_RESEARCH.md` documenting all 5 corpus sources

#### Research: External Corpora
- Documented Ai4Privacy, Nemotron-PII, SecretBench, gitleaks, detect-secrets
- License, size, format, entity type coverage, ETL instructions for each
- Download script handles all sources with verified label mappings

### Stream C: Model Registry + Lazy Loading (1 item)

#### ModelRegistry Infrastructure
- `data_classifier/registry/` — new module
- `ModelRegistry` class: register, get (lazy load), is_loaded, unload, check_dependencies
- Thread-safe per-entry locks for concurrent access
- `ModelDependencyError` with clear install instructions
- Module-level convenience functions: `register_model()`, `get_model()`, `check_model_deps()`
- 20 tests, all using mock models (no ML deps required)

#### Engine Interface Extension
- `classify_batch()` added to `ClassificationEngine` base class
- Default implementation loops over `classify_column()`
- ML engines will override for GPU-efficient batching

#### Optional ML Dependencies
- `[ml]` extra in pyproject.toml: torch, transformers, tokenizers
- `pip install data_classifier[ml]` for ML engine support

### Infrastructure
- CI docs build check: `mkdocs build --strict` on Python 3.12
- Implementation plans in `docs/plans/` for all 3 streams

## Benchmark Results (Sprint 4 Final)

### Synthetic Corpus (1,850 samples, 37 columns)

| Metric | Sprint 3 | Sprint 4 | Change |
|---|---|---|---|
| Macro F1 | — | **0.930** | NEW |
| Micro F1 | 0.897 | **0.945** | +5.3% |
| Primary-Label | — | **96.3%** | NEW |
| Precision | 0.839 | **0.929** | +10.7% |
| Recall | 0.963 | 0.963 | same |
| TP / FP / FN | 26 / 5 / 1 | 26 / **2** / 1 | -3 FP |

### Real-World Corpora (NEW — honest baselines)

| Metric | Ai4Privacy (366K samples) | Nemotron (155K samples) |
|---|---|---|
| Macro F1 | **0.390** | **0.672** |
| Micro F1 | **0.179** | **0.464** |
| Primary-Label | **75.0%** | **100%** |
| Precision | 0.102 | 0.302 |
| Recall | 0.750 | 1.000 |
| FPs | 53 | 30 |

### Secret Detection (1,347 samples, 4 sources)

| Source | Total | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|---|
| builtin | 102 | 33 | 0 | 1 | 1.000 | 0.971 |
| detect-secrets | 8 | 5 | 0 | 2 | 1.000 | 0.714 |
| gitleaks | 170 | 12 | 37 | 17 | 0.245 | 0.414 |
| SecretBench | 1,067 | 128 | 263 | 388 | 0.327 | 0.248 |
| **Overall** | **1,347** | **178** | **300** | **408** | **0.372** | **0.304** |

### Key Findings from Real Corpora

1. **Synthetic data is misleading**: F1 0.945 (synthetic) vs 0.179-0.464 (real). Real data has messier formats, cross-pattern collisions, and international variants.
2. **Recall is strong, precision is the problem**: The engine detects the right type but also fires on too many wrong types. Secondary predictions are noise.
3. **SSN pattern fires everywhere**: Any column with 9-digit numbers triggers SSN. Root cause: regex has no contextual gating.
4. **HEALTH category ghost FPs**: HEALTH pattern matches broadly on 4-8 real-world columns. Needs pattern audit.
5. **CREDENTIAL and PHONE missed at scale**: Real passwords and international phone formats don't match our regex patterns (0% sample match on Ai4Privacy).
6. **Primary-label accuracy is the right metric**: Top-1 prediction is correct on Nemotron (100%) and usually correct on Ai4Privacy (75%). The multi-label FP noise inflates error counts.
7. **SecretBench exposes Layer 3 gaps**: 75% FN rate — secrets in code contexts, connection strings, obfuscated values that our parsers don't handle.
8. **Gitleaks FPs**: 37 false positives from crafted FP test cases — missing placeholder suppressions.

## Tests

| Suite | Tests | What |
|---|---|---|
| test_collision_resolution.py | 49 | All collision pairs, three-way, edge cases |
| test_model_registry.py | 20 | Registry, lazy loading, deps, batch, threads |
| test_patterns.py | 295+ | Pattern compilation + AWS redesign |
| test_column_name_engine.py | 78+ | Fuzzy matching + compound table matching |
| test_heuristic_engine.py | 42+ | Signal functions + SSN/ABA detection |
| test_secret_scanner.py | 70+ | Parsers + scoring + tiers + integration |
| test_regex_engine.py | 33+ | Engine behavior, validators |
| test_golden_fixtures.py | 31 | BQ compat contract |
| test_hypothesis.py | 4 | Property-based |
| test_python_api.py | 57+ | API contract |
| **Total** | **679** | **1.28s** |

## Decisions Made

1. **Three parallel worktree streams**: Collisions (A), Benchmarks (B), Model Registry (C) developed simultaneously with zero merge conflicts. Proves the architecture is modular.
2. **Real corpora over synthetic**: Faker data gave flattering results. Real-world Ai4Privacy and Nemotron data exposed the true precision problem. This is the honest baseline for ML engine work.
3. **No generated fallbacks**: If a corpus download fails, we skip it — generating fake data defeats the purpose of external validation.
4. **AWS pattern confidence gating**: Rather than removing the pattern, lowered base confidence below threshold. Context-boosted when AWS keywords present. Clean design for context-dependent detection.
5. **Model registry before ML engines**: Infrastructure first. Sprint 5 can focus on engines without building plumbing.
6. **`classify_batch()` as non-breaking addition**: Default loops over `classify_column()`. Existing engines unchanged. ML engines override for efficiency.

## Open Threads (Carry to Sprint 5)

### 1. Engine Priority Weighting (CRITICAL)
Column name engine is more reliable than regex but regex has higher confidence. When they disagree, regex wins — causing most real-world FPs. Need orchestrator-level weighting: column name authoritative when it matches.

### 2. Primary-Label Mode
Users see top-1 prediction. Secondary findings are implementation detail. Add `max_findings=1` or confidence-gap suppression to eliminate secondary noise.

### 3. Confidence Calibration
Regex confidence 0.94 beats column name 0.90 even though column name is more reliable. Before adding ML engines (third confidence scale), need unified calibration framework.

### 4. HEALTH Pattern Ghost FPs
HEALTH category pattern matches on 4-8 non-health columns in real data. Quick investigation needed.

### 5. GL iNER2 Integration
Model registry is ready. First ML engine should dramatically improve PERSON_NAME, ADDRESS detection (currently column-name-only) and provide context-aware disambiguation.

### 6. SecretBench Analysis
388 missed secrets need categorization: pattern gaps, parser gaps, format issues. Informs Layer 3 structural parser priorities.

### 7. Real-Corpus Baseline Report
Document Sprint 4 real-corpus results formally as the baseline for measuring ML engine impact.

## Sprint 5 Plan

### Theme: Precision Fix — Engine Weighting, Sibling Analysis & ML Prep

The real-world corpus results revealed that precision is the bottleneck (0.10-0.30 on real data). Sprint 5 has two architectural fixes that should make the biggest impact before ML engines are added.

### Strategic Rationale

1. **Engine priority weighting + sibling analysis** are the two biggest levers for structured data precision — no ML needed
2. **Quick fixes** (HEALTH, MAC/DEVICE_ID, SSN gating) eliminate known FP categories
3. **Confidence calibration** prepares the orchestrator for multi-engine scoring (ML engines in Sprint 6)
4. **GLiNER2** starts Iteration 3 — first ML engine, targets PERSON_NAME and ADDRESS (currently column-name-only)
5. **Users see top-1 prediction** — primary-label mode aligns the API with how connectors consume results

### Parallel Streams (suggested)

**Stream A: Orchestrator Precision** (items 1-2, both modify orchestrator)
- Engine priority weighting: column name engine authoritative when it matches
- Sibling column analysis: two-pass classification, table profile from high-confidence siblings
- These must be sequential (both modify orchestrator), but together they're the sprint's biggest win

**Stream B: Quick Fixes + Calibration** (items 3-7, independent of Stream A)
- HEALTH pattern audit, MAC/DEVICE_ID fix, SSN gating — all small, parallel
- Primary-label mode — orchestrator change but independent of Stream A
- Confidence calibration — broader orchestrator change

**Stream C: ML + Research** (items 8-10, independent)
- GLiNER2 engine integration using model registry from Sprint 4
- SecretBench FN analysis — research task
- Baseline report documentation

### Recommended Scope

| # | Item | Pri | Size | Stream | Why |
|---|------|-----|------|--------|-----|
| 1 | Engine priority weighting | P1 | M | A | Root cause of most FPs — biggest single lever |
| 2 | Sibling column analysis | P1 | M | A | Table-level disambiguation — strongest structured data signal |
| 3 | Primary-label mode | P1 | S | B | Instant user-facing improvement |
| 4 | HEALTH pattern audit | P1 | S | B | Quick fix, eliminates a whole FP category |
| 5 | MAC/DEVICE_ID column name fix | P1 | S | B | Quick fix |
| 6 | Confidence calibration | P1 | M | B | Foundation for multi-engine scoring |
| 7 | SSN confidence gating | P1 | S | B | Reduces SSN overfiring |
| 8 | GLiNER2 engine | P1 | L | C | First ML engine — Iteration 3 starts |
| 9 | SecretBench FN analysis | P1 | S | C | Research for Layer 3 |
| 10 | Real-corpus baseline report | P1 | S | C | Document honest numbers |

### Success Criteria

- Real-world primary-label accuracy > 95% on both Ai4Privacy and Nemotron
- Micro F1 on Nemotron > 0.70 (from 0.464)
- GLiNER2 detects PERSON_NAME and ADDRESS from sample values (not just column name)
- All benchmarks re-run with `python3 -m tests.benchmarks.generate_report --sprint 5`

### Key Context for Sprint 5

- **Model registry is ready** — `data_classifier/registry/` with lazy loading, thread safety, `classify_batch()`
- **Real corpora are downloaded** — 595K records across 4 sources in `tests/fixtures/corpora/`
- **Benchmark tooling is complete** — macro F1, primary-label, per-entity breakdown, HTML reports
- **Download script** — `python3 scripts/download_corpora.py` to refresh corpora
- **BQ connector coordination** happening in parallel outside sprint scope

## Commits

| # | Hash | Description |
|---|---|---|
| 1 | 0307cf3 | chore: start Sprint 4 — Benchmarks, Collisions & ML Prep |
| 2 | 9726d67 | feat: add model registry infrastructure for ML engine integration |
| 3 | 76d8a9f | feat: collision resolution — three-way SSN/ABA/SIN, NPI/PHONE, DEA/IBAN, AWS pattern redesign |
| 4 | a374e3a | feat: Sprint 4 Stream B — benchmark methodology, reporting, and corpus integration |
| 5 | 68ff8ec | feat: real-world corpora, download script, CI docs check, benchmark fixes |
| 6 | d1e4164 | fix: code review — keyword word-boundary, registry thread safety, metric accuracy |
| 7 | 73ff202 | feat: HTML benchmark report + Sprint 4 benchmark baseline |
| 8 | 5995b8f | chore: bump sibling column analysis to P1 Sprint 5 |
