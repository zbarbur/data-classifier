# Sprint 6 Handover — Hardening + Meta-Classifier Shadow Ship

> **Date:** 2026-04-12
> **Theme:** Engine precision hardening, entity split, CI install test, meta-classifier (3 phases, shipped shadow-only)
> **Branch:** sprint6/main → merged to main
> **Tests:** 777 → **1009 passing** (+232)

## Delivered (10 items)

### 1. CI install test (P1, chore)
- `scripts/install_smoke_test.py` — fresh venv + wheel install, verifies bundled resources (yaml, json, **pkl**) and end-to-end classification
- `.github/workflows/ci.yaml` — new `install-test` job on py3.11/3.12/3.13 matrix using `python -m build --wheel` (`pip install .` masks resource bugs)
- Exists specifically to catch Sprint 5 v0.5.1-class regressions where a bundled file silently fails to ship

### 2. SSN validator enhancement (P1, feature)
- `data_classifier/engines/validators.py`: rewrote `ssn_zeros_check` with canonical SSA post-2011 randomized issuance rules
  - Area 001-899 (reject 666, 900-999 ITIN range)
  - Group 01-99, Serial 0001-9999
- New `_SSN_ADVERTISING_LIST` frozenset (12 famous marketing SSNs)
- 18 tests in `tests/test_ssn_validator.py`

### 3. US NPI Luhn validator tests (P2, feature)
- `tests/test_npi_validator.py`: 4 test classes × ~25 cases covering valid CMS NPIs (Luhn with 80840 prefix), invalid checksums, format tolerance, malformed inputs
- Existing validator code unchanged — this closed a coverage gap flagged in Sprint 5

### 4. URL / IP_ADDRESS collision pair (P2, feature)
- `data_classifier/orchestrator/orchestrator.py`: new `_suppress_url_embedded_ips` pass — URLs containing IPs suppress the IP_ADDRESS finding
- 9 tests in `tests/test_url_ip_collision.py`

### 5. DATE_OF_BIRTH_EU entity type (P2, feature)
- `data_classifier/patterns/default_patterns.json`: retargeted `dob_european` pattern from `DATE_OF_BIRTH` → `DATE_OF_BIRTH_EU`
- `data_classifier/profiles/standard.yaml`: new entity with multilingual column hints (dob_eu, geburtsdatum, date_naissance, fecha_nacimiento, data_nascita)
- **Known behavior documented:** column_name engine authority (10) suppresses regex (5) for known DOB column names — test `test_column_name_bias_is_preserved` captures this
- 12 tests in `tests/test_date_of_birth_eu.py`

### 6. Secret scanner hardening (2 items merged)
- **6a. Fast-path rejection** (P2, feature) — `secret_scanner.py`: skip KV parsing when no secret indicators present; 11 tests in `test_secret_scanner_fast_path.py`
- **6b. Gitleaks placeholder FP analysis** (P2, bug) — 37 missing placeholder suppressions added; 41 tests in `test_secret_scanner_placeholder_fps.py`
- Fixture file uses the project's **XOR encoding pattern** (from `data_classifier/patterns/__init__.py`) to avoid GitHub push protection on real Terraform Cloud token signatures

### 7. Sprint-over-sprint benchmark history (P2, chore)
- `tests/benchmarks/schema/benchmark_history.py` — JSON schema
- `tests/benchmarks/benchmark_history_io.py` — save/load/delta helpers
- `tests/benchmarks/consolidated_report.py` — trend chart + auto-delta section
- 11 tests in `test_benchmark_history.py`

### 8. Aggressive secondary suppression opt-in (P2, feature)
- `data_classifier/__init__.py`: new `aggressive_secondary_suppression: bool = False` parameter
- Thresholds: primary ≥ 0.80 AND gap ≥ 0.15 kills all secondary findings
- 9 tests in `test_aggressive_secondary_suppression.py`
- Opt-in so existing consumers (BQ) are unaffected

### 9. Meta-classifier for learned engine arbitration (P1, feature) — **3 phases, shipped shadow-only**

#### Phase 1 — Feature extraction skeleton
- `data_classifier/orchestrator/meta_classifier.py` — pure `extract_features()` (15 features), `MetaClassifierPrediction` dataclass, lazy-loading `MetaClassifier` class
- `tests/benchmarks/meta_classifier/{build_training_data,extract_features}.py` — offline pipeline
- 30+ tests in `test_meta_classifier_features.py`

#### Phase 2 — Training + three-tier evaluation
- Parallel research sessions produced:
  - `docs/research/meta_classifier/sharding_strategy.md` (525 lines, Session A)
  - `docs/research/meta_classifier/corpus_diversity.md` (386 lines, Session B)
- New corpus loaders: SecretBench, gitleaks, detect_secrets (+ NEGATIVE label for `is_secret=False` rows)
- `tests/benchmarks/meta_classifier/shard_builder.py` (552 lines) — 75 unique shards per (type, real-corpus), stratified M, without-replacement sampling with resampled tagging
- `scripts/train_meta_classifier.py` (434 lines) — LogReg + StandardScaler + 5-fold stratified CV, best-C selection, BCa 95% CI bootstrap (2000 resamples), metadata sidecar
- `tests/benchmarks/meta_classifier/evaluate.py` — LOCO + paired bootstrap + McNemar
- `data_classifier/models/meta_classifier_v1.{pkl,metadata.json}` — **7770 training rows, 24 classes, CV macro F1 = 0.916, held-out 0.918, BCa 95% CI width 0.0245**
- 31 tests in `test_meta_classifier_training.py`

#### Phase 3 — Shadow inference wiring
- `data_classifier/orchestrator/meta_classifier.py` — full `predict_shadow()` implementation, importlib.resources-based model loading
- `data_classifier/orchestrator/orchestrator.py` — shadow call + MetaClassifierEvent emit, wrapped in belt-and-suspenders try/except, `DATA_CLASSIFIER_DISABLE_META` kill switch
- `data_classifier/events/types.py` — new `MetaClassifierEvent` dataclass
- 20 tests in `test_meta_classifier_shadow.py`
- **Shadow only:** predictions are logged but never mutate `classify_columns` return values

### 10. Meta-classifier post-review hygiene (review-time fixes)
- `_ensure_loaded`: read pkl bytes *inside* the `as_file` context manager before loading — was safe on filesystem installs but leaked the contract for zipapp/pex/frozen deployments
- Install smoke test now verifies `MetaClassifier._ensure_loaded()` succeeds — catches the `models/*.pkl` packaging glob regression the pkl check previously missed

## Key Decisions

1. **Ship gate for meta-classifier was tight (F1 delta ≥ +0.02 AND CI width ≤ ±0.03)** — Phase 2 blew past it (+0.25 delta, 0.058 CI width) but…
2. **…ship shadow-only due to LOCO collapse.** Standard CV macro F1 = 0.92, leave-one-corpus-out macro F1 = 0.27-0.36. A 0.55 gap. This is a distribution-shift failure, not an overfit — the model is learning corpus fingerprints as a shortcut. Shadow inference = log predictions for offline comparison without affecting live output.
3. **Parallel research session pattern validated.** Two concurrent Claude sessions (Session A, Session B) produced independent research docs during Sprint 6 that converged into Phase 2's design. Pattern is now the default for long-running training and investigations.
4. **XOR encoding is the project standard for test fixtures tripping GitHub push protection** — the pattern already existed in `data_classifier/patterns/__init__.py` for runtime config; repurposed for test data in item 6b after push protection blocked the first `f666c28` commit.
5. **`NEGATIVE` label for the meta-classifier** — generic pseudo-class covering every row that is legitimately not any tracked entity. Avoids the per-corpus "negative" granularity that inflates class count.
6. **Promotion model** — Phase 2 candidate is on disk as `meta_classifier_v1.pkl` but lives behind the shadow path only. A future sprint item "Promote meta-classifier v2 (post-Q3 feature fix)" can flip it to live after the LOCO investigation lands.

## Architecture Changes

### New subsystems
- **Meta-classifier** — new first-class subsystem with its own feature schema, training pipeline, serialized artifacts, shadow inference wiring, and dedicated event type. Completely optional (via `[meta]` extra) and never affects the live classification path.
- **Parallel experiment infrastructure** — `docs/experiments/meta_classifier/queue.md` defines a file-ownership contract for parallel Claude sessions running on their own git worktrees

### Public API additions
- `classify_columns(..., aggressive_secondary_suppression: bool = False)` — opt-in stricter suppression
- `MetaClassifierEvent` via event emitter — new observability signal (off by default)
- Environment variables: `DATA_CLASSIFIER_DISABLE_META`, `DATA_CLASSIFIER_DISABLE_ML`

### Backward compatibility
- Default `aggressive_secondary_suppression=False` → existing callers unaffected
- Shadow inference cannot crash live path (every exception returns None)
- pkl is optional — library imports cleanly without `[meta]` extra

## Known Issues

1. **Meta-classifier LOCO collapse (0.55 gap).** Shadow-only ship. Root cause unknown — leading hypothesis is `heuristic_avg_length` corpus-leaking (coefficient magnitude 488, 2x the runner-up). Diagnostic experiment Q3 queued in `docs/experiments/meta_classifier/queue.md`.
2. **~67% of Phase 2 training rows are resampled** (CREDENTIAL/NEGATIVE pools were smaller than 75 unique shards). Session A research said to exclude resampled rows from CI calculations. Phase 2 did not. Q2 experiment queued to re-run the bootstrap with exclusion and validate the +0.25 / 0.058 numbers.
3. **Phase 2 model predicts PERSON_NAME for canonical email columns.** Training data quality issue. Acceptable because shadow-only. Documented in queue.md.
4. **DATE_OF_BIRTH / DATE_OF_BIRTH_EU confusion pair.** Per-class F1 on held-out test: DOB = 0.527, DOB_EU = 0.828. Worst confusion pair in the 24-class output space. Q4 experiment queued to measure whether merging the labels improves macro F1.

## Lessons Learned

1. **Parallel research sessions beat serial execution for long investigations.** Two sessions producing independent research docs in parallel (sharding + corpus diversity) delivered converging recommendations that reshaped Phase 2's training design. Cost: ~15 min of coordination overhead. Benefit: didn't block the main sprint thread and got peer-review-quality analysis for free.
2. **Subagents catch spec bugs the main thread misses.** Subagents flagged (a) the DOB-EU column-name-authority suppression (item 5), and (b) a spurious SSN test failure during Phase 1 dispatch that turned out to be env-specific. When a subagent has its own unit tests passing, trust them over a one-off smoke test typed in the main thread.
3. **Ruff/format-check/pytest CI is fast enough to run after every edit.** 10 seconds for 1009 tests means running CI after each post-review fix adds no friction and catches regressions instantly.
4. **Empirical verification beats theoretical correctness reviews.** A pre-merge code review flagged the `as_file` context-manager hygiene as "critical." Building a wheel and testing end-to-end showed the installed path works on real filesystem installs. The fix still landed (forward-compatible hygiene) but the severity was correctly downgraded — don't fix a panic alarm, fix a hygiene alarm.
5. **Three-phase delivery reduces dispatch risk.** Phase 1 (skeleton), Phase 2 (training), Phase 3 (wiring) each had a clear deliverable and independent test surface. If Phase 2 had caught fire, Phase 1 was still shippable as a pure library addition with no functional change.

## Test Coverage

| Area | Tests added | Cumulative |
|---|---|---|
| SSN validator | 18 | |
| NPI validator | 25 | |
| URL/IP collision | 9 | |
| DOB_EU | 12 | |
| Secret scanner fast-path | 11 | |
| Secret scanner placeholders | 41 | |
| Benchmark history | 11 | |
| Aggressive suppression | 9 | |
| Corpus loader (meta) | 12 | |
| Meta features | 30 | |
| Meta training | 31 | |
| Meta shadow | 20 | |
| **Total added** | **+232** | **1009** |

CI: 1009 passed, lint clean, format clean, ~10s local, matrix py3.11/3.12/3.13 green.

## Recommendations for Sprint 7

### Carryover from Sprint 6 experiments queue
- **Q3 — LOCO feature ablation** (P1, 1-2 hours, parallel session). Diagnose which feature(s) leak. Most important follow-up for meta-classifier.
- **Q2 — Resampled-row CI exclusion** (P1, 30-60 min, parallel session). Validate the +0.25 / 0.058 numbers hold without resampled rows in the CI calculation.
- **E4 — Binning continuous features** (P2, depends on Q3 ruling avg_length is the leak).
- **Q4 — DOB merge experiment** (P2, 30-60 min). Measure macro F1 delta if we collapse `DATE_OF_BIRTH` + `DATE_OF_BIRTH_EU` back to one class.

### Production backlog items ready for Sprint 7
- **Presidio comparator benchmark** — spec ready, venv set up on machine, was deferred from Sprint 6
- **Cloud DLP comparator benchmark** — spec ready, deferred from Sprint 6
- **Batch classification in orchestrator** — performance optimization deferred from Sprint 6, 204ms → 30-50ms potential on multi-column workloads
- **Meta-classifier v2 promotion** (contingent on Q3 landing a clear fix)
- **Dead `_SSN_ADVERTISING_LIST` entries cleanup** — 10 entries in `987-65-43xx` range are unreachable behind the area > 899 rule (warning from Sprint 6 code review)

### Sprint 7 theme options
- **Option A: "Compare and calibrate"** — Presidio + Cloud DLP comparators, Meta-classifier Q3 fix + promotion. Theme: we learn where we stand vs the market and act on it.
- **Option B: "Batch + research act-upon"** — Batch classification perf work + execute all queued experiments + promote whatever fixes survive. Theme: performance + execute the research we banked.
- **Option C: "Foundations"** — something deeper on training data diversity (E7: full Nemotron + Ai4Privacy pull), structural features (E8), domain adaptation. Theme: fix the meta-classifier root cause, not symptoms.

Discussion pending — user explicitly requested Sprint 7 planning happen in the main thread.

## Research Workflow Contract (introduced this sprint)

Parallel research sessions execute in git worktrees off a long-lived `research/meta-classifier` branch (created at Sprint 6 close). They touch only training-side files; production code changes flow through normal sprint items that cite research results. See `docs/experiments/meta_classifier/queue.md` for the full workflow and outstanding experiments.
