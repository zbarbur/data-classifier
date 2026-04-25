# Sprint 15 Handover — Dataset Foundation + Scoring Honesty

**Dates:** 2026-04-21 → 2026-04-25
**Version:** v0.15.0
**Tests:** 2,343 passed, 1 skipped, 1 xfailed
**Branch:** sprint15/main (40 commits ahead of main)

## Theme

Dataset foundation (openpii-1m corpus, WildChat GT), scoring honesty
(confidence rethink, diversity boost), and text-path precision (25+ FP
filters, PEM detection, SWIFT_BIC validator).

## Benchmark

| Metric | S14 | S15 | Delta |
|---|---|---|---|
| `cross_family_rate` | 0.1182 | **0.1066** | -0.0116 |
| `family_macro_f1` | 0.8566 | **0.9477** | +0.0911 |
| `NEGATIVE` F1 | 0.000 | **1.000** | +1.000 |
| `FINANCIAL` F1 | 0.996 | 0.972 | -0.024 |
| `CREDENTIAL` F1 | 0.871 | 0.896 | +0.025 |
| `URL` F1 | 0.723 | 0.948 | +0.225 |
| `VEHICLE` F1 | 0.909 | 0.998 | +0.089 |

**FINANCIAL F1 -0.024 note:** SWIFT_BIC validator now rejects all-alpha
matches (surnames like HOUTHTALING, CHRISTOPHER matching BIC format).
78 synthetic all-alpha TPs lost in benchmark; real BICs with digits
(CHASUS33, BARCGB22) unaffected. Column-gated detection path available
for all-alpha BICs when column name indicates SWIFT/BIC context.

**Regressions from corpus expansion (not code changes):**
- CONTACT F1 0.831→0.787: 600 new openpii-1m shards (ADDRESS, PERSON_NAME) not detected — recall gap
- GOVERNMENT_ID F1 0.990→0.947: 150 new NATIONAL_ID shards not detected + more EIN/SSN FPs on new data

## Items Completed (7/7)

### 1. Port opaqueTokenPass (P1, S)
Three-pass `scan_text` pipeline: regex, KV secret scanner, opaque token
detection. 25+ structural FP filters (file paths, code expressions,
CamelCase identifiers, JVM bytecode, SSH fingerprints, Ethereum
addresses, etc.). PEM block detection emits one PRIVATE_KEY finding
per `-----BEGIN/END-----` block. CamelCase key-name normalisation
(`privateKey` → `private_key`). All filters mirrored in JS.

**Files:** `scan_text.py`, `secret_scanner.py`, `scanner-core.js`,
`parsers.py` (new `parse_key_values_with_spans`), `validators.js`

### 2. Text-path benchmark (P1, S)
WildChat GT built from 3,515 prompts. Prompt-level P=93.1% R=99.4%
F1=96.1%. Finding-level P=73.2% (up from ~22% at session start).
Remaining 804 FPs are ~57% genuinely ambiguous (need zone/context
awareness) and ~43% have structural markers but filters too risky.

**Files:** `scripts/rebuild_wildchat_gt.py`, `scripts/build_review_corpus.py`

### 3. Build labeled evaluation dataset (P1, S)
331 prompts human-reviewed via `prompt_reviewer.py` web tool. Auto-labels
clear-cuts (88%), surfaces edge cases (12%). 90 unreviewed prompts remain.

### 4. Wire openpii-1m (P1, S)
DVC ingest + family benchmark shard builder wired. 1,800 new shards
from openpii-1m corpus (PERSON_NAME, ADDRESS, PHONE, EMAIL).

**Files:** `shard_builder.py`

### 5. Char-class diversity boost (P1, S)
Diversity above threshold now boosts composite score (+0.05 per class).
Applied in both tieredScore (KV pass) and opaqueTokenPass. Python + JS
parity.

**Files:** `secret_scanner.py`, `scan_text.py`, `scanner-core.js`

### 6. Confidence model rethink (P1, M)
Match quality separated from column prevalence. Count multiplier
removed. Validated matches floor at 0.95. `match_ratio` available
separately via `SampleAnalysis`.

**Files:** `regex_engine.py`

### 7. Benchmark NEGATIVE corpus cleanup (P1, M)
CamelCase filter tightened (`[A-Z][a-z]+` → `[A-Z][a-z]{3,}`) to stop
false-filtering Google API keys. SWIFT_BIC validator rejects all-alpha
matches. NEGATIVE F1 0.000→1.000, FINANCIAL precision 0.838→0.996.

**Files:** `secret_scanner.py`, `validators.py`, `scanner-core.js`,
`validators.js`

## Release

- Version: `0.15.0` in `pyproject.toml`
- CHANGELOG: Sprints 13-15 entry written
- Migration guide: `docs/migrations/v0.8.0-to-v0.15.0.md`
- JS SWIFT_BIC validator ported
- Browser parity: 88% (19 stubbed validators; known gap, not regression)

**To ship:** merge sprint15/main → main, tag v0.15.0, push to trigger
Cloud Build. Dry-run release pipeline first.

## Known Gaps / Sprint 16 Candidates

1. **Zone detection** — remaining 490 FPs in text scanning need
   zone/context awareness (code block, config, log, prose). Depends on
   research/prompt-analysis S4 code detector work. User decided to wait
   for code detector unification.
2. **JS validator porting** — 19 validators still stubbed (luhn,
   iban_checksum, ssn_zeros, etc.). Causes 12% parity gap.
3. **CONTACT recall** — ADDRESS/PERSON_NAME detection gap exposed by
   openpii-1m corpus. Needs dedicated entity patterns or ML.
4. **GOVERNMENT_ID recall** — NATIONAL_ID formats not covered.
5. **90 unreviewed WildChat prompts** in GT corpus.
6. **WASM detector architecture** — Rust/WASM single-implementation
   for zone + secret + code detectors; eliminates JS/Python parity
   problem entirely.
