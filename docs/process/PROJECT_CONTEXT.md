# data_classifier — Project Context

> **Last updated:** 2026-04-28 (Sprint 16 complete — CONTACT + GOVERNMENT_ID recall, EU national-ID phase 1, within-family specificity sort)

## Status

| Metric | Value |
|---|---|
| Current sprint | 16 (closed) → 17 (planning) |
| Release | **v0.16.0** published to Google Artifact Registry (Cloud Build `8e2eb02e` succeeded 2026-04-28). |
| Tests | **2407 passing** + 20 skipped + 1 xfailed (~56s local with `[ml]`) |
| CI | `lint-and-test` (3.11/3.12/3.13), `lint-and-test-ml` (3.12), `install-test` (3.11/3.12/3.13), `browser-parity` — all green. 3 of 4 jobs migrated to `uv` (Sprint 16). |
| Patterns | **+7 EU GOVERNMENT_ID** patterns (Sprint 16): DE Steuer-ID, FR NIR, ES DNI, ES NIE, IT Codice Fiscale, NL BSN, AT SVNR. |
| Engines | **5** (column_name, regex, heuristic_stats, secret_scanner, gliner2) + meta-classifier **v6** (live on structured_single, schema v5 with 49 features). Column-shape router: 3 branches — `structured_single`, `free_text_heterogeneous`, `opaque_tokens`. |
| Validators | **+7 EU checksum validators** (Sprint 16): `german_steuerid`, `french_nir`, `spanish_dni`, `spanish_nie`, `italian_codice_fiscale`, `dutch_bsn`, `austrian_svnr`. JS port deferred (known parity gap). |
| Entity types | **Family taxonomy:** 13 families. **`ENTITY_SPECIFICITY` map** (Sprint 16) drives within-family primary-label tie-break (cross-family ordering remains pure-confidence). |
| Two detection paths | **Structured:** `classify_columns`. **Unstructured:** `scan_text` (Python) / browser scanner (JS) — parity gated. |
| Corpora | 7 OSI-compatible + DVC-tracked WildChat-1M + openpii-1m (Sprint 15). |
| **Accuracy (family-level, Sprint 16, no-ML)** | **family_macro_f1 0.9732** (+0.0255 vs S15), **cross_family_rate 8.08%** (-2.58pp). Sprint gate metric `shadow.cross_family_rate` 0.3245 → **0.3139**. |
| **Accuracy (ML-enabled reference)** | family_macro_f1 0.9903, cross_family_rate 2.91%. CONTACT F1 0.966 (+0.170), ADDRESS subtype F1 0.942 (+0.300), PERSON_NAME F1 0.948 (+0.302). |
| **Browser scanner** | Python–JS parity CI gated. 87% WildChat parity (25 Python-only OPAQUE_SECRET = known gap, port-opaquetokenpass in S17 backlog). |
| **Distribution** | Wheel: AR Python repo. Model: AR Generic repo (urchade-gliner-multi-pii-v1, unchanged since S8). Browser: `npm run release` → zip. Datasets: DVC + GCS (`gs://data-classifier-datasets`). |
| **Dev tooling** | `uv` for venv + install (Sprint 16, 40-87% .venv size reduction); `gliner2==1.2.6` requires manual install (not in pyproject extras). |

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
| 9 | Detection quality lift + BQ production-unblock | Complete | 1222 | **Gretel-EN corpus ingest** (Apache 2.0, 60k rows, 47 domains, 7th training corpus), **ai4privacy removal** (non-OSI license retired, `docs/process/LICENSE_AUDIT.md` codifies the verification discipline), **M1 meta-classifier CV fix promoted** (`StratifiedKFold → StratifiedGroupKFold`, honest CV 0.1940 / best_c=1.0, blind delta +0.2432, LOCO ~0.17), **observability-gaps closed** (`get_active_engines()` + `health_check()` + loud ImportError fallback), retro-fit Sprint 8 benchmarks into `consolidated_report` generator, `perf_benchmark --quick` mode (stalled→~20s), tar-safety pre-scan hardening, cloudbuild SA token process-substitution + xtrace suppression, v2 inference infrastructure salvage (threshold plumbing fix + `descriptions_enabled` flag + ONNX auto-discovery guard). **Fastino promotion BLOCKED** on blind-corpus regression (−0.13 Gretel-EN / −0.19 Nemotron), deferred to Sprint 10 pending `research/gliner-context` context-injection work. **Learning memo** `docs/learning/sprint9-cv-shortcut-and-gated-architecture.md` written as capstone deliverable. |
| 10 | Detection-uplift chain + secret-dict expansion + data diversification | Complete | 1374 | **S1 NL-prompt wrapping** shipped in `gliner_engine.py` (`_build_ner_prompt(column, chunk)` replaces raw `_SAMPLE_SEPARATOR.join`) — blind corpora non-regression held. **GLiNER data_type pre-filter** skips non-text SQL types (INTEGER/FLOAT/DATE/...) in both `classify_column` and `classify_batch`, eliminating a whole class of numeric-column FPs. **Secret-key-name dictionary +90 net-new entries** (88 → 178) via `scripts/ingest_credential_patterns.py` harvesting Kingfisher (Apache 2.0), gitleaks (MIT), Nosey Parker (Apache 2.0) with pinned SHAs and full per-entry attribution in `docs/process/CREDENTIAL_PATTERN_SOURCES.md`. **Gretel-finance corpus ingest** (`gretelai/synthetic_pii_finance_multilingual`, Apache 2.0, 56k rows, 7 languages — loader/fixture/shard-builder ready, CLI wiring deferred Sprint 11). **BQ context-fields written verification** (`docs/process/BQ_INTEGRATION_STATUS.md` captures verbal confirmation from 2026-04-13). **Closed by subsumption:** `gliner2-over-fires-organization-on-numeric-dash-inputs` via item #1's regression test. **Fastino promotion (stretch)** ATTEMPTED and REVERTED — Gretel-EN −0.198, Nemotron −0.295, structural failure mode (fastino fires PHONE@0.92+ on numeric columns); Sprint 11 retry investigation item filed. **ai4privacy openpii-1m correction** filed (CC-BY-4.0, contradicts Sprint 9 blanket-ban). Nemotron blind −0.047 measurement artifact from Sprint-8 CREDENTIAL-split label drift in corpus loader, not a real detection regression. |
| 12 | Feature lift + directive-promotion safety audit → shadow-only ship | Complete | 1531 | **Meta-classifier v5** (schema v5, 49 features / 47 kept): Item #1 `validator_rejected_credential_ratio` + Item #2 `has_dictionary_name_match_ratio`. **Option A train/serve-skew fix**: `predict_shadow(engine_findings=...)` threads raw engine dict identically in training and inference — symmetric-by-construction. **Family benchmark (shadow)**: cross_family_rate 0.0585 → **0.0044** (13.3× reduction), family_macro_f1 0.9286 → **0.9945**. **DOB_EU subtype retired** (Option B: emission removed, `DATE_OF_BIRTH_EU → DATE` alias kept in `ENTITY_TYPE_TO_FAMILY` for family-metric coherence; proper v6 retrain filed as Sprint 13 item). **Phase 5b safety audit RED** on 6/6 heterogeneous fixtures: 3 high-confidence wrong-class collapses (base64 → VIN @ 0.934, chat → CREDENTIAL @ 1.000, Kafka → CREDENTIAL @ 0.999). Structural finding: softmax is the wrong primitive for multi-label columns where `argmax` forces mutual exclusivity. **Shadow→directive flip DEFERRED**; ships v0.12.0 shadow-only; BQ stays on v0.8.0 until directive flip lands. **Sprint 13 reframe**: 3 items filed (column-shape router + per-value GLiNER + opaque-token tuning) — heuristic routing to existing tools instead of training new specialized classifiers. `sprint12_safety_audit.py` reproducible harness committed. Lesson: always pair feature-extraction changes with a parity test that runs the full orchestrator and asserts training-vs-inference feature-vector equivalence. |
| 11 | Measurement honesty + Sprint 10 cleanup + meta-classifier v3 / family taxonomy | Complete | 1520 | Meta-classifier v3, family taxonomy (13 families), Nemotron named 1.000, blind 0.833, canonical family benchmark adopted |
| 13 | Column-shape router + per-value GLiNER + S0 precision | Complete | 1711 | 3-branch column-shape router, per-value GLiNER aggregation, opaque-token handler, S0 precision fixes, shadow cross_family 0.0004 |
| 14 | Directive flip + multi-label scoring + browser PoC + detection quality | Complete | 2272 | Meta-classifier v6 live (F1 0.8300→0.9509), checksum-wins collision resolution, per-pattern findings, scan_text API, browser PoC (77 patterns, P99 0.70ms, 20KB gz), Python–JS parity CI gate, DVC + GCS dataset infrastructure, corpus data quality fixes |
| 15 | Dataset foundation + scoring honesty + text-path precision | Complete | 2343 | v0.15.0 release. Three-pass `scan_text` pipeline (regex + KV scanner + opaque token), 25+ structural FP filters, PEM block detection, char-class diversity boost, confidence model rethink (single-match validated patterns floor at 0.95, count multiplier removed), SWIFT_BIC validator tightened (NEGATIVE F1 0.000→1.000), openpii-1m DVC ingest (+1800 shards), WildChat GT (3,515 prompts, P=93.1% R=99.4% F1=96.1%), CamelCase key-name normalisation. cross_family_rate 0.1182→**0.1066**, family_macro_f1 0.8566→**0.9477**. |
| 16 | CONTACT + GOVERNMENT_ID recall (no public API changes) | Complete | 2407 | v0.16.0 release. **GLiNER dedup** uses Jaccard evidence overlap (≥0.50) instead of global type hierarchy. **GOVERNMENT_ID phase 1** — 6 EU countries (DE Steuer-ID, FR NIR, ES DNI/NIE, IT Codice Fiscale, NL BSN, AT SVNR), 7 patterns + 7 checksum validators. **Within-family specificity sort** (`ENTITY_SPECIFICITY` map) — ADDRESS wins over PERSON_NAME within CONTACT regardless of confidence; cross-family ordering preserves pure-confidence. **Gap-baseline bug** caught in code review (used position-0 confidence after specificity reorder; fixed to use true max). Tooling: dev environment + 3 of 4 CI jobs migrated to `uv`. cross_family_rate 0.1066→**0.0808** (no-ML), shadow gate 0.3245→**0.3139**, family_macro_f1 0.9477→**0.9732** (no-ML) / **0.9903** (ML reference). WildChat GT completion deferred to S17. |

## Consumers

| Consumer | Status | Migration | Integration status |
|---|---|---|---|
| BigQuery connector | Current (Sprint 27 target) | `docs/migration-from-bq-connector.md` | `docs/process/BQ_INTEGRATION_STATUS.md` — per-field verification of `ColumnInput` context fields (`table_name`, `dataset`, `schema_name`, `data_type`, `description`) |
| Snowflake connector | Future | Same API via ColumnInput | — |
| Postgres connector | Future | Same API via ColumnInput | — |

## Documentation Map

| Doc | Purpose |
|---|---|
| `CLAUDE.md` | Project rules, commands, code style |
| `docs/CLIENT_INTEGRATION_GUIDE.md` | API contract for connector teams |
| `docs/migration-from-bq-connector.md` | Sprint 27 migration plan |
| `docs/process/BQ_INTEGRATION_STATUS.md` | Per-field verification of BQ-populated `ColumnInput` context fields |
| `docs/process/FAIL_FAST_STRETCH_DISPATCH.md` | Stretch-item dispatch protocol — revert-and-refile playbook (Sprint 10 lesson #3) |
| `docs/ROADMAP.md` | Iterations 1-4 plan |
| `docs/PATTERN_SOURCES.md` | Pattern sources, license/IP, gap plan, testing corpus strategy |
| `docs-public/` | Client-facing docs (mkdocs source) |
| `docs/sprints/SPRINT1_HANDOVER.md` | Sprint 1 delivery log |
| `docs/sprints/SPRINT2_HANDOVER.md` | Sprint 2 delivery log |
| `docs/sprints/SPRINT2_BENCHMARK.md` | Sprint 2 benchmark report |
| `docs/sprints/SPRINT{3..12}_HANDOVER.md` | Per-sprint delivery logs |
| `docs/research/meta_classifier/sprint12_safety_audit.md` | Sprint 12 Phase 5b capacity / architecture / heterogeneous RED verdict |
| `docs/research/meta_classifier/sprint12_family_benchmark.json` | Sprint 12 family-level shadow baseline (0.0044 cross_family_rate) |
| `docs/spec/` | Full architectural spec (read-only reference) |
