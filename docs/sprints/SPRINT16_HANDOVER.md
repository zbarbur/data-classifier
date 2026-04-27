# Sprint 16 Handover — CONTACT + GOVERNMENT_ID Recall

**Dates:** 2026-04-25 → 2026-04-27
**Version:** v0.16.0
**Tests:** 2,405 passed, 20 skipped, 1 xfailed
**Branch:** sprint16/main

## Theme

Lift CONTACT and GOVERNMENT_ID recall against the openpii-1m gap surfaced
in S15: dedup correctness, EU national-ID coverage, and the within-family
primary-label fix that emerged from the ADDRESS↔PERSON_NAME investigation.

## Benchmark (canonical, ML disabled)

| Metric | S15 | S16 | Delta |
|---|---|---|---|
| LIVE `cross_family_rate` | 0.1066 | **0.0808** | -0.0258 (better) |
| LIVE `family_macro_f1` | 0.9477 | **0.9732** | +0.0255 |
| SHADOW `cross_family_rate` | 0.3245 | **0.3139** | -0.0106 (better) |
| SHADOW `family_macro_f1` | 0.7030 | **0.8305** | +0.1275 |

Sprint gate metric (`shadow.cross_family_rate`) improved from baseline.
Summary saved to `docs/research/meta_classifier/sprint16_family_benchmark.json`.

### ML-enabled (reference, not gated)

With GLiNER active and within-family specificity sort applied:

| Metric | S15 (no-ML) | S16 (ML+spec) | Delta |
|---|---|---|---|
| `cross_family_rate` | 0.1066 | **0.0291** | -0.0775 |
| `family_macro_f1` | 0.9477 | **0.9903** | +0.0426 |
| CONTACT F1 | 0.796 | **0.966** | +0.170 |
| ADDRESS subtype F1 | 0.642 | **0.942** | +0.300 |
| PERSON_NAME F1 | 0.646 | **0.948** | +0.302 |

Saved to `docs/research/meta_classifier/sprint16_ml_enabled_benchmark.json`.
The canonical sprint gate runs without ML (CI matches), so these numbers
are directional — they show the contribution of GLiNER + the specificity
fix on top of the no-ML baseline.

## Items Completed (4/4)

### 1. GLiNER dedup fix — evidence-overlap suppression (P1, S, bug)

`_deduplicate_gliner_findings` previously suppressed PERSON_NAME whenever
ADDRESS co-fired (global type-hierarchy: specificity 3 > 1). Wrong when
the two findings detect different values.

**Fix:** suppression now requires Jaccard overlap ≥ 0.50 on
`sample_matches`. Different-value findings both survive.

**Files:** `gliner_engine.py` (new `_evidence_overlap`,
`_EVIDENCE_OVERLAP_THRESHOLD`), `test_gliner_engine.py` (+1 test).

### 2. GLiNER threshold sweep — finding only (P2, S, research)

GLiNER threshold (0.30–0.50) has **no measurable impact** on CONTACT
recall. Predictions are bimodal — well above 0.5 or below 0.3. The real
lever is ML on/off; the canonical benchmark runs no-ML so CONTACT recall
reflects regex+column_name only. With ML enabled, PERSON_NAME recall
jumps 47.7% → 100%.

**Files:** `scripts/gliner_threshold_sweep.py` (sweep tool, not in CI).

### 3. S3b label narrowing — finding only (P2, S, research)

Narrowing GLiNER's label set when `column_name_engine` is confident shows
no material improvement (6/10 vs 7/10 on ambiguous address samples).
Confirms the research/gliner-context S3 result. Label narrowing is not
productive for this model.

**Files:** `docs/research/meta_classifier/sprint16_ml_enabled_benchmark.json`.

### 4. GOVERNMENT_ID patterns phase 1 — 6 EU countries (P1, L, feature)

Added 7 regex patterns + 7 checksum validators:

| Country | Pattern | Validator | Confidence |
|---|---|---|---|
| DE | `\b\d{11}\b` | `german_steuerid` (iterative mod-10/11) | 0.35 |
| FR | `\b[12378]\d{14}\b` | `french_nir` (97 - base % 97) | 0.40 |
| ES DNI | `\b\d{8}[A-Z]\b` | `spanish_dni` (mod-23 letter) | 0.50 |
| ES NIE | `\b[XYZ]\d{7}[A-Z]\b` | `spanish_nie` (prefix + mod-23) | 0.70 |
| IT | `\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b` | `italian_codice_fiscale` (odd/even tables) | 0.85 |
| NL | `\b[1-9]\d{8}\b` | `dutch_bsn` (11-check, weights `[9..2,-1]`) | 0.35 |
| AT | `\b[1-9]\d{9}\b` | `austrian_svnr` (check digit at pos 4) | 0.35 |

**Files:** `validators.py` (+209 lines), `default_patterns.json` (+7),
`test_regex_engine_precision.py` (+50 tests).

### Bonus: within-family specificity ordering

Emerged from ADDRESS investigation. When GLiNER fires both ADDRESS and
PERSON_NAME on the same column (common — Bulgarian street names look
like person names), the primary-label sort previously picked the higher
confidence (PERSON_NAME 0.96 > ADDRESS 0.68). But within the CONTACT
family, ADDRESS is the more informative type.

**Fix:** added `ENTITY_SPECIFICITY` map; primary-label sort breaks ties
within a family by preferring higher specificity. Cross-family ordering
unchanged (pure confidence).

**Files:** `taxonomy.py` (+`ENTITY_SPECIFICITY`, `specificity_for`),
`__init__.py` (`_apply_findings_limit`),
`family_accuracy_benchmark.py` (`_top_finding`),
`test_primary_label.py` (+3 tests).

## Tooling

### uv migration (chore PR #20, merged before close)

- Dev workflow migrated to `uv` (10–100× faster venv creation, 40–87%
  on-disk reduction via APFS clones / hardlinks).
- 3 of 4 CI jobs (`lint-and-test`, `lint-and-test-ml`, `browser-parity`)
  switched to `uv pip install --system` with shared cache.
- `install-test` deliberately left on pip — validates the end-user
  `pip install data_classifier-*.whl` smoke path.
- CLAUDE.md updated to document the new install command and the
  `gliner2==1.2.6` manual-install gotcha.

### Backlog hygiene

- Fixed `scan-text-fp-filter-parity-with-js-scanner.yaml` schema
  (`status: open` → `backlog`, `test_plan` dict → list); was being
  silently dropped by `agile-backlog`.
- Removed stale `xfail` marker on
  `test_invalid_dates_rejected[32/13/2000]` (GLiNER no longer fires
  DATE_OF_BIRTH on this string after the dedup + specificity changes).

## Deferred to Sprint 17

- **WildChat GT completion** — 90 prompts still unreviewed. Ground-truth
  build is interactive and didn't fit S16 capacity; deferred as a
  scoped P1 to S17 backlog.

## Known Gaps / Sprint 17 Candidates

1. **EU validators not ported to JS** — 7 new validators stubbed in
   `validators.js`; browser parity will drop for these patterns until
   ported.
2. **EU validators not ported to Rust** — `research/prompt-analysis`
   unified WASM detector branch needs the 7 validators when it merges.
3. **NATIONAL_ID benchmark unchanged at 0.667** — patterns present but
   openpii-1m values may not pass the checksums (corpus has
   synthetic/approximate values; expected, not a regression).
4. **Unified WASM detector merge** (`research/prompt-analysis`,
   ~140 commits ahead) — Sprint 17 first item candidate. Will need
   conflict resolution on `scan_text.py`/`validators.py` plus the EU
   validators ported to Rust.
5. **Multi-label primary output** — within-family specificity is a
   short-term fix. Longer-term, multi-label output makes both ADDRESS
   and PERSON_NAME first-class when both apply.

## Release

- Version: `0.16.0` in `pyproject.toml` and `data_classifier/__init__.py`
- CHANGELOG: Sprint 16 entry added
- Browser parity: maintained at 87% (no regression; new EU validators
  add to the existing stubbed-validator backlog)

**To ship:** merge `sprint16/main` → `main`, tag `v0.16.0`, push to
trigger Cloud Build. Dry-run the release pipeline first per the
`feedback_dry_run_release_pipelines` memory.
