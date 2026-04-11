# Sprint 3 Handover — Disambiguation, New Engines, Secret Detection

> **Date:** 2026-04-11
> **Theme:** SSN/ABA disambiguation, heuristic statistics engine, structured secret scanner, benchmark hardening
> **Branch:** sprint3/main (13 commits)

## Delivered

### Heuristic Statistics Engine (NEW — 3rd engine)
- Analyzes column sample distributions: cardinality, entropy, length, character class
- Pure signal functions (testable independently): `compute_cardinality_ratio`, `compute_shannon_entropy`, `compute_length_stats`, `compute_char_class_ratios`, `compute_char_class_diversity`
- SSN detection: high cardinality + uniform 9-digit → SSN (confidence 0.82-0.85)
- ABA detection: low cardinality + uniform 9-digit → ABA_ROUTING (confidence 0.85)
- All thresholds loaded from `config/engine_defaults.yaml`, not hardcoded
- Engine order=3, structured mode only
- 35+ tests

### Structured Secret Scanner (NEW — 4th engine)
- Detects secrets in structured content (JSON, YAML, env files, code literals)
- Three-tier scoring model:
  - **Definitive** (key score ≥ 0.90): Key name alone sufficient, value plausibility check
  - **Strong** (key score 0.70-0.89): Needs relative entropy ≥ 0.5 OR 3+ char classes
  - **Contextual** (key score < 0.70): Needs relative entropy ≥ 0.7 AND 3+ char classes
- 88 key-name patterns with match types (substring, word_boundary, suffix) and tiers
- Relative entropy scoring (actual/max for charset — hex, base64, alphanumeric, full)
- False positive prevention: word-boundary matching, value plausibility check, anti-indicators, 34 known placeholders
- 4 parsers: JSON (nested flattening), YAML, env, code literal
- All parameters configurable via `engine_defaults.yaml`
- Engine order=4, structured + unstructured modes
- 70+ tests

### Collision Resolution
- Pairwise collision resolution in orchestrator: SSN↔ABA, SSN↔SIN, ABA↔SIN, NPI↔PHONE, DEA↔IBAN
- CREDENTIAL suppression: when a more specific entity type has higher confidence, generic CREDENTIAL is dropped
- Configurable gap threshold (0.15 default)

### Credential Pattern Expansion (24 → 36 patterns)
- 12 new service-specific patterns: DigitalOcean (PAT + OAuth), Azure Storage, Cloudflare, HuggingFace, Sentry, Supabase, Terraform Cloud, Vercel, Linear, Netlify, Fly.io
- AWS secret key validator: rejects pure-hex strings (git SHAs, checksums)

### ColumnInput Extension
- `schema_name` field added (backward compatible)
- Table context boosting: column name engine boosts confidence +0.05 when table name contextually supports entity type (46 table keywords → PII/Health/Financial)

### Bug Fixes
- Canadian SIN: new `sin_luhn_check` validator for 9-digit values (was using credit card Luhn with 13-digit minimum)
- VIN corpus: replaced invalid check-digit value with 5 valid VINs from different manufacturers

### Configuration System
- `data_classifier/config/engine_defaults.yaml` — centralized config for all engine thresholds
- `data_classifier/patterns/secret_key_names.json` — 88 key-name entries (score, match_type, tier)
- `data_classifier/patterns/known_placeholder_values.json` — 34 placeholder values
- All scoring parameters documented with defaults in SECRET_DETECTION.md

### Benchmarks
- **Secret detection benchmark** (`secret_benchmark.py`): 102 adversarial samples, per-layer P/R/F1, obfuscated values for GitHub push protection, HTML viewer
- **Performance benchmark** expanded: all 4 engines, input-type variation matrix (plain digits, plain text, JSON KV, env KV)
- Benchmark commands added to sprint config as standard sprint closure step

### Backlog Grooming
- 53 backlog items tagged with roadmap iteration (iter2/iter3/iter4/future)
- 8 detailed Sprint 4 items created for benchmark methodology and collision fixes

### Documentation
- `docs/SECRET_DETECTION.md` — comprehensive feature doc (scoring model, FP prevention, configuration, parameter reference, limitations)
- Added to mkdocs site at Guides > Secret Detection

## Benchmark Results (Sprint 3 Final)

### Column-Level (full pipeline, 37 columns, 3,700 samples)

| Metric | Sprint 2 | Sprint 3 | Change |
|---|---|---|---|
| Precision | 0.634 | **0.839** | +32.3% |
| Recall | 0.963 | 0.963 | same |
| **F1** | 0.765 | **0.897** | +17.3% |
| TP / FP / FN | 26 / 15 / 1 | 26 / 5 / 1 | -10 FP |

### Secret Detection (102 adversarial samples)

| Metric | Value |
|---|---|
| Precision | 1.000 |
| Recall | 0.971 |
| **F1** | **0.985** |
| TP / FP / FN | 33 / 0 / 1 |
| Known limitation | MongoDB URI (needs Layer 3 parser) |

### Performance (37 columns, 100 samples each)

| Engine | Time | % of pipeline |
|---|---|---|
| Column name | 0.13ms | <1% |
| Regex (RE2) | 14.97ms | 13% |
| Heuristic (NEW) | 0.74ms | 1% |
| Secret scanner (NEW) | 95.36ms | **82%** |
| Full pipeline | ~111ms | 100% |

**Note:** Secret scanner is the performance bottleneck. Fast-path rejection (skip parsing when no KV indicators) is backlogged for Sprint 4.

### Remaining Column-Level FPs (5)

| FP | Root cause | Fix |
|---|---|---|
| ABA → SSN | Regex confidence > column name, no cardinality signal in benchmark | Engine priority weighting |
| NPI → PHONE (×2) | Same — regex PHONE confidence > NPI | Engine priority weighting |
| Numeric IDs → SSN | No column name match, random 9-digit numbers | Expected — no context |
| DOB_EU → DOB | EU DD/MM format classified as generic DOB | Entity type separation |

## Tests

| Suite | Tests | What |
|---|---|---|
| test_patterns.py | 288 | Pattern compilation, examples (71 patterns × 4) |
| test_column_name_engine.py | 78+ | Fuzzy matching + compound table matching |
| test_heuristic_engine.py | 42+ | Signal functions + SSN/ABA detection + collision resolution |
| test_secret_scanner.py | 70+ | Parsers + scoring + tiers + match types + integration |
| test_regex_engine.py | 33+ | Engine behavior, validators, SIN Luhn |
| test_golden_fixtures.py | 31 | BQ compat contract |
| test_hypothesis.py | 4 | Property-based |
| test_python_api.py | 57+ | API contract |
| **Total** | **603** | **1.28s** |

## Decisions Made

1. **Entropy is a secondary signal, not primary.** Standalone entropy detection produces too many FPs on natural text, UUIDs, and hex strings. The secret scanner requires key-name evidence + entropy, not entropy alone. The heuristic engine's CREDENTIAL rule was removed for this reason.
2. **Tiered scoring replaces multiplication.** High key-name score (password, api_key) bypasses entropy — `password="admin123"` is detected even with low entropy. Contextual keys (hash, salt, nonce) need strong value evidence.
3. **Relative entropy over absolute thresholds.** `actual_entropy / max_for_charset` normalizes across charsets. A hex string at 97% of max is highly suspicious; an alphanumeric string at 53% is not.
4. **Word-boundary matching for ambiguous patterns.** `auth` matches `auth_token` but not `author`. `key` matches `api_key` (suffix) but not `keyboard`.
5. **Value plausibility check for definitive tier.** Even with a strong key name, prose text ("8 characters minimum"), dates, URLs, and config values ("true", "enabled") are not credentials.
6. **All parameters in config.** Every scoring threshold, tier boundary, and gate value is in `engine_defaults.yaml`. No hardcoded magic numbers in engine code.
7. **Benchmark must be adversarial.** A perfect 1.000 score is a red flag — the test set is too easy. The redesigned benchmark includes near-miss keys, encoded non-secrets, and ambiguous cases.
8. **Ambiguous keys (hash, salt, nonce) correctly defer.** These need higher-level engines (table context, sibling columns, ML) to disambiguate. The secret scanner correctly says "I'm not confident enough."

## Open Threads (Carry to Sprint 4)

### 1. Secret Scanner Performance
82% of pipeline cost. Needs fast-path rejection: check for KV indicators (`=`, `:`, `{`, `"`) before running 4 parsers. Backlogged.

### 2. Benchmark Methodology
Current benchmark uses synthetic Faker data and micro F1. Needs real-world corpora (Ai4Privacy, Nemotron, SecretBench) and macro F1 per entity type. 8 backlog items created.

### 3. Engine Priority Weighting
Column name engine is correct on NPI/ABA columns but regex engine has higher confidence for the wrong type. Need orchestrator-level logic: "when column name engine and regex disagree, weight column name higher."

### 4. Structural Secret Parsers (Layer 3)
No detection for: SQL grammar (`IDENTIFIED BY`), HTTP headers (`Authorization: Bearer`), CLI arguments (`--password`), connection string URIs (`mongodb://user:pass@host`). Backlogged.

### 5. AWS Secret Key Pattern
40-char `[A-Za-z0-9/+=]{40}` is too broad even with hex validator. Consider requiring context (`aws_secret` nearby) or removing standalone pattern.

## Sprint 4 Backlog Items Created

| Item | Priority | Complexity |
|---|---|---|
| Benchmark methodology: industry-standard evaluation | P1 | M |
| Three-way SSN/ABA/SIN collision resolution | P1 | S |
| NPI vs PHONE collision resolution | P1 | S |
| DEA vs IBAN collision resolution | P1 | S |
| Benchmark reporting: macro F1, per-entity F1, primary-label | P1 | S |
| Integrate real-world PII corpus | P1 | M |
| Research external secret detection corpora | P1 | — |
| Structural secret parsers (Layer 3) | P1 | L |
| Secret scanner fast-path rejection | P2 | S |
| DATE_OF_BIRTH_EU entity type | P2 | M |
| ML-optimized scoring parameters | P2 | L |
| AWS secret key pattern redesign | P2 | S |

## Commits

| # | Hash | Description |
|---|---|---|
| 1 | b801585 | chore: start Sprint 3 — Disambiguation & New Engines |
| 2 | 4081e90 | feat: ColumnInput schema_name + table-context boosting |
| 3 | b1f7ba3 | feat: extend ColumnInput (code review cleanup) |
| 4 | 8ccc23f | fix: VIN test corpus |
| 5 | 4248d3c | fix: Canadian SIN Luhn validator |
| 6 | a159fcb | feat: heuristic statistics engine |
| 7 | 0a51b3c | feat: SSN vs ABA collision resolution |
| 8 | fc5357f | fix: code review — heuristic engine |
| 9 | 814d4d6 | feat: structured secret scanner |
| 10 | 9a13dd8 | fix: code review — secret scanner |
| 11 | c5195d0 | chore: backlog grooming |
| 12 | 09f0946 | feat: scanner redesign, benchmarks, collision resolution, docs (squashed) |
| 13 | 3fa9370 | fix: code review — parameters to config |
| 14 | ffa361a | docs: parameter reference update |
