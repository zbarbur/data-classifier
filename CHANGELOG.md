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

Sprint 8 work in progress on `sprint8/main`. Entries will land here as
each item ships and be promoted to the `[0.8.0]` section at sprint close.

## [0.8.0] — Sprint 8 (in progress)

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
  needs `artifactregistry.writer` granted. The actual AR repo creation
  + Cloud Build trigger setup is a Phase 2 manual step within Sprint 8
  (4 `gcloud` commands + one GitHub App install).

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
