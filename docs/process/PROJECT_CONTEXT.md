# data_classifier — Project Context

> **Last updated:** 2026-04-13 (Sprint 8 complete — first published wheel `v0.8.0`, Cloud Build release pipeline, ONNX model distribution, credential 4-way split, E10 baseline corrections)

## Status

| Metric | Value |
|---|---|
| Current sprint | 8 (closing) → 9 (planning) |
| Release | **v0.8.0 published to Google Artifact Registry** (`dag-bigquery-dev` / us-central1, Python repo `data-classifier`); ONNX model tarball (254 MB) in AR Generic repo `data-classifier-models`; fresh-venv install validated end-to-end |
| Tests | **1197 passing** + 1 skipped (+64 vs Sprint 7) (~36s local with `[meta]`) |
| CI | `lint-and-test` green on 3.11/3.12/3.13; new `lint-and-test-ml` job (install + import + construct, kill-switch on); `install-test` green |
| Patterns | **73** content patterns + 26 profile rules |
| Engines | **5** (column_name, regex, heuristic_stats, secret_scanner, gliner2) + meta-classifier (shadow) |
| Validators | **14** (PEM private-key scanner + hash-scheme detector added in Sprint 8 credential split) |
| Entity types | **36** (CREDENTIAL split into API_KEY / PRIVATE_KEY / PASSWORD_HASH / OPAQUE_SECRET in Sprint 8) |
| Key-name patterns | 88 |
| Backlog | 70+ items + 7 new Sprint 9 candidates parked at Sprint 8 close |
| **Accuracy (synthetic, Sprint 8)** | **Macro F1 0.915, Micro 0.897, Primary-Label 96.3%** (50 samples/type, 22 entity types, 4 FPs / 1 FN — all match known filed gaps) |
| **Accuracy (real-corpus blind)** | Nemotron 0.8974 (Ai4Privacy retired, Gretel-EN baseline pending Sprint 9 re-run) |
| **Accuracy (named)** | Both corpora: 1.000 Macro F1 |
| **Per-column regex coverage** | **Ai4Privacy PHONE: 16.3% → 94.5%** (Sprint 7 measurement on retired Ai4Privacy corpus; see LICENSE_AUDIT.md), **Ai4Privacy CREDENTIAL: 0% → 98.6%** (Sprint 7 measurement on retired Ai4Privacy corpus; see LICENSE_AUDIT.md) |
| **Meta-classifier (CV)** | **0.916 is a methodology artifact**; honest LOCO ~0.30 |
| **Meta-classifier (LOCO)** | 0.27–0.36 — structural gap per Q3 §6 (hypothesis A+C); E10 GLiNER-features experiment regressed LOCO further (−0.031 mean) — NOT promoted |
| **Meta-classifier (honest blind delta)** | **+0.191** vs 5-engine live baseline (E10, 2026-04-13). The Sprint 6 "+0.257" number was vs a 4-engine baseline with GLiNER disabled — see SPRINT6_HANDOVER.md "Honest baseline correction — E10" |
| **Performance (Sprint 8 baseline)** | **78.9 ms/col p50** with ML on 12 col × 10 samples (ad-hoc snapshot, see `docs/benchmarks/history/sprint_8.json`). Warmup 7.46s. Replaces the older 207ms/col PROJECT_CONTEXT figure as the baseline; numbers not directly comparable due to different corpus shape. |
| **ML share** | GLiNER2 = **99.8%** of pipeline latency (Sprint 8 measurement) |
| **Pattern library** | Column-gated patterns via `requires_column_hint` + `column_hint_keywords` (Sprint 7); credential subtype taxonomy (Sprint 8) |
| **Benchmark comparators** | Presidio comparator infrastructure shipped (Sprint 7); Cloud DLP comparator deferred from Sprint 8 (scope swap to model distribution) |
| **Distribution** | Wheel: AR Python repo (Cloud Build trigger `data-classifier-release`, 2nd gen, fires on `^v.*$`). Model: AR Generic repo, decoupled from package version, downloaded via `python -m data_classifier.download_models` (4-tier auth discovery: flag → env → metadata SA → gcloud) |

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
| `engines/validators.py` | 14 validators (Luhn, SSN, IPv4, NPI, DEA, VIN, EIN, ABA, IBAN, phone, SIN Luhn, AWS not-hex, random_password) |
| `orchestrator/orchestrator.py` | Engine cascade, collision resolution, CREDENTIAL suppression |
| `config/engine_defaults.yaml` | All engine thresholds and scoring parameters (Sprint 3) |
| `profiles/__init__.py` | Profile loading (YAML, dict, bundled) |
| `profiles/standard.yaml` | Bundled default profile (25 rules, 4 categories) |
| `patterns/default_patterns.json` | Content pattern library (73 patterns) |
| `patterns/column_names.json` | Column name variants (400+, 32 entity types) |
| `patterns/secret_key_names.json` | Secret key-name dictionary (88 entries, tiered scoring) |
| `patterns/known_placeholder_values.json` | Known placeholder values for FP suppression (34) |
| `patterns/stopwords.json` | Known placeholder values for regex FP suppression |
| `events/emitter.py` | Pluggable event handlers |

### Key Patterns

- **RE2 Set matching** — all 73 patterns screened in one C++ pass per value
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
| 4 | Collisions + model registry + real corpora | Complete | 700 | Collision resolution, model registry, honest baseline on real corpora (F1 0.18-0.46 blind) |
| 5 | Engine weighting + ML engine + production deployment | Complete | 777 | Authority weighting, sibling analysis, GLiNER2 ML engine, ONNX deployment, v0.5.2 → BQ integration |
| 6 | Hardening + meta-classifier shadow | Complete | 1009 | SSN/NPI validators, DOB_EU split, secret scanner FP fixes, CI install test, meta-classifier (3 phases, shadow-only), parallel research workflow |
| 7 | Compare & measure | Complete | 1133 | SSN advertising cleanup, international phone 16.3%→94.5%, column-gated random_password 0%→98.6%, Presidio comparator infrastructure, M1 methodology correction (docs), worktree isolation rule |
| 8 | Ship it: stabilize, release, prep credentials | Complete | 1197 | **First published wheel `v0.8.0` to Google Artifact Registry** (Cloud Build pipeline, ~60s release), ONNX model distribution decoupled from package version (`download_models` CLI + AR Generic repo, 254MB tarball), CREDENTIAL split into 4 subtypes (API_KEY/PRIVATE_KEY/PASSWORD_HASH/OPAQUE_SECRET), `lint-and-test-ml` CI matrix job (install/import/construct verification, kill-switch permanent until WIF), `test_ssn_in_samples` ML regression diagnosed and pinned to regex-only, E10 baseline correction (+0.257 → +0.191), CHANGELOG.md introduced with forward-only versioning |

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
