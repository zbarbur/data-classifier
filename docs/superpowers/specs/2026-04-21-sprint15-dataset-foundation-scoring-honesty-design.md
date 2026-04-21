# Sprint 15 Design — Dataset Foundation + Scoring Honesty

> **Date:** 2026-04-21
> **Sprint:** 15
> **Branch:** sprint15/main
> **Items:** 7 (3M + 4S)

---

## Overview

Sprint 15 fixes the measurement and scoring foundation before the Sprint 16 architectural items (shape-first routing, context-aware pre-routing). Three themes:

1. **Dataset foundation** — DVC migration, corpus thickening, openpii-1m ingest
2. **Scoring honesty** — confidence model rethink, char-class diversity metric
3. **Text-path measurement** — opaqueTokenPass parity, scan_text benchmark

## Execution Order

```
Phase 1 (foundation — independent, parallelizable):
  [1] DVC migration + corpus ingest
  [5] Port opaqueTokenPass to Python scan_text

Phase 2 (scoring — needs Phase 1 corpora for verification):
  [3] Confidence model rethink
  [4] Char-class diversity boost
  [2] NEGATIVE corpus cleanup

Phase 3 (measurement — needs Phase 1+2 for accurate results):
  [6] Text-path benchmark
  [7] WildChat eval dataset
```

---

## Item 1: DVC Migration + Corpus Ingest (M)

### Step 1 — Migrate existing data files to DVC

All data files >10KB move from git to DVC+GCS (`gs://data-classifier-datasets/dvc-cache`):

- `tests/fixtures/corpora/*.json` (nemotron 12MB, secretbench 190KB+166KB, gretel 24KB+36KB, gitleaks 44KB, detect_secrets 4KB)
- `docs/sprints/*_bench.predictions.jsonl` (7.4MB)
- `docs/experiments/prompt_analysis/s0_artifacts/**/*.jsonl` (22MB)
- `docs/experiments/prompt_analysis/s2_spike/report/*.json` (3.7MB)

Process: `git rm --cached` → `dvc add` → commit `.dvc` pointers → `dvc push`.

Pattern data (`data_classifier/patterns/*.json`) stays in git — ships in the pip wheel.

### Step 2 — Re-download Gretel fixtures uncapped

Current fixtures were generated via HuggingFace REST API fallback, capped at ~500 rows. The `datasets` library (installed in `.venv`) can stream the full dataset.

- Change `download_corpora.py` default: `max_per_type=None` (no limit, pull all unique values)
- Re-run `download_gretel_en` (60K rows → expect ~5K+ unique values per type)
- Re-run `download_gretel_finance` (100K rows → expect ~5K+ unique values per type)
- DVC-track the new larger fixtures

### Step 3 — Add openpii-1m ingest

- New `download_openpii_1m()` in `download_corpora.py`
- Source: `ai4privacy/pii-masking-openpii-1m` (CC-BY-4.0, 1.4M rows, 23 languages, 19 labels)
- ETL through existing `OPENPII_1M_TYPE_MAP` (19 labels → 8 entity types)
- NEGATIVE candidates: values failing format validation + unmapped label types
- Fixture: `tests/fixtures/corpora/openpii_1m_sample.json`, DVC-tracked
- Raw parquet: `data/ai4privacy_openpii/`, DVC-tracked

### Step 4 — Wire into shard builder

- New `_openpii_1m_pool()` in `shard_builder.py` (same pattern as `_gretel_en_pool()`)
- Wire into `build_real_corpus_shards()` alongside Nemotron/Gretel-EN/Gretel-finance
- NEGATIVE pool gains openpii unmapped values as new source
- NATIONAL_ID gets first real-corpus coverage (3 source labels: IDCARDNUM, DRIVERLICENSENUM, PASSPORTNUM)

### Step 5 — CI update

- Add `dvc pull tests/fixtures/corpora/` step to `.github/workflows/ci.yaml`
- Add `google-github-actions/auth` step for GCS access (same `dag-bigquery-dev` project)
- Runs before pytest

---

## Item 5: Port opaqueTokenPass to Python scan_text (S)

### What

Add `_opaque_token_pass()` as the third pass in `TextScanner.scan()`, after regex and secret scanner KV.

### Logic (mirrors browser scanner-core.js lines 265-321)

1. Tokenize text on whitespace (`\S+`)
2. Strip leading/trailing quotes and punctuation
3. Skip if: too short, obviously not secret, UUID, placeholder, anti-indicator
4. Compute relative entropy + char-class diversity
5. Gate: `rel_entropy >= threshold` AND `diversity >= threshold`
6. Confidence: base + bonuses for high entropy and length
7. Emit as `OPAQUE_SECRET` finding

### Implementation

Reuse existing Python helpers from `SecretScannerEngine` and `heuristic_engine`:
- `_compute_relative_entropy()` / `_score_relative_entropy()`
- `compute_char_class_diversity()`
- `_value_is_obviously_not_secret()`
- Placeholder detection, anti-indicators

Pull thresholds from browser's `SECRET_SCANNER` config constants to ensure parity.

Dedup: existing `_dedup()` keeps highest-confidence span per overlap. Regex patterns have specific entity types and higher confidence, so they win over generic OPAQUE_SECRET. Opaque token pass catches what regex misses.

### Files

- `data_classifier/scan_text.py` — add `_opaque_token_pass()` method, wire into `scan()`
- Remove TODO comment on line 17

---

## Item 3: Confidence Model Rethink (M)

### Problem

`confidence` conflates two signals: match quality (is this value really that type?) and prevalence (what fraction of the column contains this type?). With per-pattern findings (S14), a single validated AWS key in a 200-row column gets penalized to 0.62 by the count multiplier.

### Design decisions

1. **`confidence` = match quality** — how certain is this specific match?
2. **`sample_analysis.match_ratio` = prevalence** — already exists, no schema change
3. **Validated matches floor at 0.95** — checksum/structural proof is near-certain
4. **No count multiplier** — drop the 0.65/0.85/1.0 scaling entirely

### New formula

```python
# In regex_engine.py _compute_sample_confidence():
base = pattern.confidence                    # from default_patterns.json
if validator_exists and validator_passed:
    confidence = max(base, 0.95)             # mathematical proof → floor at 0.95
elif validator_exists and not validator_passed:
    suppress finding                         # already the behavior
else:
    confidence = base                        # pattern specificity IS the quality signal
confidence = min(confidence, 1.0)
# NO count multiplier
```

### Why no count multiplier at all

The pattern base confidence in `default_patterns.json` already encodes match quality:
- `\d{9}` (bare SSN) → base 0.40 (weak regex, uncertain)
- `AKIA[0-9A-Z]{16}` (AWS key) → base 0.95 (prefix + length + charset = certain)
- Validated patterns floor at 0.95 regardless of base

The count multiplier was prevalence signal leaking into match quality. With the semantic split, prevalence belongs in `match_ratio` only.

### Ripple effects

- **Meta-classifier retrain** — confidence is a feature; semantic change requires rebuilding training data. Happens naturally with new corpora (Item 1).
- **min_confidence filtering** — validated patterns always pass (0.95+). Weak unvalidated patterns at base < 0.5 get filtered. No change needed.
- **Collision resolution** — validated patterns win collisions. Correct behavior.
- **CLIENT_INTEGRATION_GUIDE.md** — document semantic: `confidence` = match quality, `match_ratio` = prevalence.

---

## Item 4: Char-class Diversity Boost (S)

### Problem

`diversity >= 3` is a binary gate in the secret scanner. A value with diversity=4 and perfectly distributed character classes scores identically to diversity=3 with one dominant class.

### New metric: char-class evenness

Instead of just counting classes present, measure how evenly characters are distributed across classes using normalized Shannon entropy over the 4-bucket class distribution:

```python
def char_class_evenness(value: str) -> float:
    """0.0 = one class dominates, 1.0 = perfectly even across all present classes."""
    counts = [upper, lower, digit, symbol]  # character counts per class
    present = [c / total for c in counts if c > 0]
    num_classes = len(present)
    if num_classes <= 1:
        return 0.0
    H = -sum(p * log2(p) for p in present)
    H_max = log2(num_classes)
    return H / H_max
```

### Examples

| Value | Classes | Distribution | Evenness |
|---|---|---|---|
| `P}fX2+dX8B5q#a` | 4 | ~33/33/20/14% | 0.94 |
| `myLongVariableName1!` | 4 | 5/80/5/5% | 0.49 |
| `AKIA0B1C2D3E4F5G6H7` | 3 | 70/0/30/0% | 0.88 |

### Usage in secret scanner

```python
# Gate (unchanged)
if diversity < diversity_min:
    return 0.0

# Boost (new)
evenness = char_class_evenness(value)
diversity_bonus = evenness * 0.15   # calibrate against WildChat
composite += diversity_bonus
```

### Browser parity

Add `charClassEvenness()` to `entropy.js`, use in `scanner-core.js` strong/contextual tiers.

### Files

- `data_classifier/engines/heuristic_engine.py` — add `compute_char_class_evenness()`
- `data_classifier/engines/secret_scanner.py` — use in strong/contextual tier scoring
- `data_classifier/clients/browser/src/entropy.js` — JS port
- `data_classifier/clients/browser/src/scanner-core.js` — wire into scoring

---

## Item 2: NEGATIVE Corpus Cleanup (M)

### Approach

1. Run `scan_text` (with opaqueTokenPass from Item 5) over every value in the NEGATIVE pool
2. Values producing a finding → relabel to detected entity type
3. Placeholder-patterned values (repeated X/0, `EXAMPLE`, `test`) → remain NEGATIVE
4. Non-credential strings (prose, code, config without secrets) → remain NEGATIVE
5. With openpii-1m (Item 1), NEGATIVE pool gains diverse genuinely-non-sensitive values

### Files

- `shard_builder.py` — `_credential_corpus_pool()` and `_relabel_negative_by_regex()`
- Extend `_relabel_negative_by_regex()` to also use opaqueTokenPass signals

---

## Item 6: Text-path Benchmark (S)

### What

New benchmark: `tests/benchmarks/text_path_benchmark.py`

- Loads WildChat eval dataset (Item 7)
- Runs `scan_text` on each prompt
- Compares against labels → precision, recall, F1
- Outputs summary JSON (same format as family accuracy benchmark)
- Becomes the text-path equivalent of `family_macro_f1`

---

## Item 7: WildChat Eval Dataset (S)

### What

Persist the 3,515 WildChat credential prompts reviewed in S14 as a labeled evaluation dataset.

- Re-scan all prompts with current `scan_text` (including opaqueTokenPass)
- Save as JSONL: `{prompt_xor, findings, label, confidence, reviewed}`
- Include 5 known FN cases (label=FN) and 4 known FP cases (label=FP)
- 620 suppressed prompts labeled TN
- DVC-tracked in `data/`

### Browser parity

JS scanner should produce identical results on same prompts. Differential test using this dataset.

---

## Verification

### Sprint quality gates

1. `ruff check .` — zero warnings
2. `ruff format --check .` — zero diffs
3. `.venv/bin/python -m pytest tests/ -v` — all green
4. `bash scripts/ci_browser_parity.sh` — passed
5. Family accuracy benchmark — `family_macro_f1` no regression from S14 (0.9509)
6. Text-path benchmark — scan_text F1 on WildChat (new baseline)
7. GitHub Actions CI passing on sprint branch
