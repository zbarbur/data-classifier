# data_classifier — Project Context

> **Last updated:** 2026-04-10 (Sprint 1 complete)

## Status

| Metric | Value |
|---|---|
| Current sprint | 2 (planning) |
| Tests | 234 passing (0.34s local, ~19s CI) |
| CI | Green on Python 3.11, 3.12, 3.13 |
| Patterns | 43 content patterns + 15 profile rules |
| Backlog | 56 items (6 done, 50 pending) |

## Architecture

**data_classifier** is a standalone, stateless Python library for classifying sensitive data in structured database columns. Connector-agnostic — works with BigQuery, Snowflake, Postgres, or any structured data source.

### Core Modules

| Module | Purpose |
|---|---|
| `core/types.py` | All dataclasses (ColumnInput, ClassificationFinding, SampleAnalysis, etc.) |
| `engines/interface.py` | ClassificationEngine base class |
| `engines/regex_engine.py` | RE2 two-phase matching (Set screening + extraction + validators) |
| `engines/validators.py` | Luhn, SSN zeros, IPv4 reserved |
| `orchestrator/orchestrator.py` | Engine cascade, event telemetry, budget awareness |
| `profiles/__init__.py` | Profile loading (YAML, dict, bundled) |
| `profiles/standard.yaml` | Bundled default profile (15 rules, 4 categories) |
| `patterns/default_patterns.json` | Content pattern library (43 patterns) |
| `events/emitter.py` | Pluggable event handlers |

### Key Patterns

- **RE2 Set matching** — all patterns screened in one C++ pass per value
- **Two-phase matching** — Set screens, then individual patterns extract + validate
- **Confidence vs Prevalence** — confidence = "entity exists", prevalence = match_ratio
- **Category dimension** — PII / Financial / Credential / Health
- **Engine cascade** — orchestrator filters by mode + supported_categories

## Infrastructure

| Component | Details |
|---|---|
| Language | Python 3.11+ |
| Repo | https://github.com/zbarbur/data-classifier |
| CI | GitHub Actions (ruff + pytest on 3.11/3.12/3.13) |
| Linter | Ruff (line-length 120, E/F/I/N/W) |
| Test runner | pytest + pytest-asyncio |
| Regex engine | Google RE2 (linear-time, Set matching) |
| Backlog | agile-backlog CLI (YAML files in backlog/) |
| Pattern docs | Generated HTML (scripts/generate_pattern_docs.py) |

## Test Coverage

| Suite | Tests | What |
|---|---|---|
| test_patterns.py | 172 | Pattern compilation, examples, metadata (parameterized) |
| test_golden_fixtures.py | 31 | BQ compat contract (column names + rollups) |
| test_regex_engine.py | 31 | Engine behavior, confidence, masking, filtering, validators |
| **Total** | **234** | **0.34s** |

## Sprint History

| Sprint | Theme | Status | Tests | Key Deliverables |
|---|---|---|---|---|
| 1 | Bootstrap + RE2 engine | Complete | 234 | Package, RE2 engine, 43 patterns, validators, orchestrator, events, CI, test suite, migration plan |

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
| `docs/PATTERN_SOURCES.md` | Pattern sources, license/IP, gap plan |
| `docs/pattern-library.html` | Generated pattern reference |
| `docs/sprints/SPRINT1_HANDOVER.md` | Sprint 1 delivery log |
| `docs/spec/` | Full architectural spec (read-only reference) |
