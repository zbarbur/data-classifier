# Stream B: Benchmark Overhaul + Corpus Integration

> **NOTE (2026-04-13):** This document cites F1 numbers measured against the `ai4privacy/pii-masking-300k` corpus, which has since been retired due to license non-compatibility. Historical numbers are preserved as records of what was measured at the time. See `docs/process/LICENSE_AUDIT.md` for context.

## Items
1. Benchmark methodology — industry-standard evaluation (P1, M)
2. Benchmark reporting — macro F1, per-entity F1, primary-label accuracy (P1, S)
3. Integrate real-world PII corpus (P1, M)
4. Research external secret detection corpora (P1, S)
5. Secret detection benchmark improvements (P1, S)

## Files Modified
- `tests/benchmarks/accuracy_benchmark.py` — new metrics (macro F1, per-entity, primary-label)
- `tests/benchmarks/generate_report.py` — unified report with new metrics
- `tests/benchmarks/secret_benchmark.py` — per-layer breakdown, expanded corpus
- `tests/benchmarks/corpus_loader.py` — NEW module for external corpora
- `tests/fixtures/corpora/` — NEW directory for downloaded corpus data
- `docs/BENCHMARK_METHODOLOGY.md` — NEW methodology documentation
- `docs/research/SECRET_CORPORA_RESEARCH.md` — NEW research findings

## Implementation Order

### Step 1: Research External Corpora (item 4 — research first, informs everything else)

Research task — web search and document findings:

1. **Ai4Privacy pii-masking-300k** (HuggingFace): 225K rows, 27+ PII types, custom license (research OK). Check format: JSON lines with `masked_text`, `privacy_mask`, `span_labels`. ETL: extract labeled spans → (value, entity_type) pairs.

2. **Nemotron-PII** (HuggingFace, CC BY 4.0): 100K records, 55+ types. Format TBD — download sample and analyze.

3. **SecretBench** (GitHub): 97K labeled secrets from 818 repos + FPSecretBench false positive corpus. MIT license. Format: CSV with `secret_value`, `type`, `file_path`.

4. **gitleaks test fixtures** (GitHub): Built-in test corpus in gitleaks repo. MIT license. Format: Go test files with known secrets.

5. **detect-secrets test suite** (GitHub, Yelp): Test fixtures with known secrets and FP cases. Apache 2.0.

Write findings to `docs/research/SECRET_CORPORA_RESEARCH.md` with license, size, format, coverage, and integration feasibility for each.

Recommend which to integrate first based on: license compatibility, ease of ETL, coverage of our entity types, and corpus quality.

### Step 2: Benchmark Methodology (item 1)

**Add to `accuracy_benchmark.py`:**

1. **Macro F1 computation:**
   - Current code computes micro F1 (sum all TP/FP/FN, then compute P/R/F1).
   - Add: compute F1 per entity type, then average → macro F1.
   - Both should be reported. Macro F1 gives equal weight to rare types.

2. **Primary-label accuracy:**
   - For each column: is the TOP prediction (highest confidence) the correct entity type?
   - Report as accuracy percentage: correct_top_1 / total_positive_columns.
   - This is the metric that matters most for user-facing results.

3. **Return new metrics** from `run_benchmark()` — add to return value:
   - `macro_f1: float`
   - `primary_label_accuracy: float`
   - `per_entity_metrics: dict[str, EntityMetrics]` (already returned)

4. **Corpus source abstraction:**
   - `run_benchmark()` already takes `corpus: list[tuple[ColumnInput, str | None]]`
   - This is source-agnostic — just need different corpus loaders to produce this format

**Write `docs/BENCHMARK_METHODOLOGY.md`:**
- What we measure: micro F1, macro F1, primary-label accuracy, per-entity P/R/F1
- Why: micro F1 is dominated by frequent types; macro F1 weights all types equally; primary-label is the user-facing metric
- How: synthetic (Faker) + real-world (Ai4Privacy/Nemotron) corpora
- Limitations: synthetic data doesn't capture real-world distributions; real corpora may have labeling errors

### Step 3: Benchmark Reporting (item 2)

**Update `accuracy_benchmark.py` `print_report()`:**

1. Add macro F1 row to overall summary
2. Add primary-label accuracy row
3. Per-entity F1 table already exists — ensure it's prominently displayed

**Update `generate_report.py`:**

1. Add macro F1 and primary-label accuracy to the summary table
2. Add per-entity F1 breakdown section in the markdown report
3. Add corpus source metadata (synthetic vs real-world)

### Step 4: Integrate Real-World PII Corpus (item 3)

**Create `tests/benchmarks/corpus_loader.py`:**

1. `load_ai4privacy_corpus(path, max_rows) -> list[tuple[ColumnInput, str | None]]`
   - Download a subset from HuggingFace (or ship a small sample in fixtures)
   - Parse span labels → group by entity type → create ColumnInput per type
   - Map Ai4Privacy types to our entity types (e.g., "CREDITCARDNUMBER" → "CREDIT_CARD")
   - Return in benchmark-compatible format

2. `load_synthetic_corpus(samples_per_type) -> list[tuple[ColumnInput, str | None]]`
   - Wrap existing `generate_corpus()` for consistent interface

3. `load_corpus(source="synthetic", **kwargs) -> list[tuple[ColumnInput, str | None]]`
   - Dispatcher: source="synthetic" → Faker, source="ai4privacy" → real corpus

**Update `accuracy_benchmark.py`:**
- Accept `--corpus` flag: "synthetic" (default) or "ai4privacy"
- Pass through to corpus loader

**Update `generate_report.py`:**
- Report which corpus source was used
- Optionally run both and compare

**Ship sample data:**
- Download a representative subset (500-1000 rows) of Ai4Privacy to `tests/fixtures/corpora/ai4privacy_sample.json`
- This allows offline benchmarking without network access

### Step 5: Secret Detection Benchmark Improvements (item 5)

**Update `secret_benchmark.py`:**

1. **Per-layer metrics:**
   - Current: reports overall P/R/F1 across all test cases
   - Add: break down by detection layer:
     - Regex layer: secrets detected by regex patterns alone
     - Key-name layer: secrets detected by key-name matching in scanner
     - Entropy layer: secrets detected by entropy scoring
   - Each SampleCase should be tagged with which layer(s) should detect it

2. **Expanded corpus:**
   - Add test cases from research findings (Step 1)
   - More adversarial near-misses: encoded non-secrets, UUIDs with key-like names
   - More service-specific tokens if found in gitleaks/detect-secrets fixtures

3. **Align report format** with main benchmark methodology
   - Use same metrics structure (micro F1, per-type breakdown)
   - Integrate into unified report via `generate_report.py`

## Acceptance Criteria Verification
After all changes:
- `pytest tests/ -v` — all green
- `ruff check . --exclude .claude/worktrees && ruff format --check . --exclude .claude/worktrees` — clean
- `python -m tests.benchmarks.accuracy_benchmark` produces report with macro F1 + primary-label
- `python -m tests.benchmarks.generate_report --sprint 4` produces unified report
