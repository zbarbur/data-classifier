# Sprint 16 Mid-Handoff — CONTACT + GOVERNMENT_ID Recall

**Date:** 2026-04-27
**Branch:** `sprint16/main` (21 files changed, +951/-132 vs main)
**Theme:** CONTACT + GOVERNMENT_ID recall improvements
**Tests:** 2,383 passed, 1 skipped, 1 xfailed

## Status: 4/5 items in review, 1 doing

| # | Item | Status | Size |
|---|------|--------|------|
| 1 | GLiNER dedup fix | **review** | S |
| 2 | Threshold sweep | **review** (re-scoped to finding) | S |
| 3 | S3b label narrowing | **review** (re-scoped to finding) | S |
| 4 | GOVERNMENT_ID patterns phase 1 | **review** | L |
| 5 | WildChat GT completion | doing | S |

## What Was Done

### 1. GLiNER dedup fix — evidence-overlap suppression

**Problem:** `_deduplicate_gliner_findings` in `gliner_engine.py` suppressed
PERSON_NAME whenever ADDRESS co-fired, using a global type-hierarchy
(specificity=3 beats specificity=1). This was wrong when the two
findings detected different values (e.g. names vs street addresses).

**Fix:** Changed suppression to check Jaccard overlap on `sample_matches`.
Two findings only suppress each other when evidence overlap >= 50%.
When they detect different values, both survive.

**Files:** `gliner_engine.py` (new `_evidence_overlap` function +
`_EVIDENCE_OVERLAP_THRESHOLD`), `test_gliner_engine.py` (+1 test).

### 2. Threshold sweep — finding: not the lever

**Finding:** GLiNER threshold (0.30-0.50) has **no measurable impact** on
CONTACT recall. Predictions are bimodal — either well above 0.5 or below
0.3. The real lever is ML on/off: the Sprint 15 canonical benchmark ran
with `DATA_CLASSIFIER_DISABLE_ML=1`, so CONTACT recall was
regex+column_name only.

With ML enabled, PERSON_NAME recall jumps 47.7% → 100%.

**Files:** `scripts/gliner_threshold_sweep.py` (sweep script, not used in CI).

### 3. S3b label narrowing — finding: doesn't help

**Finding:** Narrowing GLiNER's label set when column_name_engine is
confident shows no material improvement (6/10 vs 7/10 on ambiguous
address samples). The research/gliner-context S3 result was confirmed —
label narrowing is not productive for this model.

**Files:** `docs/research/meta_classifier/sprint16_ml_enabled_benchmark.json`
(ML-on benchmark saved as reference).

### 4. GOVERNMENT_ID patterns phase 1 — 6 countries

Added 7 regex patterns + 7 checksum validators for:

| Country | Pattern | Validator | Confidence |
|---------|---------|-----------|------------|
| DE | `\b\d{11}\b` | `german_steuerid` (iterative mod-10/11) | 0.35 |
| FR | `\b[12378]\d{14}\b` | `french_nir` (97 - base % 97) | 0.40 |
| ES DNI | `\b\d{8}[A-Z]\b` | `spanish_dni` (mod-23 letter) | 0.50 |
| ES NIE | `\b[XYZ]\d{7}[A-Z]\b` | `spanish_nie` (prefix + mod-23) | 0.70 |
| IT | `\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b` | `italian_codice_fiscale` (odd/even tables) | 0.85 |
| NL | `\b[1-9]\d{8}\b` | `dutch_bsn` (11-check, weights [9,8,7,6,5,4,3,2,-1]) | 0.35 |
| AT | `\b[1-9]\d{9}\b` | `austrian_svnr` (check digit at pos 4) | 0.35 |

**Files:** `validators.py` (+209 lines), `default_patterns.json` (+7 patterns,
count 77→169*), `test_regex_engine_precision.py` (+50 tests).

*Pattern count was already outdated before this sprint; now correct.

### 5. Within-family specificity ordering (bonus — emerged from ADDRESS investigation)

**Problem:** When GLiNER fires both ADDRESS and PERSON_NAME on the same
column (common — Bulgarian street names are person names), the primary
label picks PERSON_NAME because it has higher confidence (0.96 vs 0.68).
But they're in the same CONTACT family — ADDRESS is more informative.

**Fix:** Added `ENTITY_SPECIFICITY` map to `taxonomy.py` and
within-family specificity-based sorting to `_apply_findings_limit` in
`__init__.py`. Also updated the benchmark's `_top_finding`. Cross-family
ordering is unchanged (pure confidence); within the same family, the
more specific type becomes primary.

**Impact (measured on ML-enabled benchmark, re-scored):**
- ADDRESS subtype recall: 0.500 → **1.000**
- PERSON_NAME recall: 1.000 → 1.000 (no regression)

**Files:** `taxonomy.py` (+`ENTITY_SPECIFICITY`, `specificity_for`),
`__init__.py` (`_apply_findings_limit`), `family_accuracy_benchmark.py`
(`_top_finding`), `test_primary_label.py` (+3 tests).

## Benchmark Comparison

### No-ML (canonical sprint gate)

| Metric | S15 | S16 | Delta |
|--------|-----|-----|-------|
| cross_family_rate | 0.1066 | **0.0801** | -0.0265 |
| family_macro_f1 | 0.9477 | **0.9734** | +0.0257 |

### ML-enabled + specificity fix (re-scored from predictions)

| Metric | S15 (no-ML) | S16 (ML+spec) | Delta |
|--------|-------------|---------------|-------|
| cross_family_rate | 0.1066 | **0.0291** | -0.0775 |
| family_macro_f1 | 0.9477 | **0.9903** | +0.0426 |
| CONTACT F1 | 0.796 | **0.966** | +0.170 |
| ADDRESS subtype F1 | 0.642 | **0.942** | +0.300 |
| PERSON_NAME F1 | 0.646 | **0.948** | +0.302 |
| GOVERNMENT_ID F1 | 0.947 | 0.951 | +0.004 |

## What's NOT Done

1. **WildChat GT completion** — 90 prompts still unreviewed (interactive task)
2. **EU validators not ported to JS** — browser parity will drop for these
   6 patterns (same as the 19 existing stubbed validators)
3. **EU validators not ported to Rust** — the unified WASM detector branch
   (`research/prompt-analysis`) has its own validator set; these 7 need
   adding when that merges
4. **NATIONAL_ID benchmark unchanged at 0.667** — new patterns are present
   but openpii-1m values may not pass the checksums (expected — the corpus
   has synthetic/approximate values)

## Key Findings to Carry Forward

1. **Canonical benchmark runs without ML** — CONTACT recall metrics in
   sprint gate don't reflect GLiNER's contribution. Consider adding an
   ML-enabled benchmark run as a secondary gate.

2. **ADDRESS↔PERSON_NAME is a primary-label selection problem, not a
   detection problem** — both findings exist. The specificity fix
   addresses it for now. Long-term, multi-label output is the right
   answer (both labels are correct).

3. **openpii-1m ADDRESS shards contain person-name-derived street
   names** (Bulgarian: "Мария Габровска", "Стефан Стамболов") — GLiNER
   correctly identifies both person and address tokens. Not a bug.

4. **Unified WASM detector** (`research/prompt-analysis`) is 115 commits
   ahead with full Rust implementation. Merge will need:
   - Conflict resolution on `scan_text.py`, `validators.py`
   - Port of 7 new EU validators to Rust
   - Specificity ordering in Rust's output path

## Files Changed (21 files, +951/-132)

```
data_classifier/__init__.py                     — within-family specificity sort
data_classifier/core/taxonomy.py                — ENTITY_SPECIFICITY map
data_classifier/engines/gliner_engine.py        — evidence-overlap dedup
data_classifier/engines/validators.py           — 7 EU validators
data_classifier/patterns/default_patterns.json  — 7 EU patterns
tests/test_gliner_engine.py                     — dedup tests
tests/test_primary_label.py                     — specificity tests
tests/test_regex_engine_precision.py            — EU validator tests
tests/benchmarks/family_accuracy_benchmark.py   — specificity in _top_finding
scripts/gliner_threshold_sweep.py               — sweep script (not CI)
docs/research/.../sprint16_ml_enabled_benchmark.json
+ browser generated files (auto-regenerated)
+ backlog YAMLs (status updates)
```

## To Resume

1. Run full CI: `ruff check . --exclude .claude/worktrees && ruff format --check . --exclude .claude/worktrees && .venv/bin/python -m pytest tests/ -v && bash scripts/ci_browser_parity.sh`
2. Items 1-4 are in review — code review then move to done
3. Item 5 (WildChat GT) — decide if completing in this sprint or deferring
4. Close sprint: benchmark, handover doc, version bump, merge, tag
5. Consider merging unified WASM detector as Sprint 17 first item
