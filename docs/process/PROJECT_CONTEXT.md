# data_classifier — Project Context

> **Last updated:** 2026-04-10 (Sprint 2 complete)

## Status

| Metric | Value |
|---|---|
| Current sprint | 3 (planning) |
| Tests | 398 passing (0.94s local) |
| CI | Green on Python 3.11, 3.12, 3.13 |
| Patterns | 59 content patterns + 25 profile rules |
| Engines | 2 (column_name, regex) |
| Validators | 11 |
| Entity types | 32 (in column_names.json) |
| Backlog | 65+ items |
| Benchmark F1 | Pattern: 0.793, Column: 0.765 |

## Architecture

**data_classifier** is a standalone, stateless Python library for classifying sensitive data in structured database columns. Connector-agnostic — works with BigQuery, Snowflake, Postgres, or any structured data source.

### Core Modules

| Module | Purpose |
|---|---|
| `core/types.py` | All dataclasses (ColumnInput, ClassificationFinding, SampleAnalysis, etc.) |
| `engines/interface.py` | ClassificationEngine base class |
| `engines/column_name_engine.py` | Column name semantics (400+ variants, fuzzy matching) |
| `engines/regex_engine.py` | RE2 two-phase matching + context boosting + stopwords + allowlists |
| `engines/validators.py` | 11 validators (Luhn, SSN, IPv4, NPI, DEA, VIN, EIN, ABA, IBAN, phone) |
| `orchestrator/orchestrator.py` | Engine cascade, event telemetry, budget awareness |
| `profiles/__init__.py` | Profile loading (YAML, dict, bundled) |
| `profiles/standard.yaml` | Bundled default profile (25 rules, 4 categories) |
| `patterns/default_patterns.json` | Content pattern library (59 patterns) |
| `patterns/column_names.json` | Column name variants (400+, 32 entity types) |
| `patterns/stopwords.json` | Known placeholder values for FP suppression |
| `events/emitter.py` | Pluggable event handlers |

### Key Patterns

- **RE2 Set matching** — all 59 patterns screened in one C++ pass per value
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
| test_patterns.py | 236 | Pattern compilation, examples, metadata (59 patterns × 4) |
| test_column_name_engine.py | 60+ | Fuzzy matching, abbreviations, multi-token, no-match |
| test_golden_fixtures.py | 31 | BQ compat contract (column names + rollups) |
| test_regex_engine.py | 31 | Engine behavior, confidence, masking, filtering, validators |
| test_hypothesis.py | 4 | Property-based (SSN, email, CC, random strings) |
| **Total** | **398** | **0.94s** |

### Benchmark Suite (not in CI — manual)

| Benchmark | Command | What |
|---|---|---|
| Pattern matching | `python -m tests.benchmarks.pattern_benchmark` | Per-sample TP/FP/FN on raw values |
| Column accuracy | `python -m tests.benchmarks.accuracy_benchmark` | Full pipeline P/R/F1 |
| Performance | `python -m tests.benchmarks.perf_benchmark` | Latency, throughput, scaling |
| Sprint report | `python -m tests.benchmarks.generate_report --sprint N` | Combined markdown report |

## Sprint History

| Sprint | Theme | Status | Tests | Key Deliverables |
|---|---|---|---|---|
| 1 | Bootstrap + RE2 engine | Complete | 234 | Package, RE2 engine, 43 patterns, 4 validators, orchestrator, events, CI |
| 2 | Regex hardening + column name engine + testing | Complete | 398 | 59 patterns, 11 validators, column name engine, context boosting, stopwords, benchmarks, mkdocs |

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
