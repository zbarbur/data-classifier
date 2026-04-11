# data_classifier — Project Context

> **Last updated:** 2026-04-11 (Sprint 3 complete)

## Status

| Metric | Value |
|---|---|
| Current sprint | 4 (planning) |
| Tests | 603 passing (1.28s local) |
| CI | Green on Python 3.11, 3.12, 3.13 |
| Patterns | 71 content patterns + 25 profile rules |
| Engines | 4 (column_name, regex, heuristic_stats, secret_scanner) |
| Validators | 12 (+ aws_secret_not_hex) |
| Entity types | 32 (in column_names.json) |
| Key-name patterns | 88 (in secret_key_names.json) |
| Backlog | 70+ items |
| Benchmark F1 | Column: 0.897, Secret: 0.985 |

## Architecture

**data_classifier** is a standalone, stateless Python library for classifying sensitive data in structured database columns. Connector-agnostic — works with BigQuery, Snowflake, Postgres, or any structured data source.

### Core Modules

| Module | Purpose |
|---|---|
| `core/types.py` | All dataclasses (ColumnInput, ClassificationFinding, SampleAnalysis, etc.) |
| `engines/interface.py` | ClassificationEngine base class |
| `engines/column_name_engine.py` | Column name semantics (400+ variants, fuzzy matching) |
| `engines/regex_engine.py` | RE2 two-phase matching + context boosting + stopwords + allowlists |
| `engines/heuristic_engine.py` | Cardinality, entropy, length, char class analysis (Sprint 3) |
| `engines/secret_scanner.py` | Structured secret scanner — key-name + entropy scoring (Sprint 3) |
| `engines/parsers.py` | JSON, YAML, env, code literal parsers for secret scanner |
| `engines/validators.py` | 12 validators (Luhn, SSN, IPv4, NPI, DEA, VIN, EIN, ABA, IBAN, phone, SIN Luhn, AWS not-hex) |
| `orchestrator/orchestrator.py` | Engine cascade, collision resolution, CREDENTIAL suppression |
| `config/engine_defaults.yaml` | All engine thresholds and scoring parameters (Sprint 3) |
| `profiles/__init__.py` | Profile loading (YAML, dict, bundled) |
| `profiles/standard.yaml` | Bundled default profile (25 rules, 4 categories) |
| `patterns/default_patterns.json` | Content pattern library (71 patterns) |
| `patterns/column_names.json` | Column name variants (400+, 32 entity types) |
| `patterns/secret_key_names.json` | Secret key-name dictionary (88 entries, tiered scoring) |
| `patterns/known_placeholder_values.json` | Known placeholder values for FP suppression (34) |
| `patterns/stopwords.json` | Known placeholder values for regex FP suppression |
| `events/emitter.py` | Pluggable event handlers |

### Key Patterns

- **RE2 Set matching** — all 71 patterns screened in one C++ pass per value
- **Two-phase matching** — Set screens, then individual patterns extract + validate
- **Context boosting** — per-pattern boost/suppress words adjust confidence ±0.30
- **Stopword suppression** — global + per-pattern known placeholders → hard zero
- **Column name engine** — fuzzy matching, abbreviation expansion, multi-token
- **Confidence vs Prevalence** — confidence = "entity exists", prevalence = match_ratio
- **Category dimension** — PII / Financial / Credential / Health
- **Engine cascade** — orchestrator filters by mode, highest confidence wins

## Infrastructure

| Component | Details |
|---|---|
| Language | Python 3.11+ |
| Repo | https://github.com/zbarbur/data-classifier |
| CI | GitHub Actions (ruff + pytest on 3.11/3.12/3.13) |
| Linter | Ruff (line-length 120, E/F/I/N/W) |
| Test runner | pytest + pytest-asyncio + hypothesis |
| Regex engine | Google RE2 (linear-time, Set matching) |
| Phone validation | phonenumbers library (170+ countries) |
| Docs | mkdocs + Material theme + mkdocstrings |
| Backlog | agile-backlog CLI (YAML files in backlog/) |
| Benchmarks | tests/benchmarks/ (accuracy, pattern, perf, corpus, report) |

## Test Coverage

| Suite | Tests | What |
|---|---|---|
| test_patterns.py | 288 | Pattern compilation, examples, metadata (71 patterns × 4) |
| test_column_name_engine.py | 78+ | Fuzzy matching, abbreviations, multi-token, compound table matching |
| test_heuristic_engine.py | 42+ | Signal functions, SSN/ABA detection, collision resolution |
| test_secret_scanner.py | 70+ | Parsers, scoring tiers, match types, integration |
| test_golden_fixtures.py | 31 | BQ compat contract (column names + rollups) |
| test_regex_engine.py | 33+ | Engine behavior, confidence, masking, filtering, validators, SIN Luhn |
| test_hypothesis.py | 4 | Property-based (SSN, email, CC, random strings) |
| test_python_api.py | 57+ | API contract |
| **Total** | **603** | **1.28s** |

### Benchmark Suite (not in CI — manual)

| Benchmark | Command | What |
|---|---|---|
| Pattern matching | `python3 -m tests.benchmarks.pattern_benchmark` | Per-sample TP/FP/FN on raw values |
| Column accuracy | `python3 -m tests.benchmarks.accuracy_benchmark` | Full pipeline P/R/F1 |
| Performance | `python3 -m tests.benchmarks.perf_benchmark` | Per-engine latency, input-type matrix, scaling |
| Secret detection | `python3 -m tests.benchmarks.secret_benchmark` | Per-layer P/R/F1 on 102 adversarial samples |
| Sprint report | `python3 -m tests.benchmarks.generate_report --sprint N` | Combined markdown report |

## Sprint History

| Sprint | Theme | Status | Tests | Key Deliverables |
|---|---|---|---|---|
| 1 | Bootstrap + RE2 engine | Complete | 234 | Package, RE2 engine, 43 patterns, 4 validators, orchestrator, events, CI |
| 2 | Regex hardening + column name engine + testing | Complete | 398 | 59 patterns, 11 validators, column name engine, context boosting, stopwords, benchmarks, mkdocs |
| 3 | Disambiguation + new engines + secret detection | Complete | 603 | 71 patterns, 12 validators, heuristic + secret scanner engines, collision resolution, F1 0.897 |

## Consumers

| Consumer | Status | Migration |
|---|---|---|
| BigQuery connector | Current (Sprint 27 target) | `docs/migration-from-bq-connector.md` |
| Snowflake connector | Future | Same API via ColumnInput |
| Postgres connector | Future | Same API via ColumnInput |

## Documentation Map

| Doc | Purpose |
|---|---|
| `CLAUDE.md` | Project rules, commands, code style |
| `docs/CLIENT_INTEGRATION_GUIDE.md` | API contract for connector teams |
| `docs/migration-from-bq-connector.md` | Sprint 27 migration plan |
| `docs/ROADMAP.md` | Iterations 1-4 plan |
| `docs/PATTERN_SOURCES.md` | Pattern sources, license/IP, gap plan, testing corpus strategy |
| `docs-public/` | Client-facing docs (mkdocs source) |
| `docs/sprints/SPRINT1_HANDOVER.md` | Sprint 1 delivery log |
| `docs/sprints/SPRINT2_HANDOVER.md` | Sprint 2 delivery log |
| `docs/sprints/SPRINT2_BENCHMARK.md` | Sprint 2 benchmark report |
| `docs/spec/` | Full architectural spec (read-only reference) |
