# data_classifier — Project Context

> **Last updated:** 2026-04-16 (Sprint 12 complete — meta-classifier v5 + Option A train/serve-skew fix + RED safety audit → shadow-only v0.12.0)

## Status

| Metric | Value |
|---|---|
| Current sprint | 12 (closed) → 13 (planning) |
| Release | **v0.8.0** published to Google Artifact Registry (`dag-bigquery-dev` / us-central1, Python repo `data-classifier`); ONNX model tarball (254 MB) in AR Generic repo `data-classifier-models`. Sprint 9 + 10 + 11 changes not yet tagged — `v0.11.0` tag pending merge to main + BQ consumer coordination. |
| Tests | **1531 passing** + 1 skipped + 1 xfailed (+11 vs Sprint 11) (~44s local with `[meta]`) |
| CI | `lint-and-test` green on 3.11/3.12/3.13; `lint-and-test-ml` green (install + import + construct, kill-switch on); `install-test` green |
| Patterns | **77** content patterns + 26 profile rules |
| Engines | **5** (column_name, regex, heuristic_stats, secret_scanner, gliner2) + meta-classifier **v5** (shadow, schema v5 with 49 features / 47 kept — adds `validator_rejected_credential_ratio` + `has_dictionary_name_match_ratio` on top of v3). **Option A train/serve-skew fix** (Sprint 12): `predict_shadow` now accepts raw `engine_findings` dict, threaded identically through training and inference — symmetric-by-construction. GLiNER2 uses S1 NL-prompt wrapping (Sprint 10) and skips non-text data_type columns (Sprint 10). |
| Validators | **17** (+3 Sprint 11: Bitcoin base58check/bech32, Ethereum checksum, placeholder-credential) |
| Entity types | **35** in column-name dictionary (CREDENTIAL split into API_KEY / PRIVATE_KEY / PASSWORD_HASH / OPAQUE_SECRET in Sprint 8). **Family taxonomy shipped Sprint 11 as new public API field:** 13 families (`CONTACT`, `FINANCIAL`, `HEALTH`, `GOVERNMENT_ID`, `CREDENTIAL`, `NETWORK`, `DEVICE`, `GEO`, `DEMOGRAPHIC`, `VEHICLE`, `CRYPTOCURRENCY`, `OPAQUE`, `NEGATIVE`) auto-populated on every `ClassificationFinding`. |
| Key-name patterns | **178** (Sprint 10 baseline; unchanged in Sprint 11 beyond the `id_token` / `token_secret` match_type tightening) |
| Corpora | **7** OSI-compatible: Nemotron-PII (CC BY 4.0), SecretBench (MIT), gitleaks (MIT), detect_secrets (Apache-2.0), synthetic (MIT/Faker), gretelai/gretel-pii-masking-en-v1 (Apache 2.0, Sprint 9), gretelai/synthetic_pii_finance_multilingual (Apache 2.0, Sprint 10 loader — **Sprint 11 wired into accuracy_benchmark CLI**). Ai4Privacy pii-masking-300k/400k retired Sprint 9. |
| Backlog | Sprint 12 closed with 5 items shipped (Items #1/#2 features + DOB_EU retire + stopwords XOR + safety-analysis-memo, all `code_reviewed: true`). 2 items retired with evidence: `sprint12-shadow-directive-promotion-gate` (RED verdict) + `gated-meta-classifier-architecture-q8-continuation` (wrong framing — softmax-is-wrong-primitive). 3 Sprint 13 items filed: `sprint13-column-shape-router` (P1), `sprint13-per-value-gliner-aggregation` (P1), `sprint13-opaque-token-branch-tuning` (P2). Release item `sprint-12-v0-12-0-release-and-bq-consumer-bump` stays at `doing` pending branch push + merge sign-off. |
| **Accuracy (synthetic, Sprint 8)** | Macro F1 0.915, Micro 0.897, Primary-Label 96.3% (unchanged, synthetic not re-run in Sprint 11) |
| **Accuracy (real-corpus blind, Sprint 11)** | **Nemotron 0.833 (+0.059 vs Sprint 10, above Sprint 9 baseline), Gretel-EN 0.611 (flat), Gretel-finance 0.806 (NEW)** (50 samples/col, 2026-04-15, git b05c896). Nemotron recovery driven by Sprint 11 item #8 credential-shape partitioner — 81 JWT values moved from OPAQUE_SECRET to new API_KEY column where regex engine's `jwt_token` matches score as TPs. |
| **Accuracy (real-corpus named, Sprint 11)** | **Nemotron 1.000 (+0.077 vs Sprint 10), Gretel-EN 0.917 (flat), Gretel-finance 0.917 (NEW)** |
| **Accuracy (family-level, Sprint 12 shipped)** | **cross_family_rate 0.44%** (down from Sprint 11's 5.85%, **13.3× reduction**), **family_macro_f1 0.9945** (+0.0659), within-family mislabels 322 → 3 (107× reduction). Measured on 9,870-shard shadow evaluation (300 shards removed due to DOB_EU subtype retirement). Baseline committed at `docs/research/meta_classifier/sprint12_family_benchmark.json`. In-distribution only — heterogeneous columns (logs/chat/base64) are a known gap documented in `docs/research/meta_classifier/sprint12_safety_audit.md`, addressed in Sprint 13 by the column-shape router. |
| **Per-column regex coverage (historical)** | Ai4Privacy PHONE: 16.3% → 94.5% (Sprint 7 measurement on retired Ai4Privacy corpus; see `docs/process/LICENSE_AUDIT.md`); Ai4Privacy CREDENTIAL: 0% → 98.6% (same). Not re-measured against Gretel-EN; the patterns still work, the corpus is different. |
| **Meta-classifier (honest CV, Sprint 9)** | **cv_mean_macro_f1 = 0.1940 ± 0.0848, best_c = 1.0** under `StratifiedGroupKFold` (M1 promotion, 2026-04-13). Replaces the Sprint 6 claim of 0.916 / best_c = 100, which was inflated by corpus-fingerprint leakage via `heuristic_avg_length`. See `docs/learning/sprint9-cv-shortcut-and-gated-architecture.md` for the full diagnosis. |
| **Meta-classifier (honest blind delta, Sprint 9)** | **+0.2432** vs 5-engine live baseline (n=848, CI width 0.0519, ship gates pass). Supersedes the E10 +0.191 number which was pre-Gretel + pre-M1. Going forward, cite +0.2432, not +0.191. |
| **Meta-classifier (LOCO, Sprint 9)** | **Mean ~0.17** across 5 corpora (detect_secrets 0.11, gitleaks 0.07, gretel_en 0.08, nemotron 0.27, secretbench 0.33). This is the **honest generalization number** — what the model does on a held-out corpus it's never seen. The reported CV and held-out test numbers are higher because they use same-distribution sampling. Cite LOCO going forward for product claims. |
| **Performance (Sprint 8 baseline)** | 78.9 ms/col p50 with ML on 12 col × 10 samples (ad-hoc snapshot, see `docs/benchmarks/history/sprint_8.json`). Warmup 7.46s. |
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
| 9 | Detection quality lift + BQ production-unblock | Complete | 1222 | **Gretel-EN corpus ingest** (Apache 2.0, 60k rows, 47 domains, 7th training corpus), **ai4privacy removal** (non-OSI license retired, `docs/process/LICENSE_AUDIT.md` codifies the verification discipline), **M1 meta-classifier CV fix promoted** (`StratifiedKFold → StratifiedGroupKFold`, honest CV 0.1940 / best_c=1.0, blind delta +0.2432, LOCO ~0.17), **observability-gaps closed** (`get_active_engines()` + `health_check()` + loud ImportError fallback), retro-fit Sprint 8 benchmarks into `consolidated_report` generator, `perf_benchmark --quick` mode (stalled→~20s), tar-safety pre-scan hardening, cloudbuild SA token process-substitution + xtrace suppression, v2 inference infrastructure salvage (threshold plumbing fix + `descriptions_enabled` flag + ONNX auto-discovery guard). **Fastino promotion BLOCKED** on blind-corpus regression (−0.13 Gretel-EN / −0.19 Nemotron), deferred to Sprint 10 pending `research/gliner-context` context-injection work. **Learning memo** `docs/learning/sprint9-cv-shortcut-and-gated-architecture.md` written as capstone deliverable. |
| 10 | Detection-uplift chain + secret-dict expansion + data diversification | Complete | 1374 | **S1 NL-prompt wrapping** shipped in `gliner_engine.py` (`_build_ner_prompt(column, chunk)` replaces raw `_SAMPLE_SEPARATOR.join`) — blind corpora non-regression held. **GLiNER data_type pre-filter** skips non-text SQL types (INTEGER/FLOAT/DATE/...) in both `classify_column` and `classify_batch`, eliminating a whole class of numeric-column FPs. **Secret-key-name dictionary +90 net-new entries** (88 → 178) via `scripts/ingest_credential_patterns.py` harvesting Kingfisher (Apache 2.0), gitleaks (MIT), Nosey Parker (Apache 2.0) with pinned SHAs and full per-entry attribution in `docs/process/CREDENTIAL_PATTERN_SOURCES.md`. **Gretel-finance corpus ingest** (`gretelai/synthetic_pii_finance_multilingual`, Apache 2.0, 56k rows, 7 languages — loader/fixture/shard-builder ready, CLI wiring deferred Sprint 11). **BQ context-fields written verification** (`docs/process/BQ_INTEGRATION_STATUS.md` captures verbal confirmation from 2026-04-13). **Closed by subsumption:** `gliner2-over-fires-organization-on-numeric-dash-inputs` via item #1's regression test. **Fastino promotion (stretch)** ATTEMPTED and REVERTED — Gretel-EN −0.198, Nemotron −0.295, structural failure mode (fastino fires PHONE@0.92+ on numeric columns); Sprint 11 retry investigation item filed. **ai4privacy openpii-1m correction** filed (CC-BY-4.0, contradicts Sprint 9 blanket-ban). Nemotron blind −0.047 measurement artifact from Sprint-8 CREDENTIAL-split label drift in corpus loader, not a real detection regression. |
| 12 | Feature lift + directive-promotion safety audit → shadow-only ship | Complete | 1531 | **Meta-classifier v5** (schema v5, 49 features / 47 kept): Item #1 `validator_rejected_credential_ratio` + Item #2 `has_dictionary_name_match_ratio`. **Option A train/serve-skew fix**: `predict_shadow(engine_findings=...)` threads raw engine dict identically in training and inference — symmetric-by-construction. **Family benchmark (shadow)**: cross_family_rate 0.0585 → **0.0044** (13.3× reduction), family_macro_f1 0.9286 → **0.9945**. **DOB_EU subtype retired** (Option B: emission removed, `DATE_OF_BIRTH_EU → DATE` alias kept in `ENTITY_TYPE_TO_FAMILY` for family-metric coherence; proper v6 retrain filed as Sprint 13 item). **Phase 5b safety audit RED** on 6/6 heterogeneous fixtures: 3 high-confidence wrong-class collapses (base64 → VIN @ 0.934, chat → CREDENTIAL @ 1.000, Kafka → CREDENTIAL @ 0.999). Structural finding: softmax is the wrong primitive for multi-label columns where `argmax` forces mutual exclusivity. **Shadow→directive flip DEFERRED**; ships v0.12.0 shadow-only; BQ stays on v0.8.0 until directive flip lands. **Sprint 13 reframe**: 3 items filed (column-shape router + per-value GLiNER + opaque-token tuning) — heuristic routing to existing tools instead of training new specialized classifiers. `sprint12_safety_audit.py` reproducible harness committed. Lesson: always pair feature-extraction changes with a parity test that runs the full orchestrator and asserts training-vs-inference feature-vector equivalence. |
| 11 | Measurement honesty + Sprint 10 cleanup + meta-classifier v3 / family taxonomy | Complete | 1520 | **Two-track sprint**: 8-item main-session cleanup + 14-commit scanner-tuning-batch (PR #12). **Nemotron named 0.923→1.000 (+0.077)** and **Nemotron blind 0.774→0.833 (+0.059, above Sprint 9 baseline)** from item #1 (corpus-loader taxonomy refresh: stale CREDENTIAL → 4 subtypes across Nemotron/Gretel-EN/_DETECT_SECRETS) + item #8 (Nemotron credential-shape partitioner: 81 JWT values routed from OPAQUE_SECRET → new API_KEY column). **Gretel-finance wired into accuracy_benchmark CLI** (first formal measurement: 0.917 named / 0.806 blind). **Corpus-loader entity-taxonomy drift lint** with CI entrypoint + `_SKIP_MAPS_WITH_EXPIRY` machine-readable expiry rule. **Secret-scanner `id_token`/`token_secret` match_type tightened** from `substring` → `word_boundary`. **`test_meta_classifier_training.py` env-leak hygiene fix**. **Engines Reference §5A (329 lines) in CLIENT_INTEGRATION_GUIDE.md** — canonical per-engine doc + 7-pass orchestrator pipeline, all symbol-only citations for drift resistance. **Fail-fast stretch-item dispatch protocol** (`docs/process/FAIL_FAST_STRETCH_DISPATCH.md`) codifying Sprint 10 Lesson #3. **Meta-classifier v2 → v3** shipped (schema v3 adds Chao-1 bias-corrected cardinality + heuristic dictionary-word-ratio; v3 +0.39 subtype macro F1 over v2). **New public API field `ClassificationFinding.family`** + `FAMILIES` / `family_for()` / `ENTITY_TYPE_TO_FAMILY` exports (13-family taxonomy, non-breaking). **New structural validators**: Bitcoin base58check + bech32, Ethereum checksum, placeholder-credential. **Tier-1 credential pattern-hit gate** (observability-only, `GateRoutingEvent`). **Canonical family accuracy benchmark** adopted as new quality gate: `cross_family_rate 5.85%` (8.2× reduction from 47.71% baseline), `family_macro_f1 0.9286` on 10,170-shard shadow. **4 Sprint 12 backlog items** filed from family A/B analysis. Diagnostic-spike lesson: the "scanner over-fires" P1 bug was a mis-attribution — secret_scanner produces zero findings on col_7; fix was corpus-side (item #8), not engine-side. **Review remediation**: 2 must-fix + 7 yellow findings addressed pre-merge. Zero merge conflicts between the two tracks despite both editing `CLIENT_INTEGRATION_GUIDE.md`. |

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
