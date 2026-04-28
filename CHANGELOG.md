# Changelog

All notable changes to `data_classifier` are documented here.

The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
keyed to sprint numbers: the sprint-release line is `0.{sprint}.0` with hotfix
cherry-picks as `0.{sprint}.{patch}`.

> **History note.** Versions `0.2.0` through `0.7.0` were **never published**
> to any index. The `pyproject.toml::version` field was frozen at `0.1.0`
> from Sprint 1 (2026-04-10) through Sprint 7 (2026-04-13), and the only
> wheel distributed during that window was a manually-built
> `data_classifier-0.1.0-py3-none-any.whl` vendored into
> `BigQuery-connector/vendor/`. The entries below for Sprints 5–7 are
> reconstructed from `docs/sprints/SPRINT{N}_HANDOVER.md` and represent the
> state the code was in at each sprint close — **not** a tagged release.
> Forward-only versioning begins with `0.8.0`.

## [Unreleased]

No unreleased changes.

## [0.17.0] — Sprint 17 (2026-04-28)

Promotion of `research/prompt-analysis` (130+ commits) into main —
unified Rust/WASM detector for the browser scanner v2.

### Added

- **Zone Detector v2** (Rust crate `data_classifier_core`) — full
  partitioning pipeline with format / structural / syntax / data /
  prose detectors. PyO3 + WASM bindings.
- **Unified WASM scanner** in `data_classifier/clients/browser/` —
  byte-identical WASM ↔ PyO3 native parity (validated by
  `scripts/cross_runtime_parity.sh`: 14 Rust + 8 WASM fixtures pass).
- **Scan pipeline + WildChat archive** — `scripts/scan_wildchat_unified.py`
  processed 1.94M prompts (2924 prompts/sec, 0 errors). Output split:
  - `data/wildchat_unified/candidates.jsonl` (81k records, 4.17%) —
    sparse view of prompts with non-NL zones or secrets.
  - `data/wildchat_unified/all_prompts.jsonl` (3.5 GB) — full archive,
    DVC-tracked at `gs://data-classifier-datasets/dvc-cache`.
- **s4 zone-detection validation infrastructure** — fresh-reviewed gold,
  IoU-based block-level scorer, stratified re-labeling pipeline.

### Changed

- `data_classifier/scan_text.py` prefers the Rust `UnifiedDetector`
  (PyO3) when available, falls back to pure-Python `TextScanner`.
- Browser bundle now ships WASM + unified patterns instead of the
  Sprint 14 JS-regex scanner.

### Known follow-ups (deferred from this PR)

- **Port 7 EU validators to Rust** —
  `backlog/port-7-eu-validators-to-rust-sprint16-parity.yaml`. Sprint 16
  added german_steuerid, french_nir, spanish_dni, spanish_nie,
  italian_codice_fiscale, dutch_bsn, austrian_svnr on the Python side.
  WASM detector emits these entity types via pattern-only matching
  (no checksum) until ported.
- **Regenerate wildchat_eval via Rust path + deprecate pure-Python
  TextScanner** —
  `backlog/regenerate-wildchat-eval-via-rust-path-deprecate-textscanner.yaml`.
  Closes the WASM-vs-pure-Python parity gap (currently 197/200 = 98.5%
  agreement).

### Gates verified

- `ruff check . --exclude .claude/worktrees`: clean
- `ruff format --check . --exclude .claude/worktrees`: clean
- `DATA_CLASSIFIER_DISABLE_ML=1 .venv/bin/python -m pytest tests/ -q`:
  2580 passed, 3 skipped, 1 xfailed
- `bash scripts/cross_runtime_parity.sh`: 14 + 8 fixtures pass
- `bash scripts/ci_browser_parity.sh`: 197/200 (98.5%) ≥ 87% S16 gate
- Family benchmark LIVE path: family_macro_f1 0.955

### Disclosures

- Pytest + family benchmark were run with `DATA_CLASSIFIER_DISABLE_ML=1`
  (this branch does not modify ML model code; ML-gated tests skip
  cleanly). Shadow-path family benchmark gate is unverified — needs an
  ML-enabled rerun on a non-throttled machine.

## [0.16.0] — Sprint 16 (2026-04-25 → 2026-04-27)

CONTACT and GOVERNMENT_ID recall sprint. No public API changes.
Focused on detection quality: GLiNER dedup correctness, EU national-ID
patterns, and a primary-label fix for within-family ambiguity
(ADDRESS vs PERSON_NAME).

### Added

- **GOVERNMENT_ID phase 1: 6 EU countries** — DE Steuer-ID, FR NIR,
  ES DNI/NIE, IT Codice Fiscale, NL BSN, AT SVNR. 7 regex patterns +
  7 checksum validators with country-specific confidence floors.
- **`ENTITY_SPECIFICITY` map** in `core/taxonomy.py` (with
  `specificity_for()` helper). Drives the within-family primary-label
  tie-break.

### Changed

- **GLiNER dedup uses evidence overlap** (`gliner_engine.py`). Previously
  the global type-hierarchy suppressed PERSON_NAME whenever ADDRESS
  co-fired, even when the two findings detected different values.
  Suppression now requires Jaccard overlap ≥ 0.50 on `sample_matches`;
  different-value findings both survive.
- **Primary-label tie-break uses specificity within a family.** When
  multiple findings share the same family (e.g. CONTACT — both ADDRESS
  and PERSON_NAME fired), the more specific entity wins regardless of
  raw confidence. Cross-family ordering is unchanged (pure confidence).

### Tooling

- Dev environment migrated to `uv` (chore PR #20). 3 of 4 CI jobs run
  `uv pip install --system`; `install-test` deliberately stays on pip
  to validate the end-user wheel install path.

### Benchmark

Family accuracy benchmark (Sprint 16, `DATA_CLASSIFIER_DISABLE_ML=1`):

| Metric | v0.15.0 (S15) | v0.16.0 (S16) | Delta |
|---|---|---|---|
| LIVE `cross_family_rate` | 0.1066 | **0.0808** | -0.0258 |
| LIVE `family_macro_f1` | 0.9477 | **0.9732** | +0.0255 |
| SHADOW `cross_family_rate` | 0.3245 | **0.3139** | -0.0106 |
| SHADOW `family_macro_f1` | 0.7030 | **0.8305** | +0.1275 |

Sprint gate metric (`shadow.cross_family_rate`) improved from baseline.
Summary committed as
`docs/research/meta_classifier/sprint16_family_benchmark.json`.

ML-enabled reference run (not gated by CI; documents the contribution
of GLiNER + within-family specificity on top of the no-ML baseline):
`cross_family_rate` 0.0291, `family_macro_f1` 0.9903, CONTACT F1 0.966
(+0.170 vs S15 no-ML), ADDRESS subtype F1 0.942 (+0.300), PERSON_NAME
F1 0.948 (+0.302).

## [0.15.0] — Sprints 13 / 14 / 15 (2026-04-16 → 2026-04-25)

Second BQ-facing release. Bundles three sprints of changes since
`v0.12.0`. **This release includes one behavior change:** the
meta-classifier directive flip (Sprint 14) makes the v5 meta-classifier
the live decision-maker on `structured_single` columns, improving
family-macro F1 from 0.83 to 0.95. See
`docs/migrations/v0.8.0-to-v0.15.0.md` for integration guidance.

### Added

- **`scan_text()` public API** (Sprint 14). Free-text credential
  scanning for prompts, logs, and configs. Three-pass pipeline: regex,
  KV secret scanner, and opaque token detection. Available via
  `from data_classifier import scan_text`.
- **`health_check()` probe** (Sprint 14). Safe readiness probe for
  `/health` endpoints — never raises.
- **3-branch column-shape router** (Sprint 13). Columns are classified
  as `structured_single`, `free_text_heterogeneous`, or `opaque_tokens`
  and routed to specialised detection pipelines.
- **Per-value GLiNER union** (Sprint 13). Heterogeneous columns get
  per-value ML classification instead of column-level aggregation.
- **PEM block detection** (Sprint 15). `-----BEGIN/END-----` blocks
  are detected as whole private keys instead of per-line noise.
- **CamelCase key-name normalisation** (Sprint 15). `privateKey` and
  `apiSecret` now match the snake_case secret key-name dictionary.
- **Opaque token pass** (Sprint 15). Standalone high-entropy token
  detection (JWTs, hex hashes, random API keys) in `scan_text`.

### Changed

- **Meta-classifier directive flip** (Sprint 14). The v5
  meta-classifier is now the live directive on `structured_single`
  columns. Shadow-only since Sprint 12, promoted after passing the
  safety audit. `family_macro_f1` 0.83 → 0.95.
- **Confidence model rethink** (Sprint 15). Single-match validated
  patterns (AKIA, ghp_) now floor at 0.95 confidence. The count-based
  multiplier is removed — confidence reflects match quality, not
  column prevalence. `match_ratio` available separately via
  `SampleAnalysis`.
- **Char-class diversity boost** (Sprint 15). Values with high
  character-class diversity (upper+lower+digits+symbols) get a small
  confidence lift in both the KV scorer and opaque token pass.
- **SWIFT_BIC validator tightened** (Sprint 15). All-alpha matches
  are rejected — real BIC codes almost always contain digits. Eliminates
  false positives from surnames and common words. FINANCIAL benchmark
  precision recovered from 0.838 to 0.996.

### Fixed

- **25+ structural FP filters** (Sprint 15). Opaque token and KV
  pass false positive rate reduced by ~80% on WildChat corpus. Filters
  cover: file paths, code expressions, CamelCase identifiers, JVM
  bytecode references, config bracket access, SSH fingerprints, template
  literals, Ethereum addresses, and more. All mirrored in Python + JS.
- **KV pass span accuracy** (Sprint 15). `scan_text` KV pass now
  reports the matched value span, not the whole text span.
- **CREDENTIAL split into subtypes** (Sprint 14). Benchmark ground
  truth uses `API_KEY` / `PRIVATE_KEY` / `OPAQUE_SECRET` instead of
  monolithic `CREDENTIAL` (runtime emission already used subtypes
  since v0.8.0).

### Removed

- **DOB_EU entity type** (Sprint 12, carried forward). `DOB_EU` is
  no longer emitted; use `DOB` instead. Family alias (`DATE`)
  preserved.

### Benchmark

Family accuracy benchmark (Sprint 15, `DATA_CLASSIFIER_DISABLE_ML=1`):

| Metric | v0.12.0 (S12) | v0.14.0 (S14) | v0.15.0 (S15) |
|---|---|---|---|
| `cross_family_rate` | 0.1627 | 0.1182 | **0.1066** |
| `family_macro_f1` | 0.8329 | 0.8566 | **0.9477** |
| `NEGATIVE` F1 | 0.000 | 0.000 | **1.000** |
| `FINANCIAL` F1 | — | 0.996 | 0.972 |
| `CREDENTIAL` F1 | — | 0.871 | 0.896 |

Test suite: **2343 tests**, 1 skipped, 1 xfailed.

## [0.12.0] — Sprints 9 / 10 / 11 / 12 (2026-04-13 → 2026-04-16)

First BQ-facing release since `v0.8.0`. Bundles four sprints of changes.
**This is a shadow-only release from the consumer perspective** — the
live classification path (`classify_columns` return values on
structured single-entity columns) is functionally identical to
`v0.8.0`. What's new is additive: a `family` field on every
`ClassificationFinding`, expanded pattern coverage, a shadow
meta-classifier for observability, and new validators. There is
**no behavior change** that requires connector-side adaptation; the
meta-classifier's directive promotion was evaluated in Sprint 12 and
**deferred to Sprint 13** after the Phase 5b safety audit returned
RED on heterogeneous columns (see
`docs/research/meta_classifier/sprint12_safety_audit.md`).

### Added

- **New public API field `ClassificationFinding.family`** (Sprint 11).
  Every finding is auto-populated with its family label via a
  `__post_init__` hook. 13 families covering downstream DLP handling
  concerns: `CONTACT`, `CREDENTIAL`, `CRYPTO`, `DATE`, `DEMOGRAPHIC`,
  `FINANCIAL`, `GOVERNMENT_ID`, `HEALTHCARE`, `NEGATIVE`, `NETWORK`,
  `PAYMENT_CARD`, `URL`, `VEHICLE`. Non-breaking additive change —
  existing consumers ignoring this field work unchanged.
- **New public API exports** (Sprint 11):
  `data_classifier.FAMILIES`, `data_classifier.family_for`,
  `data_classifier.ENTITY_TYPE_TO_FAMILY`. Downstream DLP policy
  engines can read `finding.family` or call `family_for(entity_type)`
  without needing to know the subtype→family mapping.
- **Meta-classifier shadow path** (v3 landed Sprint 11, v5 landed
  Sprint 12 as the current default). Accessible via
  `ClassificationEvent.meta_classification` on every event emitted by
  the orchestrator when the `[meta]` extra is installed. Shadow-only:
  the orchestrator's 7-pass merge remains the source of truth for
  `classify_columns()` return values. v5 adds two column-level
  statistics (`validator_rejected_credential_ratio`,
  `has_dictionary_name_match_ratio`) on top of v3's feature schema.
- **Family-level accuracy benchmark** as the canonical ship gate
  (Sprint 11). Run via
  `tests.benchmarks.family_accuracy_benchmark`; reports
  `cross_family_rate` (Tier 1 errors, product-impact) and
  `family_macro_f1` (aggregate quality). Current Sprint 12 shipped
  baseline: shadow `cross_family_rate=0.0044` /
  `family_macro_f1=0.9945` on 9,870 shards (committed at
  `docs/research/meta_classifier/sprint12_family_benchmark.json`).
- **Structural validators** (Sprint 11):
  * `bitcoin_base58check` and `bitcoin_bech32` / `bech32m` — replaces
    the prior length-only check.
  * `ethereum_checksum` — EIP-55 case-encoded address validation.
  * `not_placeholder_credential` — reject `password123`, `admin`,
    `your_api_key_here`, etc. Backed by
    `data_classifier/patterns/known_placeholder_values.json`
    (34-entry curated list).
- **Secret-key-name dictionary: 88 → 178 entries** (Sprint 10) via
  `scripts/ingest_credential_patterns.py`. Sourced from Kingfisher
  (Apache 2.0), gitleaks (MIT), and Nosey Parker (Apache 2.0) with
  pinned SHAs and full per-entry attribution in
  `docs/process/CREDENTIAL_PATTERN_SOURCES.md`.
- **GLiNER2 data_type pre-filter** (Sprint 10). The ML engine now
  skips columns whose `ColumnInput.data_type` is non-textual
  (INTEGER, FLOAT, NUMERIC, DATE, TIME, BOOLEAN, BYTES, ...). Fixes a
  whole class of numeric-column false positives without changing the
  regex cascade.
- **GLiNER2 natural-language prompt wrapping** (Sprint 10, "S1"):
  `_build_ner_prompt(column, chunk)` replaces the raw
  `_SAMPLE_SEPARATOR.join` approach.
- **`Orchestrator.get_active_engines()` and `health_check()`**
  (Sprint 9) for consumer-side observability. Returns the list of
  actually-registered engines and confirms each is alive.
- **New corpus: `gretelai/gretel-pii-masking-en-v1`** as a 7th
  training corpus (Sprint 9, Apache 2.0, 60k rows across 47
  domains). Training-only; no runtime consumer impact.
- **New corpus loader: `gretelai/synthetic_pii_finance_multilingual`**
  (Sprint 10, Apache 2.0, 56k rows, 7 languages). Loader landed
  Sprint 10; CLI wiring landed Sprint 11.
- **New CLIENT_INTEGRATION_GUIDE.md §5A Engines Reference** (Sprint
  11, 329 lines). Canonical per-engine documentation + 7-pass
  orchestrator pipeline walkthrough. All symbol-only citations for
  drift resistance.
- **Tier-1 credential pattern-hit gate**
  (`data_classifier/orchestrator/credential_gate.py`, Sprint 11).
  Observability-only. Emits `GateRoutingEvent` on every column with
  credential signal; never modifies `classify_columns()` return
  values. Promotion to a directive routing rule is filed as a
  future-sprint item pending production telemetry calibration.
- **Per-value parity tests for the shadow path** (Sprint 12,
  `tests/test_meta_classifier_inference_parity.py`). End-to-end tests
  that run the full orchestrator and assert the feature vector at
  inference equals the feature vector at training, preventing the
  class of train/serve-skew bug that shipped in Sprint 11 Phase 7
  and Sprint 12 Phase 5a.

### Changed

- **Meta-classifier feature schema v3** (Sprint 11) adds two
  heuristic column-level features: Chao-1 bias-corrected
  `heuristic_distinct_ratio` and `heuristic_dictionary_word_ratio`.
  Training-side change; the shadow model weights picked them up as
  the #1 and #3 coefficients by magnitude.
- **Meta-classifier feature schema v5** (Sprint 12) adds
  `validator_rejected_credential_ratio` and
  `has_dictionary_name_match_ratio`. Combined with the Sprint 12 Phase
  5a "Option A" train/serve-skew fix in `predict_shadow`, the shadow
  cross-family error rate dropped from 5.85% (Sprint 11 baseline) to
  **0.44%** on the canonical family benchmark (9,870 shards) — a
  13.3× reduction.
- **`predict_shadow` signature** (Sprint 12, Phase 5a) accepts a new
  optional `engine_findings` kwarg
  (`dict[engine_name, list[Finding]]`). When provided, the shadow
  model's feature vector is computed from the raw per-engine finding
  dict instead of the orchestrator's merge-collapsed list. This fix
  closes the train/serve skew that caused Sprint 12 Phase 5a's
  `SSN→CREDIT_CARD` shadow collapse on 219 SSN columns. Callers that
  do not pass `engine_findings` keep the legacy behavior for
  back-compat.
- **GLiNER2 consumer mode** (Sprint 10): column-level inference now
  chunks sample values into the NL prompt template rather than
  concatenating them with a literal separator. No consumer-side
  API change.

### Deprecated

- `DATE_OF_BIRTH_EU` subtype label (Sprint 12). The emission path is
  removed — columns that were formerly classified as
  `DATE_OF_BIRTH_EU` now emit `DATE_OF_BIRTH` (both belong to the
  `DATE` family, so family-level behavior is unchanged). A narrow
  alias is retained in `data_classifier.core.taxonomy.ENTITY_TYPE_TO_FAMILY`
  so any residual shadow predictions emitting the old label still
  map to the `DATE` family. Consumer-side impact: if you were
  reading `finding.entity_type == "DATE_OF_BIRTH_EU"` to branch on
  format, that branch never fires on new data from v0.12.0 onwards.
  Use `finding.family == "DATE"` for family-level routing, or
  consume the date-format metadata from
  `ClassificationEvent.meta_classification` if you need jurisdictional
  granularity.

### Removed

- **Ai4Privacy corpus** (Sprint 9). Removed from all training data
  after a license audit flagged the dataset as non-OSI-compatible.
  Replaced in training by the Gretel-EN corpus. Training-only
  change; no consumer API impact. See
  `docs/process/LICENSE_AUDIT.md` for the verification discipline
  that now gates every corpus addition.

### Fixed

- **Shadow path train/serve skew** (Sprint 12 Phase 5a). Historical
  root cause: `extract_features` was called with the orchestrator's
  post-merge `list[ClassificationFinding]` at inference but with
  `_run_all_engines`'s raw per-engine output at training. Same
  function, different input shape, silently different feature
  vectors. Fix: new `engine_findings` kwarg on `predict_shadow`
  (see "Changed" above). Test coverage: the parity test class
  `TestPredictShadowAcceptsRawEngineFindings` (9 tests) locks the
  contract.
- **SSN validator hardening** (Sprint 6) — area-code 000, 666, 900-999
  now correctly reject (previously slipped through). Not a
  consumer-visible fix on normal data.
- **Secret scanner `id_token` and `token_secret` patterns**
  (Sprint 11) — tightened from `substring` match to `word_boundary`
  to fix false-positive fires on `id_token_audience` and similar
  English words embedding the pattern as a substring.
- **M1 CV methodology** (Sprint 9) — the meta-classifier's
  cross-validation fold construction now uses
  `StratifiedGroupKFold(groups=corpora)` instead of
  `StratifiedKFold`, eliminating corpus-fingerprint leakage that had
  inflated the Sprint 6 CV estimate from `0.916` (leaky) to `0.194`
  honest. Training-only change; no consumer API impact. See
  `docs/learning/sprint9-cv-shortcut-and-gated-architecture.md`.

### Security

- No security-relevant fixes in this release. The
  `not_placeholder_credential` validator (Sprint 11) reduces false
  positives on documentation-placeholder credentials but does not
  address any exploit or information disclosure.

## [0.8.0] — Sprint 8, "Ship it: stabilize, release, prep credentials" (2026-04-13)

### Added

- `lint-and-test-ml` CI matrix job that installs the `[ml]` extra and runs
  the full test suite on Python 3.12. Phase 1 sets
  `DATA_CLASSIFIER_DISABLE_ML=1` at the job level as a temporary guard
  while model distribution (Item 5) is still landing; Phase 2 will remove
  the kill-switch and add a `download_models` step.
- `TestApplyFindingsLimit` unit test class pinning the orchestrator's
  confidence-gap suppression behavior. Regression coverage against the
  Sprint 5–7 silent breakage of `test_ssn_in_samples` under ML-enabled env.
- `CHANGELOG.md` (this file).
- `cloudbuild-release.yaml` for tag-triggered wheel publish to Google
  Artifact Registry (Python repo, `dag-bigquery-dev` project,
  `us-central1`). Uses Google Cloud Build rather than GitHub Actions to
  match the BigQuery-connector sibling project's existing CI pattern
  (which has 4 `cloudbuild*.yaml` files and no GitHub Actions) and to
  avoid the Workload Identity Federation overhead — Cloud Build's
  default service account runs natively in the GCP project and only
  needs `artifactregistry.writer` granted.
- GCP Artifact Registry infrastructure in `dag-bigquery-dev/us-central1`:
    * Python repo `data-classifier` (wheels)
    * Generic repo `data-classifier-models` (ONNX model tarballs)
- Cloud Build trigger `data-classifier-release` (2nd gen, on the
  `zbarbur-data-classifier` Cloud Build repository connection) that
  fires on any `^v.*$` tag push and runs the release pipeline.
- `data-classifier-download-models` console script entry in
  `pyproject.toml` `[project.scripts]`. Lets consumers run
  `data-classifier-download-models` directly without `python -m ...`.
  Smoke-tested in CI by `install-test`'s new "Smoke test download_models
  CLI entry point" step.
- `OPAQUE_SECRET` entity-type detection in
  `data_classifier/engines/heuristic_engine.py`. The heuristic engine
  emits the new fallback subtype when a column-gated random-password
  pattern hits and no more-specific subtype (`API_KEY`,
  `PRIVATE_KEY`, `PASSWORD_HASH`) wins. Threads `best_subtype`
  through `secret_scanner.py:436+,514+` so the four-way credential
  split lands end-to-end.

### Changed

- **ONNX model distribution decoupled from the release pipeline.**
  The original Item 5 design had `cloudbuild-release.yaml` re-export
  the GLiNER ONNX model on every `v*` tag push — installing the full
  `[ml-full]` extras stack (torch + transformers + onnx, ~2GB) into the
  Cloud Build runner and running `python -m data_classifier.export_onnx`
  for ~10 min per release. That was **pure waste**: the upstream
  GLiNER model doesn't change when `data_classifier` revs, so every
  release was re-producing the same byte-identical artifact. This
  commit:
    1. Removes the `publish-model` step from `cloudbuild-release.yaml`.
       Release builds now run **2 steps** (build wheel, publish wheel)
       in ~60s instead of 3 steps in ~15 min.
    2. Adds a pinned `DEFAULT_MODEL_VERSION = "urchade-gliner-multi-pii-v1"`
       constant in `data_classifier/download_models.py`. The ONNX
       tarball is versioned by the **upstream model ID**, not the
       `data_classifier` package version — and a human uploads a new
       tarball only when the base model changes (rarely, ≤1×/year).
    3. Switches `download_models.py` to use the Google Artifact
       Registry **REST download endpoint**
       (`artifactregistry.googleapis.com/v1/projects/.../files/...:download?alt=media`)
       with Bearer token authentication. Previously pointed at a
       placeholder `data-classifier-prod` project URL.
    4. Adds `_get_access_token()` helper with a 4-tier discovery chain:
       explicit `--access-token` CLI flag → `GCP_ACCESS_TOKEN` env var
       → GCP metadata service (the BQ Cloud Build path, zero setup) →
       `gcloud auth print-access-token` fallback for dev machines.
       Still stdlib-only — no new dependencies.
    5. Shrinks the published ONNX tarball from **1.4GB → 254MB** by
       shipping only the int8-quantized `model.onnx` file (GLiNER's
       loader hardcodes that filename, so `model_quantized.onnx` is
       renamed to `model.onnx` in the tarball layout). The
       unquantized 1.1GB file is dropped entirely.
    6. **`twine --skip-existing` is unsupported by Google Artifact
       Registry** (`UnsupportedConfiguration` error). The publish-wheel
       step instead does an explicit preflight `curl` against the AR
       `files.get` REST endpoint with the build's metadata-SA token,
       and exits 0 if the wheel filename + version is already present.
       This makes re-tags (e.g. `v0.8.0-rc1` → `v0.8.0`) and trigger
       re-runs idempotent without `--skip-existing`. See
       `cloudbuild-release.yaml` `publish-wheel` step + commits
       `e182cb2` (drop `--skip-existing`) and `40ced63` (add preflight).
    7. `cloudbuild-release.yaml`'s overall timeout drops from 1500s to
       300s to reflect the smaller scope.

  The ONNX tarball for this release
  (`gliner_onnx-urchade-gliner-multi-pii-v1.tar.gz`, SHA-256
  `a19fe153...ef45`) is uploaded once, manually, via
  `gcloud artifacts generic upload`. Future model upgrades follow the
  same one-off flow — see `cloudbuild-release.yaml` header comment for
  the exact commands.

### Changed

- **Version scheme.** Forward-only: `0.{sprint}.0` for normal sprint
  releases, `0.{sprint}.{patch}` for hotfix cherry-picks. `0.1.0 → 0.8.0`
  jump documented above.
- **ML extras consolidated.** `[ml-api]` removed — it declared
  `gliner2>=1.0` which is not the package `gliner_engine.py` imports, and
  no consumer used it. `[ml]` remains the lean production runtime (gliner
  + onnxruntime only). `[ml-full]` remains the developer/export extra
  (gliner + onnxruntime + torch + transformers + onnx). Consumers on
  `[ml-api]` should migrate to `[ml]` — all engine code continues to work
  unchanged.
- `tests/test_regex_engine.py::TestSampleValueMatching` is now pinned to
  regex-only semantics via a class-level autouse fixture that
  monkeypatches `data_classifier._DEFAULT_ENGINES`. Setting
  `DATA_CLASSIFIER_DISABLE_ML=1` from a pytest fixture is ineffective
  because `tests/conftest.py` imports `data_classifier` before any
  fixture runs, caching the engine list at module import time.

### Fixed

- `test_ssn_in_samples` no longer silently fails under `[ml]`-enabled
  environments. The underlying fixture (`987-65-4321`) is correctly
  rejected by `ssn_zeros_check` (ITIN range 900–999), which halves the
  regex SSN confidence to ~0.36, and when GLiNER2 fires `ORGANIZATION`
  at ~0.74 on the same column the 0.38 gap exceeds the 0.30 threshold
  and SSN is dropped. This is the correct orchestrator behavior — the
  test was written pre-Sprint-5 before the ML engine landed and has been
  silently broken under ML since. Fix pins the test to regex-only
  semantics and adds `TestApplyFindingsLimit` to cover the gap-suppression
  mechanism directly. See commits `a8f1aac` and `84d5153`.

## [0.7.0] — Sprint 7, "Compare & measure" (2026-04-13, NOT PUBLISHED)

> Reconstructed from `docs/sprints/SPRINT7_HANDOVER.md`.

### Added

- **International phone coverage on Ai4Privacy: 16.3% → 94.5%**
  (45,568 PHONE rows). New `international_phone_local` regex pattern for
  trunk-0/00 formats (34.0% of the corpus); `international_phone` regex
  expanded from single-separator to multi-segment mixed-separator (48.1%
  of the corpus).
- **Credential coverage on Ai4Privacy: 0% → 98.6%** (37,738 CREDENTIAL
  rows). New `random_password` content pattern + `random_password_check`
  validator, gated by a new **column-gate mechanism**.
- **Column-gate as a first-class pattern capability.** New fields on
  `ContentPattern`: `requires_column_hint: bool` and
  `column_hint_keywords: list[str]`. Patterns with the flag only fire
  when the column name contains a keyword (case-insensitive substring
  match). Backward-compatible — default is off.
- **Presidio comparator infrastructure** under
  `tests/benchmarks/comparators/`. Strict and aggressive InfoType
  mappings, duck-typed `RecognizerResult` adapter for testability,
  `compute_corpus_metrics`, side-by-side table formatter, consolidated
  report `--compare presidio` CLI flag, disagreement JSONL writer. The
  actual Presidio benchmark run against the 4 configs is deferred.
- 124 new tests, total 1133 passing.

### Fixed

- `_SSN_ADVERTISING_LIST` cleanup: 10 unreachable `987-65-4320..4329`
  entries removed. They were shadowed by the Sprint 6 ITIN area rule
  which rejects the 900–999 range before the advertising list check
  ever runs. A monkeypatch-based characterization test in
  `TestAdvertisingRangeHandledByAreaRule` pins the area rule as the
  real mechanism.

### Changed

- **M1 meta-classifier CV methodology correction — docs only.**
  `SPRINT6_HANDOVER.md` gained a Known Issues subsection flagging the
  Sprint 6 "CV macro F1 = 0.916" headline as a memorization artifact.
  Honest LOCO mean is ~0.30. The actual code fix
  (`StratifiedKFold → StratifiedGroupKFold` in
  `scripts/train_meta_classifier.py`) is deferred to Sprint 8 pending
  E10 research visibility.

## [0.6.0] — Sprint 6 (NOT PUBLISHED)

> Reconstructed from `docs/sprints/SPRINT6_HANDOVER.md`.

### Added

- **Meta-classifier shadow pipeline** (logistic-regression on 18
  features): `scripts/train_meta_classifier.py`,
  `scripts/evaluate_meta_classifier.py`, `data_classifier/registry/`
  module. Shadow mode — findings are computed and logged but not
  returned from `classify_columns`. Cross-validated macro F1 = 0.916
  on the Sprint 5 canonical dataset; LOCO (leave-one-corpus-out) gap
  of 0.27–0.36 flagged as a structural concern.
- Secret scanner hardening: context-window scoring refinements,
  additional lookalike rejection, SSN zeros check extended to reject
  ITIN areas 900–999 canonically.
- `DATE_OF_BIRTH_EU` entity type for European DD/MM formats (separate
  from US MM/DD DOB).
- Total 1009 passing tests.

### Fixed

- SSN advertising-list handling regression uncovered during Sprint 6 —
  partial fix landed in Sprint 6 and completed in Sprint 7.

## [0.5.0] — Sprint 5 (NOT PUBLISHED)

> Reconstructed from `docs/sprints/SPRINT5_HANDOVER.md` and memory.

### Added

- **GLiNER2 ML engine** (`data_classifier/engines/gliner_engine.py`).
  Zero-shot NER on sample values using description-enhanced labels.
  Order 5 in the cascade (after secret_scanner). Supports three
  inference modes: ONNX local (fastest, ~3s load), HF download
  (first-run penalty), API fallback.
- **ONNX deployment path** via `_find_bundled_onnx_model()` which
  searches `{package}/models/gliner_onnx/`, `~/.cache/data_classifier/`,
  and `/var/cache/data_classifier/` for a pre-exported model. The
  model itself is ~200MB and not committed to git.
- **BQ integration activated** — BigQuery-connector imports
  `data_classifier` via a vendored wheel at
  `BigQuery-connector/vendor/data_classifier-0.1.0-py3-none-any.whl`.
- Model registry (`data_classifier/registry/`), ONNX export script
  (`data_classifier/export_onnx.py`), environment-variable kill-switch
  (`DATA_CLASSIFIER_DISABLE_ML=1`).
- Blind-test F1 on Sprint 4 corpora: 0.87 / 0.67.

## Earlier history

Sprints 1–4 are documented in their respective `SPRINT{N}_HANDOVER.md`
files. No wheels were published and the implementation landed on top of
an in-place `0.1.0` version string.

[Unreleased]: https://github.com/zbarbur/data-classifier/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/zbarbur/data-classifier/releases/tag/v0.8.0
