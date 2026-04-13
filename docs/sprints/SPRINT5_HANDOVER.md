# Sprint 5 Handover — Precision Fix, ML Engine & Production Deployment

> **NOTE (2026-04-13):** This document cites F1 numbers measured against the `ai4privacy/pii-masking-300k` corpus, which has since been retired due to license non-compatibility. Historical numbers are preserved as records of what was measured at the time. See `docs/process/LICENSE_AUDIT.md` for context.

> **Date:** 2026-04-12
> **Theme:** Engine weighting, sibling analysis, first ML engine (GLiNER2), ONNX deployment
> **Branch:** sprint5/main → merged to main
> **Release:** v0.5.0 → v0.5.1 → v0.5.2 (patched during integration)

## Delivered

### Stream A: Orchestrator Precision

#### Engine Priority Weighting
- Authority system on `ClassificationEngine` base class
- Column name engine = 10, regex = 5, others = 1
- Conflict resolution: higher-authority suppresses lower when gap ≥ 3
- Agreement boost: +0.05 when engines agree on entity type
- `_apply_engine_weighting()` in orchestrator
- 17 tests in `test_engine_weighting.py`

#### Sibling Column Analysis
- Two-pass classification via `classify_columns()` on orchestrator
- Pass 1: independent per-column classification
- Pass 2: infer table domain from high-confidence siblings, adjust ambiguous columns
- `table_profile.py` with healthcare/financial/customer_pii domain inference
- Domain-specific boosts/suppressions (e.g., healthcare boosts NPI, suppresses ABA)
- 29 tests in `test_sibling_analysis.py`
- Backward compatible — single-column calls skip Pass 2

### Stream B: Quick Fixes + Calibration

#### Primary-Label Mode
- `max_findings` parameter in `classify_columns()`
- `confidence_gap_threshold` (default 0.30) suppresses noisy secondary findings
- `_apply_findings_limit()` helper
- 10 tests in `test_primary_label.py`

#### HEALTH Pattern Audit
- Root cause: ICD-10 regex `[A-TV-Z]\d{2}\.?\d{0,4}` matched any letter+2 digits
- Fix: require decimal portion `\b[A-TV-Z]\d{2}\.\d{1,4}\b`
- Lowered base confidence to 0.30, added context boost/suppress words

#### DEVICE_ID / MAC_ADDRESS Fix
- MAC keywords duplicated in both entity types; DEVICE_ID won by load order
- Removed 6 MAC-related variants from DEVICE_ID
- 9 regression tests in `test_column_name_engine.py`

#### SSN Confidence Gating
- Verified Sprint 4 already handled this — `us_ssn_no_dashes` at 0.40 (below threshold)
- Added 5 documentation tests

#### Confidence Calibration
- New `data_classifier/orchestrator/calibration.py`
- Per-engine calibration functions: regex, column_name, heuristic, secret_scanner, gliner2
- Applied in orchestrator before merging findings
- `engine_id` property on `ClassificationEngine` base class
- 16 tests in `test_calibration.py`

### Stream C: ML Engine + Deployment

#### GLiNER2 NER Engine
- `data_classifier/engines/gliner_engine.py` — first ML engine
- Model: `urchade/gliner_multi_pii-v1` (205M params, PII-tuned)
- 8 entity types: PERSON_NAME, ADDRESS, ORGANIZATION, DATE_OF_BIRTH, PHONE, SSN, EMAIL, IP_ADDRESS
- Label optimization tested against real corpora — "person" beats "person name", "street address" beats "physical address", "national identification number" beats "social security number"
- Entity descriptions stored in `ENTITY_LABEL_DESCRIPTIONS` dict for future GLiNER2 v2 migration
- Specificity deduplication (ADDRESS suppresses PERSON_NAME when both match)
- ML suppression in orchestrator when non-ML engine has high-confidence match (>0.85)
- Multi-model support via `model_id` parameter (v1 or v2, auto-detected)
- 29 mock-based tests in `test_gliner_engine.py`

#### ONNX Deployment Mode
- Three deployment tiers:
  - **Light** (`pip install data_classifier`): regex + column name + heuristic only (~5MB)
  - **Standard** (`pip install data_classifier[ml]`): + GLiNER2 ONNX (~70MB + 350MB model)
  - **Full** (`pip install data_classifier[ml-full]`): + torch + export tools (~2.5GB)
- `scripts/export_onnx_model.py` — one-time export, reusable across deploys
- `data_classifier/export_onnx.py` — module entry point: `python -m data_classifier.export_onnx`
- Quantized INT8 ONNX model (~350MB vs 1.1GB full precision)
- Identical accuracy vs PyTorch (verified)
- 4x faster model load (3.4s vs 14s)

#### Zero-Config Auto-Discovery
- `_find_bundled_onnx_model()` searches:
  1. `{package_dir}/models/gliner_onnx/` — bundled location
  2. `~/.cache/data_classifier/models/gliner_onnx/` — user cache
  3. `/var/cache/data_classifier/models/gliner_onnx/` — system cache
- `_build_default_engines()` reads env vars:
  - `GLINER_ONNX_PATH` — explicit override
  - `GLINER_API_KEY` — API fallback
  - `DATA_CLASSIFIER_DISABLE_ML` — skip ML entirely
- Narrowed `except Exception` to `except ImportError` to avoid swallowing real errors

### Infrastructure & Tooling

#### Consolidated Benchmark Report
- New `tests/benchmarks/consolidated_report.py`
- Runs all 4 configurations in one invocation (Nemotron × Ai4Privacy × named × blind)
- Single HTML output with executive summary, per-entity matrix, delta analysis, failure breakdown
- `python -m tests.benchmarks.consolidated_report --sprint 5`

#### Quick Performance Benchmark
- New `tests/benchmarks/perf_quick.py` — ~25s runtime
- Warm environment by default (cold start is one-time, amortized)
- Reports: total p50/p95, per-column p50, throughput, per-engine contribution
- Skips scaling sweeps, input variation, length linearity
- Deep perf still available at `tests.benchmarks.perf_benchmark`

#### Blind Mode for Accuracy Benchmarks
- `--blind` flag on accuracy_benchmark and corpus_loader
- Replaces descriptive column names with `col_0`, `col_1`, ... to test value-only detection
- Essential for measuring ML engine impact honestly

### Client Integration (BQ)

#### Packaging Bug Fix (Critical)
- `engine_defaults.yaml` was not in `package-data` — heuristic + secret_scanner engines silently failed at runtime
- Added `config/*.yaml` and `models/gliner_onnx/*` globs to pyproject.toml

#### CLIENT_INTEGRATION_GUIDE.md Updated
- v0.5.0 → v0.5.2 version bumps
- Installation tiers table with size/latency/what-you-get
- Zero-config workflow as the recommended path
- Env var override and explicit injection as alternatives
- Private repo install options (Git SSH, token, local path, private PyPI)
- New classify_columns parameters (max_findings, confidence_gap_threshold)
- Engine cascade appendix with all 5 engines
- Version history v0.1.0 through v0.5.2

#### BQ Integration Verified
- Clean install tested in fresh venv — works end-to-end
- All 5 engines load correctly (including heuristic + secret_scanner that were broken)
- GLiNER2 detects PERSON_NAME, ADDRESS, ORGANIZATION from free-text "description" columns
- BQ team integrated in track3-classification worktree

## Benchmark Results (Sprint 5 Final, v0.5.2)

### Accuracy — Consolidated (50 samples, warm env)

| Corpus | Mode | Macro F1 | Micro F1 | Primary-Label | TP / FP / FN |
|---|---|---|---|---|---|
| Nemotron | named | **1.000** | 1.000 | **100%** | 13 / 0 / 0 |
| Nemotron | **blind** | **0.872** | 0.857 | **92.3%** | 12 / 3 / 1 |
| Ai4Privacy | named | **1.000** | 1.000 | **100%** | 8 / 0 / 0 |
| Ai4Privacy | **blind** | **0.667** | 0.750 | **75.0%** | 6 / 2 / 2 |

**Blind aggregate** (21 entity observations): Precision 0.783, Recall 0.857, F1 0.818, Macro 0.770

### Performance — Quick Perf (10 cols × 50 samples, warm)

| Metric | Value | Note |
|---|---|---|
| Total pipeline p50 | 2.07s | 10 columns |
| Total pipeline p95 | 2.21s | stable |
| Per column p50 | **207ms** | GLiNER-dominated |
| Per sample p50 | 4.1ms | |
| Throughput | **5 col/s, 242 samples/s** | with ML |

### Per-Engine Breakdown

| Engine | Time | Calls | Avg | % |
|---|---|---|---|---|
| **gliner2** | **2037ms** | 10 | **204ms** | **99.3%** |
| secret_scanner | 12.1ms | 10 | 1.21ms | 0.6% |
| regex | 1.5ms | 10 | 0.15ms | 0.1% |
| heuristic_stats | 0.2ms | 10 | 0.02ms | 0.0% |
| column_name | 0.2ms | 10 | 0.02ms | 0.0% |

GLiNER2 is 99.3% of pipeline time. Everything else combined: ~1% (14ms for all 4 non-ML engines).

## Sprint 4 → Sprint 5 Comparison (Blind Mode)

| Corpus | Metric | Sprint 4 | Sprint 5 | Change |
|---|---|---|---|---|
| Nemotron | Macro F1 | 0.672 | **0.872** | +30% |
| Nemotron | Precision | 0.302 | **0.800** | +165% |
| Nemotron | FPs | 30 | **3** | -90% |
| Ai4Privacy | Macro F1 | 0.390 | **0.667** | +71% |
| Ai4Privacy | Precision | 0.102 | **0.750** | +635% |
| Ai4Privacy | FPs | 53 | **2** | -96% |

**Note:** Sprint 4 claimed 100% Primary-Label on Nemotron but that was measured with named columns. Sprint 5's blind mode is a new, honest baseline.

## Tests

| Suite | Sprint 4 | Sprint 5 | Delta |
|---|---|---|---|
| test_calibration.py | — | 16 | NEW |
| test_engine_weighting.py | — | 17 | NEW |
| test_gliner_engine.py | — | 29 | NEW |
| test_primary_label.py | — | 10 | NEW |
| test_sibling_analysis.py | — | 29 | NEW |
| test_column_name_engine.py | 78 | 87 | +9 |
| test_patterns.py | 295+ | 305+ | +10 |
| test_model_registry.py | 20 | 20 | same |
| test_collision_resolution.py | 49 | 26 | -23 (removed dead resolvers) |
| test_secret_scanner.py | 70 | 70 | same |
| test_golden_fixtures.py | 31 | 31 | same |
| Other | — | — | — |
| **Total** | **681** | **777** | **+96** |

**CI: 777 passed in 1.46s. Lint clean.**

## Decisions Made

1. **GLiNER v1 PII-specific > GLiNER2 v2 general.** Tested `fastino/gliner2-base-v1` — it dominated on partial addresses (descriptions helped) but lost on PII-specific detection (classified person names as addresses). Kept `urchade/gliner_multi_pii-v1` as default. Multi-model support allows BQ to switch later.

2. **ONNX as the production deployment.** 350MB quantized model, 3.4s load, identical accuracy vs PyTorch. Zero runtime HuggingFace downloads. Eliminates torch dependency in production (though gliner package still imports torch at module level — full torch-free mode is a Sprint 6 item).

3. **Engine authority weighting replaces specific collision resolvers.** The Sprint 4 `_resolve_three_way_collisions`, `_resolve_npi_phone`, `_resolve_dea_iban` methods were removed from the pipeline in favor of generic authority-based conflict resolution. This is cleaner architecturally but loses some domain-specific signals (NPI keywords, DEA sample lengths) when column names don't match. Some blind-mode FPs trace back to this. **Trade-off noted — revisit if Sprint 6 shows regressions.**

4. **Label tuning matters more than descriptions for v1.** GLiNER v1 ignores the dict description values and only uses the key string. `"person"` scored 0.99 vs `"person name"` at 0.33 on the same samples. GLiNER2 v2 actually uses descriptions, but we don't use v2 yet.

5. **Auto-discovery over env vars.** BQ's feedback drove a shift from `GLINER_ONNX_PATH` env var (required) to auto-discovery from standard locations. Zero-config is the recommended path; env var is still supported as an override.

6. **Warm-env benchmarks by default.** Cold start (12.7s for GLiNER model load) is a one-time cost that amortizes across a process lifetime. Mixing it into steady-state measurements creates noise. `perf_quick` warms the engines before timing.

## Open Threads (Carry to Sprint 6)

### 1. CRITICAL: GLiNER2 is 99.3% of Pipeline Cost
The ML engine dominates latency at 204ms/col for 50 samples. For BQ's 10K+ column workloads, this is the bottleneck. Options:
- **Batch inference**: `classify_batch` is implemented on the engine but orchestrator still calls `classify_column` per column. Proper batching could drop to 30-50ms/col.
- **Skip GLiNER when regex is confident**: if regex has 0.95 confidence on EMAIL, no need to also run GLiNER2 on that column.
- **Configurable scan depth**: quick scan (10-20 samples, regex-focused) vs deep scan (50+ samples, ML included).
- **Further quantization**: INT4 or CPU-optimized ONNX profiles.

### 2. FP/FN Root-Cause Deep Dive (Sprint 6 focus — user request)
Remaining failures (see SPRINT5_CONSOLIDATED.html for full list):

**False Positives (blind mode):**
- Nemotron col_12 `URL` → IP_ADDRESS (URL contains IP — URL/IP collision)
- Nemotron col_2 `CREDENTIAL` → ORGANIZATION (GLiNER fires on API keys)
- Nemotron col_0 `ABA_ROUTING` → SSN (9-digit collision without NPI signal)
- Ai4Privacy col_7 `SSN` → IP_ADDRESS (international SSN format matches IP)
- Ai4Privacy col_7 `SSN` → PHONE (international SSN format matches phone)
- Ai4Privacy col_6 `PHONE` → IP_ADDRESS (phone format collision)
- Ai4Privacy col_4 `IP_ADDRESS` → PHONE (IP format collision)

**False Negatives:**
- Nemotron col_0 `ABA_ROUTING` missed (no keyword, collision pile)
- Ai4Privacy col_1 `CREDENTIAL` missed (passwords look like random strings — no engine detects)
- Ai4Privacy col_7 `SSN` missed (international formats — our regex only handles US)

### 3. CREDENTIAL Detection Gap
Passwords in sample values can't be detected by any engine without column name hints. Options: password entropy scoring, known-bad-password dictionary, dedicated secret_scanner enhancement.

### 4. International SSN / Phone / Address Formats
Ai4Privacy and Nemotron include international formats we don't handle. Needs regex expansion with country-specific patterns.

### 5. Vague BQ Columns (`description`, `data`, `value`, `field_1`)
The real BQ challenge. Our `sample_analysis.match_ratio` is designed for this (low ratio = scattered PII → redaction, high ratio = whole-column type → policy tag), but we haven't validated on actual BQ data. Need a corpus of real vague-name mixed-content columns.

### 6. Meta-Classifier / Learned Arbitration
Hand-tuned calibration + confidence gap thresholds will hit a ceiling. A small logistic regression or XGBoost trained on (engine signals → correct entity type) would eliminate manual tuning. Training data already exists in benchmark results.

### 7. Batch Classification in Orchestrator
`classify_batch` was added to the engine interface but the orchestrator still loops `classify_column`. Backlog item exists (`batch-classification-in-orchestrator-dispatch-columns-to-ml-engines-in-batches-not-one-by-one`).

### 8. Sprint-over-Sprint Benchmark History
We run benchmarks each sprint but don't persist them as JSON for trend analysis. Need `benchmarks/history/sprint_{N}.json` + a chart in the report.

### 9. CI Install Test
The packaging bug (missing `engine_defaults.yaml`) showed we need a CI job that installs the package in a fresh venv and validates bundled data files load. Would catch future regressions.

### 10. Deep Dive on Descriptions with GLiNER2 v2
We confirmed GLiNER2 v2 supports descriptions, `include_confidence=True`, and has better accuracy on hard cases (partial addresses: 5/5 at 1.0 vs v1's 0.64-0.88). When fastino releases a PII-tuned v2 model, switch to it. Backlog item exists.

## Commits

| # | Hash | Description |
|---|---|---|
| 1 | b49460c | chore: start Sprint 5 |
| 2 | 2a76a2d | feat: Sprint 5 — engine weighting, sibling analysis, calibration, GLiNER2 |
| 3 | 86f153b | feat: GLiNER2 engine tuning — multi-model support, label optimization, ML suppression |
| 4 | 705565f | feat: ONNX deployment mode + API fallback |
| 5 | 67d1aba | docs: update CLIENT_INTEGRATION_GUIDE for v0.5.0 |
| 6 | 1a8ff42 | fix: make performance benchmark opt-in in generate_report |
| 7 | b0b25b6 | fix: code review — calibration key, column_id collision, dead code, guide |
| 8 | 195a732 | Merge pull request #4 from zbarbur/sprint5/main |
| 9 | a9597a2 | fix: packaging bug, ONNX auto-discovery, env var support |
| 10 | 1698661 | feat: consolidated benchmark report across all corpora and modes |
| 11 | 521e611 | feat: quick performance benchmark (<30s runtime) |
| 12 | 9a6e59b | refactor: perf_quick assumes warm env by default |

## Recommendations for Sprint 6

Based on open threads, the highest-leverage items for Sprint 6:

1. **FP/FN deep dive** — user-requested focus. Categorize every blind-mode failure by root cause, design targeted fixes.
2. **Batch classification** — biggest performance lever. 204ms → 30-50ms per column.
3. **International format expansion** — SSN, phone, address regex for non-US data.
4. **Meta-classifier prototype** — logistic regression on engine signals, evaluate on benchmark corpora.
5. **BQ vague-column corpus** — build a test corpus of real BigQuery columns with generic names and mixed content.

## Artifacts Shipped to BQ

- `v0.5.0` — Sprint 5 initial release
- `v0.5.1` — Critical fix: packaging bug + auto-discovery
- `v0.5.2` — Consolidated report + quick perf tooling
- `docs/CLIENT_INTEGRATION_GUIDE.md` — Full integration docs v0.5.2
- `docs/benchmarks/SPRINT5_REPORT.html` — Single-corpus report
- `docs/benchmarks/SPRINT5_CONSOLIDATED.html` — Cross-corpus consolidated report
- `scripts/export_onnx_model.py` — ONNX export CLI
- `data_classifier/export_onnx.py` — Module entry point for ONNX export

## CI Status

- ruff check: clean
- ruff format: clean
- pytest: 777 passed in 1.46s
- GitHub Actions: green on main

**Sprint 5 closed.** Ready for Sprint 6 planning.
