# Sprint 4 Benchmark Baseline Report

> **NOTE (2026-04-13):** This document cites F1 numbers measured against the `ai4privacy/pii-masking-300k` corpus, which has since been retired due to license non-compatibility. Historical numbers are preserved as records of what was measured at the time. See `docs/process/LICENSE_AUDIT.md` for context.

> **Date**: 2026-04-11
> **Purpose**: Formal baseline for measuring Sprint 5+ improvements
> **Methodology**: See Sprint 4 benchmark methodology (macro F1, micro F1, primary-label accuracy)

## Metric Definitions

| Metric | Definition | Why It Matters |
|--------|-----------|----------------|
| **Macro F1** | Average of per-entity F1 scores | Weights all entity types equally — reveals weak types |
| **Micro F1** | Aggregate TP/FP/FN across all types | Dominated by frequent types — reflects real-world volume |
| **Primary-Label Accuracy** | Is the top-1 prediction correct? | What users actually see — most actionable metric |
| **Precision** | TP / (TP + FP) | Measures false positive rate |
| **Recall** | TP / (TP + FN) | Measures missed detections |

## Synthetic Corpus (1,850 samples, 37 columns)

| Metric | Sprint 3 | Sprint 4 | Change |
|--------|----------|----------|--------|
| Macro F1 | -- | **0.930** | NEW |
| Micro F1 | 0.897 | **0.945** | +5.3% |
| Primary-Label | -- | **96.3%** | NEW |
| Precision | 0.839 | **0.929** | +10.7% |
| Recall | 0.963 | 0.963 | same |
| TP / FP / FN | 26 / 5 / 1 | 26 / **2** / 1 | -3 FP |

**Notes**: Synthetic data (Faker-generated) provides controlled validation but gives
flattering results. Real-world precision is significantly lower.

## Real-World PII Corpora

### Ai4Privacy (366K samples, 8 entity types)

| Metric | Sprint 4 (Baseline) |
|--------|-------------------|
| Macro F1 | **0.390** |
| Micro F1 | **0.179** |
| Primary-Label | **75.0%** |
| Precision | 0.102 |
| Recall | 0.750 |
| FPs | 53 |

**Key observations**:
- Recall is strong (75%) but precision is catastrophically low (10.2%)
- Secondary predictions are the main source of noise (SSN fires on any 9-digit number)
- Primary-label accuracy (75%) is much more representative of user experience
- PERSON_NAME, ADDRESS, and DATE_OF_BIRTH detection relies on column name only (no sample analysis)

### Nemotron-PII (155K samples, 13 entity types)

| Metric | Sprint 4 (Baseline) |
|--------|-------------------|
| Macro F1 | **0.672** |
| Micro F1 | **0.464** |
| Primary-Label | **100%** |
| Precision | 0.302 |
| Recall | 1.000 |
| FPs | 30 |

**Key observations**:
- Perfect recall (100%) and primary-label accuracy (100%)
- FPs come from secondary predictions on already-classified columns
- Better precision than Ai4Privacy because Nemotron has cleaner formatting

## Secret Detection Corpora

### Per-Source Breakdown

| Source | Total | TP | FP | FN | Precision | Recall |
|--------|-------|-----|-----|-----|-----------|--------|
| builtin | 102 | 33 | 0 | 1 | 1.000 | 0.971 |
| detect-secrets | 8 | 5 | 0 | 2 | 1.000 | 0.714 |
| gitleaks | 170 | 12 | 37 | 17 | 0.245 | 0.414 |
| SecretBench | 1,067 | 128 | 263 | 388 | 0.327 | 0.248 |
| **Overall** | **1,347** | **178** | **300** | **408** | **0.372** | **0.304** |

### Secret Detection Analysis

- **Builtin corpus** (our own test cases): Near-perfect (P=1.0, R=0.97)
- **detect-secrets**: Small corpus, good results (P=1.0, R=0.71)
- **gitleaks**: 37 FPs from crafted false-positive test cases; missing placeholder suppressions
- **SecretBench**: Largest gap (388 FNs) — see `docs/research/SECRETBENCH_FN_ANALYSIS.md`

## Per-Entity Type Performance (Where Available)

### Synthetic Corpus — Per-Entity

Entity types with known issues from Sprint 4 benchmarks:

| Entity Type | Status | Issue |
|-------------|--------|-------|
| SSN | High FP | Fires on any 9-digit number without context gating |
| HEALTH | High FP | Pattern matches broadly on 4-8 non-health columns |
| PERSON_NAME | Column-name only | No sample value analysis — GLiNER2 will address |
| ADDRESS | Column-name only | No sample value analysis — GLiNER2 will address |
| CREDENTIAL | Missed at scale | Real passwords and international formats not matched |
| PHONE | Missed at scale | International phone formats not covered |
| MAC_ADDRESS/DEVICE_ID | FP | Column name pattern too broad |

## Comparison Framework

### How to Measure Sprint 5+ Improvements

To compare against this baseline:

```bash
# Re-run benchmarks
python3 -m tests.benchmarks.generate_report --sprint 5

# Compare specific corpus
python3 -m tests.benchmarks.accuracy_benchmark --corpus ai4privacy
python3 -m tests.benchmarks.accuracy_benchmark --corpus nemotron
python3 -m tests.benchmarks.secret_benchmark
```

### Target Metrics for Sprint 5

| Metric | Sprint 4 Baseline | Sprint 5 Target | Lever |
|--------|------------------|----------------|-------|
| Ai4Privacy Micro F1 | 0.179 | > 0.35 | Engine weighting, SSN gating |
| Nemotron Micro F1 | 0.464 | > 0.70 | Engine weighting, primary-label mode |
| Primary-Label (Ai4P) | 75.0% | > 95% | Engine weighting |
| Primary-Label (Nem) | 100% | 100% | Maintain |
| SecretBench Recall | 0.248 | > 0.35 | Parser expansion (Sprint 6) |
| Gitleaks FPs | 37 | < 10 | Placeholder suppressions |

### Tracking Changes

Each sprint should report:

1. **All metrics above** re-measured on same corpora
2. **Delta from baseline** for each metric
3. **Per-entity breakdown** for any entity type with > 5% change
4. **New FP/FN categories** discovered

## Key Findings (Sprint 4)

1. **Synthetic benchmarks are misleading**: F1 0.945 (synthetic) vs 0.179-0.464 (real). Real data
   has messier formats, cross-pattern collisions, and international variants.

2. **Primary-label accuracy is the right metric**: Top-1 prediction is correct much more often
   than micro F1 suggests. Users see top-1 — secondary predictions are implementation noise.

3. **Precision is the bottleneck**: Recall is strong (75-100%). The problem is too many false
   positive secondary predictions, especially SSN firing on 9-digit numbers.

4. **Column name engine is more reliable but loses to regex**: Column name engine confidence
   (0.90) loses to regex content match confidence (0.94). Engine priority weighting is the
   single biggest lever for precision improvement.

5. **PERSON_NAME and ADDRESS need ML**: Currently detected by column name only. GLiNER2 will
   enable sample-value-based detection, improving recall on these types.

6. **SecretBench exposes parser gaps**: 75% FN rate. Most missed secrets are in connection
   strings, URLs, and code contexts that our parsers do not handle yet.

---

*Baseline established Sprint 4. Updated Sprint 5+.*
