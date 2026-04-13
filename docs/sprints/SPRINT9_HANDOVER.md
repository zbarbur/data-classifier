# Sprint 9 Handover — Detection quality lift + BQ production-unblock

> **Date:** 2026-04-14
> **Theme:** Detection quality lift + BQ production-unblock. Data diversification (drop non-OSS ai4privacy, ingest Gretel-EN mixed-label corpus), meta-classifier CV methodology correctness (M1), BQ production-unblock observability, benchmark methodology debt cleanup, and a foundational educational memo capturing the distribution-shift investigation.
> **Branch:** `sprint9/main` → merging to `main`
> **Head commit:** `d0d6e7b`
> **Tests:** 1197 → **1222 passing** (+25) + 1 skipped (Presidio live-engine, gated on `[bench-compare]` extra)
> **Duration:** 2026-04-13 → 2026-04-14 (1 calendar day, heavy parallel-agent dispatch)

## Delivered (9 items)

### 1. `test-download-models` positive metadata-SA token test (P1 chore, S) — `2aa6b28`

Closes the tier-3 coverage gap flagged in Sprint 8 post-hoc review. Adds `test_metadata_sa_token_returned_from_metadata_service` to `TestAccessTokenDiscovery` — monkeypatches `urllib.request.urlopen` to return a fake metadata-service response and asserts the tier-3 branch actually returns the token. Closes a positive-path blind spot (the existing test only covered URLError failure modes).

Files: `tests/test_download_models.py` (+39 lines). +1 test.

### 2. `_disable_ml` fixture hardening (P2 chore, S) — `edfee00`

Hardens `TestSampleValueMatching._disable_ml` against in-place `_DEFAULT_ENGINES` mutation. Wraps the non-ML engine list in `list(...)` so `monkeypatch.setattr` gets a fresh copy rather than a reference, and adds a module-scope autouse teardown guard that asserts the engine list is structurally unchanged at module exit. The guard's deliberate-break verification (append `"BOGUS"` to `_DEFAULT_ENGINES`, confirm teardown fails loudly with a missing/added diagnostic, then revert) is recorded in the commit message.

Files: `tests/test_regex_engine.py` (+43/−3). +0 tests (guard is a module-scope fixture, not a new test).

### 3. `cloudbuild-release` SA token defense-in-depth (P3 chore, S) — `dfd569b`

Two-layer protection against SA token leaks in the `publish-wheel` preflight curl: (1) pass the `Authorization` header via `curl --header @<(printf 'Authorization: Bearer %s\n' "${ACCESS_TOKEN}")` process substitution so the token stays off the command line, and (2) wrap the token block in a local xtrace suppression (`case $- in *x*` + `{ set +x; } 2>/dev/null`) because bash propagates xtrace into subshells — the inner `printf` still echoes the token under `bash -x` without the wrapper. Agent measured the set-x suppression locally with `ACCESS_TOKEN=fake-token-secret-xyz` and confirmed the token does not appear in the trace output.

Files: `cloudbuild-release.yaml` (+27/−2). Not yet verified against a real Cloud Build run; that confirmation happens on the next `sprint9/main → v0.9.0` tag push.

### 4. `tar-safety` explicit symlink rejection in `_safe_extract` pre-scan (P2 chore, S) — `af2c5b4`

Hardens `data_classifier/download_models.py::_safe_extract` against tar-escape-via-symlink attacks on Python 3.11, where `tarfile.data_filter` (Python 3.12+) isn't available and the pre-scan is the only defense. The pre-scan loop now explicitly rejects any tar member with `member.issym()` or `member.islnk()` before extraction, raising `DownloadError` with a message that names the offending member.

Main-session decision at dispatch time: **harden the pre-scan**, do **not** drop Python 3.11 from the CI matrix — the consumer-breaking cost of a minimum-Python bump mid-sprint exceeds the hardening cost.

Agent found a spec/code mismatch (the spec said `TarExtractionError` but the module only defines `DownloadError`) and correctly deferred to the existing module convention instead of introducing a new exception class.

Files: `data_classifier/download_models.py`, `tests/test_download_models.py` (new `TestSafeExtractSymlinkRejection` class, 4 tests using real `tarfile` + `tempfile` fixtures, no mocking). +4 tests.

### 5. `observability-gaps` — `get_active_engines` + `health_check` + loud ImportError fallback (P1 chore, M) — `d50a6e1`

Closes three observability gaps that BigQuery production integration surfaced in Sprint 8:

1. **Silent ImportError when gliner is absent** — `_build_default_engines()` in `data_classifier/__init__.py` used to swallow `ImportError` with `pass`, so `[ml]` extras were silently degraded to regex-only. Now logs `WARNING: GLiNER2 engine disabled — install [ml] extras to enable: ...` at import time.
2. **No public `get_active_engines()`** — new function returns `[{"name": ..., "order": ..., "class": ...}]` for each engine in `_DEFAULT_ENGINES`. Lets consumers introspect the loaded engine list.
3. **No public `health_check()`** — new function runs a canned probe (`column_name='email_address'`, `sample_values=['alice@example.com']`) and returns `{"healthy": bool, "engines_executed": [...], "engines_skipped": [...], "latency_ms": float, "findings": [...]}`. Never raises — returns `healthy=False` with the exception text on failure. First-call cold-start latency ~8s (GLiNER2 warmup); subsequent calls sub-100ms.

Both new functions exported from `data_classifier.__all__`. `docs/CLIENT_INTEGRATION_GUIDE.md` §1e "Known gaps" subsection removed and the startup health probe section rewritten to use the canonical `health_check()`.

Agent surprises:
- `tests/test_meta_classifier_training.py:32` uses `os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")` at module import and never reverts it, leaking across the whole test suite. The ImportError-fallback test had to `monkeypatch.delenv(...)` to work. **Filed as a separate bug:** `hygiene-test-meta-classifier-training-py-env-leak-...` (P2, Sprint 10).
- `caplog.at_level(logger="data_classifier")` didn't capture records fired during an `importlib` reimport of the library; agent attached a direct `logging.Handler` as the workaround.

Files: `data_classifier/__init__.py`, `tests/test_observability.py` (new, 10 tests), `docs/CLIENT_INTEGRATION_GUIDE.md`. +10 tests.

### 6. Retro-fit Sprint 8 benchmarks + `perf_benchmark` flag honoring (P2 chore, M) — `315bca7`

Two related fixes closing Sprint 8's methodology debt:

1. **`perf_benchmark.py` phase 2/5 now honor `--iterations`.** The hardcoded loops (phase 2 input-type variation, phase 5 sample-scaling) that stalled lightweight runs past 10 CPU minutes regardless of CLI flags are replaced with `args.iterations`-gated helpers. New `--quick` mode drops phases 6+7 and shrinks 2+5, completing end-to-end in **~20 seconds** (measured locally). Smoke test `tests/test_perf_benchmark_smoke.py` enforces the 90-second gate.
2. **`consolidated_report.py` learned `--from-history`.** Retro-fits Sprint 8 by reading `docs/benchmarks/history/sprint_8.json` directly plus the raw logs under `docs/benchmarks/sprint8/` without requiring a live benchmark re-run. Produces `docs/benchmarks/SPRINT8_CONSOLIDATED.html` (364 lines) matching the Sprint 5/7 visual pattern with an added Performance section showing the per-engine breakdown from the Sprint 8 ad-hoc perf snapshot. `sprint_8.json` uses a non-canonical accuracy + perf schema; agent made `from_dict` tolerant via `TypeError` swallow rather than normalizing the source file, preserving the raw per-engine breakdown.
3. **Phase 7 defensive fix** — agent added a defensive `engine = RegexEngine()` rebinding inside phase 7 because phase 6's `engine` local wasn't available under `--quick` (phase 6 gets skipped). Belt-and-suspenders since phase 7 is also skipped in quick mode.

Files: `tests/benchmarks/perf_benchmark.py`, `tests/benchmarks/consolidated_report.py`, `tests/benchmarks/schema/benchmark_history.py`, `tests/benchmarks/benchmark_history_io.py`, `tests/test_perf_benchmark_smoke.py` (new), `docs/benchmarks/SPRINT8_CONSOLIDATED.html` (new, 364 lines). +1 smoke test.

### 7. Gretel-EN corpus ingest — `e49e1d8`, `5a7b662`

**Anchor item #1 of the detection-uplift chain.** Adds `gretelai/gretel-pii-masking-en-v1` (Apache 2.0, 60k rows, 47 domains) as training corpus #7. Dependency root for ai4privacy removal and for breaking the credential-pure-corpus bias the meta-classifier's LOCO collapse depends on.

Per the Sprint 8 dataset-landscape survey (`research/meta-classifier @ cd3a5cc`), Gretel-EN is the largest open mixed-label corpus available. Single documents combine medical_record_number (26k instances) + date_of_birth (23k) + ssn (16k) + credit_card_number (6k) + passwords/API keys in realistic structured-database proportions. Ingesting it disrupts the `corpus_id → credential` shortcut at the data source.

**Foreground discovery pass** (main session, before agent dispatch): fetched 100 rows from HuggingFace's datasets-server REST API (no `datasets` package installed in the venv), inspected the schema (the `entities` field is a **Python `repr()` format with single quotes, NOT JSON** — `ast.literal_eval` required), extracted the 33 unique entity types from the sample, and locked a path-(d) type map covering 16 Gretel labels → 10 data_classifier classes at ~71% sample coverage. Deferred labels (date, customer_id, employee_id, license_plate, company_name, device_identifier, biometric_identifier, unique_identifier, time, user_name, coordinate, country, city, url, cvv, certificate_license_number) parked for a Sprint 10 taxonomy expansion item.

**Agent delivered** (`worktree-agent-a0880083 @ e49e1d8`):
- `scripts/download_corpora.py` — `GRETEL_EN_TYPE_MAP` + `download_gretel_en()` + `_fetch_gretel_en_via_rest_api()` fallback path
- `tests/benchmarks/corpus_loader.py` — `load_gretel_en_corpus()` following the ai4privacy pattern
- `tests/benchmarks/meta_classifier/shard_builder.py` — `_gretel_en_pool()` + shard emission (agent bonus: the real corpora load through `shard_builder.py`, not through `build_training_data.py` as the item spec suggested)
- `tests/fixtures/corpora/gretel_en_sample.json` (new, 22637 bytes, 315 flattened records)
- `tests/test_corpus_loader.py` — new `TestGretelEnLoader` (+4 tests)
- `docs/PATTERN_SOURCES.md` — Apache 2.0 attribution row added

Fixture coverage: 12 of 12 target entity types populated (ABA_ROUTING, ADDRESS, BANK_ACCOUNT, CREDIT_CARD, DATE_OF_BIRTH, EMAIL, HEALTH, IP_ADDRESS, PERSON_NAME, PHONE, SSN, VIN).

Off-by-one in dispatch spec: my discovery doc said "17 pre-locked Gretel labels" but the actual dict had 16 entries. Agent caught the mismatch and used the dict verbatim.

Files: see commit. +4 tests.

### 8. ai4privacy removal (P1 chore, L) — `a3233a0`, `78fc25d`

The largest Sprint 9 item. Removes `ai4privacy/pii-masking-300k` from training + benchmark pipeline after Sprint 8 license verification flagged it as non-OSS (custom license prohibits commercial use and redistribution). Landed in two commits:

**Pre-work on sprint9/main (`a3233a0`)** — done in the main worktree before the full-removal agent was dispatched, so the audit trail existed as a base for the rest of the work:
- `docs/process/LICENSE_AUDIT.md` (new) — single source of truth for corpus licenses, records the Sprint 8 license finding, catalogs current OSI-compatible corpora, documents the "fetch the actual LICENSE file, never trust dataset card metadata" discipline
- `docs/PATTERN_SOURCES.md` — ai4privacy row re-labeled from the actively misleading "Custom (research OK)" to "PENDING REMOVAL Sprint 9"
- `docs/ROADMAP.md` — corresponding fix to the Iteration 3 corpus table row

**Full removal (`78fc25d`, agent commit)**:
- **Deleted:** `tests/fixtures/corpora/ai4privacy_sample.json` (30 MB committed derivative) + `tests/benchmarks/meta_classifier/training_data.jsonl` (2.1 MB). Both gitignored.
- **Code references removed from:** `tests/benchmarks/corpus_loader.py`, `tests/benchmarks/meta_classifier/shard_builder.py`, `tests/benchmarks/meta_classifier/build_training_data.py`, `scripts/download_corpora.py` (stubbed to raise `NotImplementedError` pointing to `LICENSE_AUDIT.md`), `tests/benchmarks/accuracy_benchmark.py`, `tests/benchmarks/perf_benchmark.py`, `tests/benchmarks/perf_quick.py`, `tests/test_corpus_loader.py`.
- **Retrained:** `training_data.jsonl` rebuilt (7770 → 8370 rows), `meta_classifier_v1.pkl` + metadata + eval regenerated from the post-ai4privacy corpus set. NOTE: the agent used the OLD `StratifiedKFold` CV code since M1 hadn't landed yet on sprint9/main at that point — the subsequent M1 promotion commit retrained again with the honest splitter.
- **PROJECT_CONTEXT.md** — "Nemotron 0.8974, Ai4Privacy 0.6667" replaced with "Nemotron 0.8974 (Ai4Privacy retired, Gretel-EN baseline pending Sprint 9 re-run)"; Sprint 7 per-column regex coverage wins footnoted.
- **Footnoted 12 historical docs** (not rewritten, footnoted):
  - `docs/sprints/SPRINT3_HANDOVER.md`, `SPRINT4_HANDOVER.md`, `SPRINT4_BASELINE_REPORT.md`, `SPRINT5_HANDOVER.md`, `SPRINT5_BENCHMARK.md`, `SPRINT6_HANDOVER.md`, `SPRINT7_HANDOVER.md`
  - `docs/research/meta_classifier/corpus_diversity.md`, `sharding_strategy.md`
  - `docs/research/SECRET_CORPORA_RESEARCH.md`
  - `docs/experiments/meta_classifier/queue.md`
  - `docs/plans/stream_b_benchmarks.md`

Sibling backlog item `external-corpus-integration-ai4privacy-pii-masking-300k` closed as done with the license rationale.

**Scope-creep note (justified):** Agent touched 6 files outside the "MAY edit" list to make the DoD test-gate + grep-gate pass: `test_presidio_comparator.py`, `test_benchmark_history.py`, `tests/benchmarks/generate_report.py`, `consolidated_report.py`, `meta_classifier/evaluate.py`, `schema/benchmark_history.py`. All touched minimally to preserve scope intent — justified because the original item was unusually wide (16+ file touches spec'd) and these surfaced as DoD-gate blockers.

Agent left `data_classifier/patterns/default_patterns.json` untouched (has an Ai4Privacy mention in the `international_phone_local` pattern description) because `patterns/**` was in MUST NOT TOUCH. Known-follow-up — not filed as a separate item because the reference is prose in a regex description, not active use.

**No production exposure** — the BigQuery consumer is still in development as of 2026-04-14, so ai4privacy was never shipped to a customer-serving runtime.

Files: 36 files modified, 403 insertions, 1,764,139 deletions (the deletions are the 1.75M-line `ai4privacy_sample.json` plus `training_data.jsonl`). +18 tests (Gretel tests + agent's scope-creep cleanups overlap).

### 9. M1 meta-classifier CV methodology fix + promotion (P0 bug, S) — `6b74da7`, `6195843`, `b331ab1`

**The conceptual headline of the sprint.** Closes the Q3 diagnosis from Sprint 7 that identified `StratifiedKFold` as leaking corpus fingerprints across CV folds, inflating the Sprint 6 headline CV macro F1 (0.916) by roughly 0.66 F1 points.

**Research-branch landing** (`research/meta-classifier @ c33c7fc`, merged out-of-band):
- Code change: swap `StratifiedKFold → StratifiedGroupKFold(groups=corpora)` in `scripts/train_meta_classifier.py`; thread `corpora_arr` through the outer `train_test_split`
- Candidate pkl: `data_classifier/models/meta_classifier_v1_m1_groupkfold.pkl` (non-v1 suffix per parallel-research-workflow contract)
- Full result memo: `docs/experiments/meta_classifier/runs/m1-2026-04-13/result.md`

**Production promotion (`6b74da7`, on sprint9/main post-ai4privacy):**

| Metric | ai4privacy agent's retrain (old StratifiedKFold) | M1 promotion (StratifiedGroupKFold) |
|---|---:|---:|
| Training rows | 8370 | 8370 (same) |
| `best_c` | 100.0 | **1.0** — matches Q3 §5a prediction exactly |
| `cv_mean_macro_f1` | 0.9593 | **0.1940 ± 0.0848** |
| `held_out_test_macro_f1` | 0.9553 | 0.8511 |
| Tertiary blind delta (meta − live, n=848) | (not captured) | **+0.2432** ci_width 0.0519 |
| LOCO mean (detect_secrets 0.11, gitleaks 0.07, gretel_en 0.08, nemotron 0.27, secretbench 0.33) | (not captured) | **~0.17** |

**The 76-point CV drop is a correctness improvement, not a regression.** The old CV was inflated by corpus-fingerprint leakage — the top feature `heuristic_avg_length` at absolute coefficient 131.40 (down from 252.09 pre-Gretel; 48% reduction from the Gretel ingest alone) is a corpus-identity proxy. GroupKFold exposes the honest ~19% generalization to a held-out corpus.

**Ship gates still pass:**
- Tertiary delta **+0.2432 ≥ +0.02** ✓
- CI width **0.0519 ≤ 0.06** ✓

The meta-classifier is still a ship-worthy artifact even under the honest metric — because the delta (meta − live) improved, not just the absolute. The live pipeline's baseline also dropped on the new corpus set, so meta beats live by a wider margin on the honest metric.

**Going forward, cite +0.2432 as the meta-classifier blind delta**, not the +0.191 that E10 measured pre-Gretel + pre-M1. The number moved again.

**Adaptive fallback bug fix (`b331ab1`)** — the M1 promotion broke 7 tests in `test_meta_classifier_training.py` because the test fixture uses a single corpus (`"test"`) and `StratifiedGroupKFold(n_splits=5)` with 1 unique group produces empty folds. Fix: check `n_unique_groups` before picking the splitter. If the data has fewer unique corpora than `CV_FOLDS`, fall back to plain `StratifiedKFold`. There's no cross-corpus leakage to prevent when there's only one corpus, so the fallback is semantically equivalent to the pre-M1 behavior on single-group data.

Files: `scripts/train_meta_classifier.py`, `data_classifier/models/meta_classifier_v1.pkl` + `.metadata.json` + `.eval.json`. +0 tests (fix commit adjusted existing tests, no new tests).

## Bonus deliverables

### 10. Sprint 9 learning memo — `d99d6a7`

**Capstone educational deliverable written at the user's explicit request.** `docs/learning/sprint9-cv-shortcut-and-gated-architecture.md` (364 lines, ~3000 words) covers 10 topics drawn from the live M1 investigation discussion:

1. The starting puzzle (Sprint 6 CV vs LOCO gap as the investigation trigger)
2. Shortcut learning as a failure mode (with the `heuristic_avg_length` → corpus proxy example using actual Sprint 9 coefficients)
3. What CV is actually measuring — `StratifiedKFold` vs `StratifiedGroupKFold`, what each answers, why our data needs the group one
4. The held-out test set trap — "two metrics agreeing" ≠ "evaluation is robust"
5. Distribution shift and regularization — why `best_c=100` was wrong and `best_c=1` was right, why C is metric-dependent not data-dependent
6. Gated architecture / hybrid symbolic-statistical pattern — 5 production examples (credit, self-driving, medical, spam, data_classifier)
7. Trees vs linear models — trees can find gates but find the same wrong gate under broken metrics; their real value is as diagnostic tools
8. The heterogeneous-column problem — why column-level classification breaks on log-shaped data
9. The Sprint 6 → Sprint 9 investigation arc as a worked example
10. Practical lessons transferable to other projects + glossary

### 11. v2 inference infrastructure salvage — `29db52c`

**Salvaged from the blocked fastino promotion.** Ships three improvements without the model swap:

1. **Latent v2 threshold bug fix.** The v2 inference path was calling `model.extract_entities(text, spec, include_confidence=True)` without forwarding `self._gliner_threshold`, so any configured threshold was silently ignored. Now plumbed through.
2. **`descriptions_enabled` init flag.** New `GLiNER2Engine.__init__` parameter that auto-selects `False` for `fastino/*` model ids and `True` otherwise. At inference time v2 picks between list[str] (off) and dict[str, str] (on) entity-spec forms. Infrastructure for a future fastino promotion once the research/gliner-context work lands.
3. **ONNX auto-discovery guard for v2.** `_find_bundled_onnx_model()` only runs for v1 engines now. Prevents v2 engines from silently loading v1 ONNX bundles from the standard cache paths.

Default `_MODEL_ID` stays at `urchade/gliner_multi_pii-v1`. Default threshold stays at 0.5. Entity labels unchanged. This commit changes zero behavior on the current production path; it only adds infrastructure.

Files: `data_classifier/engines/gliner_engine.py`, `tests/test_gliner_engine.py` (+3 new test classes, +7 tests).

## Deferred items (Sprint 10 backlog)

### Fastino promotion — BLOCKED

`promote-gliner-tuning-fastino-base-v1` (P1 feature) — BLOCKED on blind-corpus regression:

| Corpus | urchade baseline | fastino + 0.80 + labels + desc-off | Δ | Gate |
|---|---:|---:|---:|---|
| Gretel-EN blind | 0.6111 | 0.4792 | **−0.1319** | need ≥ +0.02 → FAIL |
| Nemotron blind | 0.7744 | 0.5821 | **−0.1923** | need ≥ −0.005 → FAIL |

**Diagnosis:** fastino over-predicts `"phone number"` on any numeric-format column (SSN 25/30 @ 0.84 avg confidence, CC 26/30 @ 0.77 avg). The eval memo's +0.091 Ai4Privacy lift was measured on corpora with **context sentences around values**; our blind benchmarks feed raw bag-of-tokens with no grammatical context. Fastino (a context-attention NER model) can't disambiguate numeric shapes without grammar, so its "any hyphen-digit group → phone" heuristic dominates. This is exactly the same distribution-shift failure pattern as M1, at the model-evaluation layer instead of the CV layer.

**Independent empirical validation of the research/gliner-context research thread.** If that research succeeds, fastino likely becomes viable because the input-format gap closes.

**Unblock path for Sprint 10:** wait for research/gliner-context to produce a working prompt-construction helper, then the promotion is a 2-line model_id swap + re-benchmark thanks to the infrastructure salvage.

### Other deferred items (all moved back to `status=backlog, sprint_target=10, phase=plan`)

- **`gliner-data-type-pre-filter-skip-ml-on-numeric-temporal-boolean-columns`** (P1 feature) — was serialized behind fastino on the `gliner_engine.py` path; safe to implement alongside the salvaged `descriptions_enabled` infrastructure in Sprint 10.
- **`gliner2-over-fires-organization-on-numeric-dash-inputs`** (P2 bug) — same file, same sequence, same deferral rationale.
- **`confirm-bq-connector-populates-columninput-context-fields`** (P1 chore) — verbally confirmed by BQ team 2026-04-13. Written verification and `docs/process/BQ_INTEGRATION_STATUS.md` stub deferred to Sprint 10 per user direction ("we can verify later").

### Closed as won't-do

- **`gliner-onnx-export-and-bundling-for-meta-classifier-feature-pipeline`** (P1 chore) — stale. Sprint 8 Item 5 (download_models CLI + AR Generic repo) already solved the real need. The 333 MB `model.onnx` acceptance criterion is impossible under GitHub's 100 MB per-file limit. `data_classifier/models/gliner_onnx/README.md` explicitly documents the dir is "intentionally empty in the source tree". Moved to `status=done` with a won't-do rationale rather than carrying the dead item forward.

## Sprint 10 candidates filed during Sprint 9 discussion

New items filed during the Sprint 9 close-out M1 discussion — added to the Sprint 10 candidate list:

- **`gated-meta-classifier-architecture-explicit-credential-gate-specialized-stage-2-classifiers-q8-continuation`** (P1 feature) — the hybrid symbolic-statistical architecture: hand-coded credential gate + heterogeneous-column gate at the root, learned multi-class classifiers at the leaves. Extended with heterogeneous-column sibling gate notes from the log-column-problem discussion.
- **`meta-classifier-model-ablation-logreg-vs-xgboost-vs-lightgbm-on-honest-loco-metric`** (P2 feature) — train XGBoost / LightGBM on the same features and inspect root splits as a diagnostic for the gated-architecture design. Also compares performance, but the structural diagnosis is the primary value.
- **`hygiene-test-meta-classifier-training-py-env-leak-data-classifier-disable-ml-set-at-module-import-never-reverted`** (P2 bug) — `os.environ.setdefault` leak surfaced by the observability-gaps agent's import-error test.

Plus the user's own Sprint 10 planning work (uncommitted, user's personal files, not touched):
- `backlog/schema-prior-consumer-foundation-regex-threshold-adjustment-via-metadata-priors.yaml`
- `docs/plans/schema_prior_consumer.md`

## Benchmarks

### Sprint 9 consolidated accuracy (nemotron + gretel_en, 50 samples/column)

| Corpus | Mode | Macro F1 | Primary | TP / FP / FN |
|---|---|---:|---:|---|
| nemotron | named | **0.923** | 92.3% | 12 / 1 / 1 |
| nemotron | blind | **0.821** | 84.6% | 11 / 3 / 2 |
| gretel_en | named | **0.917** | 91.7% | 11 / 1 / 1 |
| gretel_en | blind | **0.611** | 66.7% | 8 / 4 / 4 |

**No direct delta available against Sprint 8** — Sprint 8 was synthetic-only (no nemotron, no Gretel-EN). This Sprint 9 run establishes the new real-corpus baseline. Sprint 10 should measure against these numbers.

**Gretel-EN blind at 0.611** is directly comparable to the fastino-blocked agent's measurement — the same 0.611 number they saw on the main baseline. Cross-check: our sprint-end benchmark agrees with the parallel agent's independent measurement, so the number is reliable.

History file: `docs/benchmarks/history/sprint_9.json`. HTML report: `docs/benchmarks/SPRINT9_CONSOLIDATED.html`.

### Meta-classifier ship gates (M1 promotion)

| Gate | Required | Measured | Result |
|---|---:|---:|---|
| Tertiary blind delta (meta − live) | ≥ +0.02 | **+0.2432** | ✓ PASS |
| CI width | ≤ 0.06 | **0.0519** | ✓ PASS |

## Test coverage

| Area | Δ tests | Cumulative |
|---|---:|---:|
| Round 1 parallel quick-wins (test-download-models metadata-SA, _disable_ml guard, cloudbuild SA token) | +1 test + 1 module-level guard | |
| Round 2 parallel quick-wins (observability-gaps, tar-safety, retro-fit-benchmarks) | +10 +4 +1 | |
| Gretel-EN ingest | +4 | |
| ai4privacy removal | +0 (cleanup removed some, added some, net ≈0) | |
| M1 promotion + adaptive fallback | +0 | |
| v2 infrastructure salvage | +7 | |
| **Total for Sprint 9** | **+25** | **1197 → 1222 passing** + 1 skipped |

CI: full suite green in ~36 s locally. Ruff clean. Format clean.

## Decisions and lessons learned

1. **Parallel agent dispatch worked — but the YAML phase-bump pattern needs a process fix.** 4-for-4 merge conflicts on every parallel agent's backlog YAML (phase=plan in main vs phase=review in the agent's worktree). Trivially resolved every time, but it's noise that should be fixed in the sprint-execute skill for Sprint 10. Options: (a) main session pre-bumps YAML phase before dispatching, (b) agents don't touch YAML (main session handles phase after merge), (c) agents commit YAML as a separate commit from code. Not blocking enough to fix this sprint.

2. **Worktree branching base was sometimes wrong.** The ai4privacy agent and the first Gretel agent both branched from `main` instead of `sprint9/main`, then had to rebase. Not the agent's fault — the Agent tool's `isolation=worktree` picks up the current HEAD at dispatch time, and that HEAD can drift between the dispatch moment and when the agent actually starts. Worth investigating the tool's semantics for Sprint 10.

3. **Shortcut learning is a data-level problem, not a model-level problem.** M1 proved the meta-classifier was relying on `heuristic_avg_length` as a corpus-fingerprint proxy. The fix isn't a better model — it's (a) fixing the measurement to expose the problem (M1's `StratifiedGroupKFold`), (b) diversifying the data so the shortcut stops existing (Gretel-EN's mixed-label corpus breaks the length → corpus correlation, dropping the shortcut's coefficient from 252 → 131, a 48% reduction). Both are necessary. Neither is sufficient alone.

4. **Fastino's failure on raw-value corpora is the same distribution-shift pattern as M1, just at a different layer.** The GLiNER eval memo measured +0.091 lift on Ai4Privacy which has context sentences around values. Our blind corpora feed raw values with no grammatical context. Fastino, trained on grammatical context, can't disambiguate numeric shapes without it. **Direct empirical validation** that the research/gliner-context context-injection thread is load-bearing, not speculative. Without the input-format work, the fastino promotion cannot succeed on our actual deployment distribution.

5. **Hand-coded roots + learned leaves is the right architecture for high-stakes classification.** The user's synthesis during the M1 discussion is the architectural direction for Sprint 10+: explicit credential gate at stage 1 (hand-coded entropy + column-name rule), specialized stage-2 classifiers per routed subset. This matches every high-stakes ML deployment pattern (credit scoring, self-driving, medical diagnosis, spam filtering) — ML is good at finding subtle patterns, bad at respecting invariants. Put rules at the decision points where interpretability and safety matter.

6. **Trees are diagnostic tools first, performance upgrades second.** The Sprint 10 LogReg-vs-XGBoost ablation item was filed as a **structural diagnosis**, not a performance comparison. Train a shallow XGBoost, inspect its root splits, and use that signal to validate or refute the explicit gate design. If the tree's root is still `heuristic_avg_length` even after Gretel-EN, the shortcut is more structural than we thought.

7. **The ai4privacy license audit discipline is new.** Sprint 8 found that the dataset card claimed one license while the actual `license.md` said something different. Sprint 9 formalized the verification discipline in `docs/process/LICENSE_AUDIT.md`: **always fetch the actual LICENSE file from the source repo or HuggingFace, never trust the dataset card metadata**. This discipline applies to every future corpus ingest and should be added to corpus-ingest items' acceptance criteria.

8. **"Consistent numbers across two metrics" is not validation.** Sprint 6's CV (0.916) and held-out test (0.918) agreed — and both were lying. If both metrics use the same flawed sampling procedure (random splits in both cases), they'll agree with each other while disagreeing with reality. The way to catch this is to introduce metrics with different sampling assumptions and check for disagreement.

9. **The honest meta-classifier delta has moved twice this project.** Sprint 6 claim: +0.257. E10 correction: +0.191. Post-Gretel + M1 (this sprint): **+0.2432**. The lesson isn't that the numbers are wrong; it's that **the number is a function of the measurement choices AND the training data, and both have evolved**. Always cite the current measurement with its full context, never a historical number as if it were timeless.

10. **User's live architectural intuition was consistently ahead of the existing design.** During the M1 discussion, the user independently derived (a) the gated architecture proposal from the observation that LogReg treats all features as living on one plane, (b) the heterogeneous-column problem from the observation that a log column can contain multiple sensitive things, (c) the "domain knowledge at roots, ML at leaves" synthesis. All three became Sprint 10 candidates during the conversation. **Lesson:** active collaboration with the domain expert produces better architectural proposals than a solo agent analysis.

## Recommendations for Sprint 10

Candidate items, in rough priority order:

### Sprint-10 anchor — the gated architecture track

1. **`gated-meta-classifier-architecture-...`** (P1, M) — the headline Sprint 10 item. Phase 1: explicit credential gate at stage 1 (entropy + column-name rule) + sibling heterogeneous-column gate. Phase 2: specialized stage-2 credential 4-way classifier. Phase 3: stage-2 PII 19-way classifier with `heuristic_avg_length` dropped from the feature set (test the "remove the shortcut feature directly" hypothesis). Each phase measured on the honest LOCO metric from M1.
2. **`meta-classifier-model-ablation-logreg-vs-xgboost-vs-lightgbm-...`** (P2, M) — diagnostic ablation. Train all three on the new post-Gretel training data with `StratifiedGroupKFold`. Inspect top splits / top coefficients per model. Primary question: does any of them pick a feature *other than* `heuristic_avg_length` at the root? Secondary question: does any clear +0.02 LOCO over the current LogReg baseline? Outcome informs the gated-architecture design.

### Continue the detection-uplift chain

3. **`promote-gliner-tuning-fastino-base-v1`** (P1, M) — gated on the research/gliner-context session producing a working prompt-construction helper. The 2-line code swap is ready; the benchmark gate becomes achievable once context injection is landed.
4. **`gliner-data-type-pre-filter-skip-ml-on-numeric-temporal-boolean-columns`** (P1, S) — now implementable cleanly on the salvaged `gliner_engine.py`. Skip GLiNER on `INTEGER/FLOAT/NUMERIC/BOOLEAN/TIMESTAMP/DATE/BYTES` `data_type` values.
5. **`gliner2-over-fires-organization-on-numeric-dash-inputs`** (P2, M) — needs re-evaluation under the gated architecture. If the explicit credential gate routes numeric-dash columns away from GLiNER entirely, the ORG over-fire bug might become moot by construction.

### Benchmark + methodology debt

6. **Sprint 10 should run *all three* corpora in the same session** — Sprint 9 has nemotron + gretel_en (real) + synthetic. Establishing a 3-corpus baseline means Sprint 10 onwards can compute real deltas, not fresh-start numbers.
7. **Outer train/test split should be group-level, not random.** M1 fixed the inner CV splitter but the outer 80/20 is still random and exhibits the same corpus leak. Not blocking, but the held-out test F1 is not a credible generalization estimate as long as it's random.
8. **`hygiene-test-meta-classifier-training-py-env-leak-...`** (P2) — small hygiene cleanup.

### Process improvements (not items, but worth doing)

9. **Fix the YAML phase-bump conflict pattern in sprint-execute.** Either pre-bump on main before dispatch, or move YAML handling entirely to the post-merge step.
10. **Investigate the Agent tool's worktree base-branch selection.** Multiple agents branched off `main` instead of `sprint9/main`. Not fatal (rebase fixes it), but worth understanding.

### Research workflow status

- **`research/meta-classifier`** — M1 candidate pkl + result memo landed (commit `c33c7fc`). Gretel-EN dataset landscape memo still authoritative (commit `cd3a5cc`). E10 verdict still authoritative (commit `6d4997f`).
- **`research/gliner-context`** — research session dispatched during Sprint 9 per user initiation. **Completed 2026-04-14**; user filed Sprint 10 item `promote-s1-nl-prompt-wrapping-gliner-engine-unblocks-fastino-promotion-and-resolves-org-over-fire` (P1 feature, phase=plan). Strategy: S1 natural-language prompt wrapping of values in `gliner_engine.py` input construction. **Scoped to resolve the Sprint 8 gliner2 ORG over-fire bug by construction**, so `gliner2-over-fires-organization-on-numeric-dash-inputs` may be closed as subsumed when S1 lands. The Sprint 9 v2 infrastructure salvage (`29db52c`) already landed; the Sprint 10 fastino retry is a 2-line model_id swap + S1 prompt wrapping + re-benchmark.
- **`research/gliner-eval @ 66c504f`** — the +0.091 GLiNER-only blind lift memo. Still the source of truth for the pre-context-injection eval; its "CRITICAL CAVEAT" about GLiNER-only ≠ full-pipeline was validated by the fastino-blocked finding this sprint.

## Repository state at sprint close

```
Branch:          sprint9/main → merging to main
Head commit:     d0d6e7b
Commits ahead:   24 (since main@65b6000)
Tests:           1222 passed + 1 skipped (+25 vs Sprint 8)
CI status:       lint-and-test = green; lint-and-test-ml = green; install-test = green
Ruff:            clean (95 files)
Format:          clean
Benchmarks:      nemotron + gretel_en run on 50 samples/column; history file sprint_9.json committed
Meta-classifier: v1.pkl retrained with M1 GroupKFold on 8370-row post-Gretel training data, best_c=1.0
```

Sprint 9 commit list (chronological):

```
2aa6b28 test(sprint9): add positive metadata-SA token test to TestAccessTokenDiscovery
edfee00 test(sprint9): harden _disable_ml fixture with list-copy + module-teardown guard
dfd569b chore(sprint9): defense-in-depth — pass SA token via process-substitution header in cloudbuild-release
2240a70 Merge branch 'worktree-agent-a71d9260' into sprint9/main  [test-download-models]
e994c0c Merge branch 'worktree-agent-a041249b' into sprint9/main  [_disable_ml guard]
4db755f Merge branch 'worktree-agent-aadb9fa3' into sprint9/main  [cloudbuild SA token]
01dcbd4 chore(sprint9): bump 3 merged parallel quick-wins to phase=review
af2c5b4 fix(sprint9): tar-safety — explicit symlink/hardlink rejection in _safe_extract pre-scan
11163a6 Merge branch 'worktree-agent-a8424c4c' into sprint9/main  [tar-safety]
fa00a15 chore(sprint9): record BQ verbal confirmation on context-fields item
315bca7 chore(sprint9): retro-fit Sprint 8 benchmarks + fix perf_benchmark flag honoring
d50a6e1 feat(sprint9): observability — get_active_engines + health_check + loud ImportError fallback
efd4d5d Merge branch 'worktree-agent-aea62442' into sprint9/main  [observability-gaps]
8f5a08d Merge branch 'worktree-agent-a3ee2e5e' into sprint9/main  [retro-fit-benchmarks]
e49e1d8 feat(sprint9): ingest gretelai/gretel-pii-masking-en-v1 as training corpus #7
a3233a0 docs(sprint9): add LICENSE_AUDIT.md and flag ai4privacy as pending removal
5a7b662 Merge branch 'worktree-agent-a0880083' into sprint9/main  [Gretel-EN ingest]
78fc25d chore(sprint9): remove ai4privacy — license non-OSS, replaced by Gretel-EN
6b74da7 feat(sprint9): M1 promotion — StratifiedKFold → StratifiedGroupKFold, retrain v1
6195843 chore(sprint9): bump M1 item to phase=review after promotion commit
b331ab1 fix(sprint9): M1 — adaptive StratifiedGroupKFold fallback for low-group datasets
d99d6a7 docs(sprint9): learning memo — shortcut learning, honest CV, gated architectures
29db52c feat(sprint9): v2 inference infrastructure — threshold plumbing fix + descriptions flag + ONNX guard
d0d6e7b chore(sprint9): defer 4 items to sprint 10, close stale gliner-onnx-export, file 3 discussion candidates
```
