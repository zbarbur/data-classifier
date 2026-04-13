# Sprint 8 Handover — Ship it: stabilize, release, prep credentials

> **Date:** 2026-04-13
> **Theme:** Ship it — stabilize, release, prep credentials. First publishable wheel (`v0.8.0`) + first authenticated model distribution path + credential taxonomy refactor.
> **Branch:** sprint8/main → merging to main
> **Tests:** 1133 → **1197 passing** (+64) + 1 skipped (Presidio live-engine, gated on `[bench-compare]` extra)
> **First-ever publish:** `data_classifier 0.8.0` wheel published to Google Artifact Registry; ONNX model tarball (254 MB) uploaded to AR Generic repo. End-to-end BQ deployment path validated.

## Delivered (5 items)

### 1. CI matrix — `[ml]` extras job (P1, chore)

New `lint-and-test-ml` job in `.github/workflows/ci.yaml` that installs the `[dev,meta,ml]` extras stack on Python 3.12 and verifies:
1. `gliner` + `onnxruntime` + the rest of the ML chain install cleanly on a fresh Ubuntu runner
2. `GLiNER2Engine` imports and constructs without error (Sprint 5 regression guard against wheel-time ImportError)
3. The full pytest suite runs against an `[ml]`-enabled venv (with the kill-switch on — see below)

**Phase 1 (Sprint 8) ships only the install/import/construct verification.** Real GLiNER inference is **not** exercised in CI. `DATA_CLASSIFIER_DISABLE_ML=1` is set permanently at the job level because:

- The ONNX model lives in the private `data-classifier-models` AR Generic repo (`dag-bigquery-dev`, us-central1)
- GitHub-hosted runners have no ambient GCP credentials
- Mode 2 in `gliner_engine.py`'s loader falls back to HuggingFace, which Sprint 5 already saw 429-rate-limit BQ's prod deployment

Removing the kill-switch without first wiring Workload Identity Federation would regress us straight into the Sprint 7 flaky state. Phase 2 (real-inference CI via WIF) is filed as a Sprint 9 backlog item — see Recommendations below.

**End-to-end BQ deployment validation was performed out-of-band** in this session and proves the kill-switch isn't masking a real bug (see Item 5 below).

Files:
- `.github/workflows/ci.yaml` — new job
- Test count: +0 (CI configuration only)

### 2. Investigate `test_ssn_in_samples` failure under `[ml]` env (P1, bug)

Sprint 7 close discovered that `tests/test_regex_engine.py::TestSampleValueMatching::test_ssn_in_samples` *silently failed* when run from an `[ml]`-enabled venv. The bug had been latent since Sprint 5 because regex-only CI never exercised the path.

**Root cause** — the orchestrator's gap-suppression mechanism in `_apply_findings_limit`:

1. The fixture SSN `987-65-4321` is correctly rejected by `ssn_zeros_check` (ITIN range 900–999, added in Sprint 6), which halves the regex SSN confidence from ~0.72 to ~0.36.
2. With ML enabled, GLiNER2 fires `ORGANIZATION` at ~0.74 on the same column.
3. The orchestrator computes a confidence gap of 0.74 − 0.36 = 0.38, which exceeds the 0.30 threshold.
4. SSN is dropped as the secondary finding. ORGANIZATION is returned.

**The orchestrator is correct.** The test was written pre-Sprint-5 and asserts SSN is returned regardless of the cascade, which is no longer the right invariant once GLiNER is in the pipeline.

**Fix:**

1. **Pin `TestSampleValueMatching` to regex-only semantics** via a class-level autouse fixture that monkeypatches `data_classifier._DEFAULT_ENGINES` to drop `gliner2`. Setting `DATA_CLASSIFIER_DISABLE_ML=1` from a fixture is ineffective because `tests/conftest.py` imports `data_classifier` *before* any fixture runs, and the engine list is cached at module import time. See `tests/test_regex_engine.py::TestSampleValueMatching._disable_ml`.

2. **Add `TestApplyFindingsLimit`** — 4 new unit tests pinning the gap-suppression mechanism directly so future regressions to the threshold or scoring math fail loudly.

3. **File the underlying behavior as a Sprint 9 backlog item** — `gliner2-over-fires-organization-on-numeric-dash-inputs`. GLiNER's tendency to label hyphen-separated digit groups as ORGANIZATION is a real precision issue, just not one the SSN test should be the messenger for. The ORG label gets picked up because the GLiNER prompt for ORGANIZATION is too broad on numeric-dash patterns. Sprint 9 will either narrow the prompt or add a content-shape filter.

Files:
- `tests/test_regex_engine.py` — `TestSampleValueMatching` autouse `_disable_ml` fixture; `TestApplyFindingsLimit` (4 tests)
- New backlog item: `gliner2-over-fires-organization-on-numeric-dash-inputs-...yaml` (Sprint 9)
- Test count: +5

### 3. Wheel versioning + Google Artifact Registry release pipeline (P1, chore) — **first-ever publish**

The headline shipping work of Sprint 8. Everything from the Sprint 7 carryover memo landed: pinned semver, Cloud Build release trigger, AR Python repo, and the literal `data_classifier 0.8.0` wheel installable via `pip install --extra-index-url`.

**Decisions vs. the Sprint 7 plan:**

- **Cloud Build, not GitHub Actions.** The BigQuery-connector sibling project has 4 `cloudbuild*.yaml` files and zero GitHub Actions. Sticking with Cloud Build matches their CI pattern, runs natively in `dag-bigquery-dev`, and removes the Workload Identity Federation overhead — Cloud Build's default service account just needs `artifactregistry.writer` granted.
- **Forward-only versioning from `0.8.0`.** `pyproject.toml::version` was frozen at `0.1.0` from Sprint 1 through Sprint 7 — no published wheels existed, only the manually-built one vendored into `BigQuery-connector/vendor/`. The `0.2.0–0.7.0` versions were *never published* anywhere, and trying to backfill them creates spurious authoritative-looking artifacts. `CHANGELOG.md` documents the gap (see "History note") and reconstructs Sprints 5–7 from handover docs marked `NOT PUBLISHED`. Going forward: `0.{sprint}.0` for normal sprint releases, `0.{sprint}.{patch}` for hotfixes.
- **`[ml-api]` extra deleted.** It declared `gliner2>=1.0` which is not the package `gliner_engine.py` actually imports (`gliner`, no 2). No consumer used it. `[ml]` (lean: gliner + onnxruntime) and `[ml-full]` (developer/export: + torch + transformers + onnx) are the two surviving ML extras.

**Infrastructure created in `dag-bigquery-dev` / us-central1:**

- AR Python repo `data-classifier` (wheels)
- AR Generic repo `data-classifier-models` (ONNX tarballs — see Item 5)
- Cloud Build trigger `data-classifier-release` (2nd gen, on the `zbarbur-data-classifier` Cloud Build repo connection) — fires on `^v.*$` tag pushes
- IAM bindings: Cloud Build SA + Compute SA both granted `artifactregistry.writer` project-wide

**`cloudbuild-release.yaml`** — 2 steps, ~60s total:

1. `build-wheel`: clean `python:3.12-slim`, `python -m build --wheel`, sanity-check that the wheel filename carries the `pyproject.toml::version`.
2. `publish-wheel`: preflight check via `curl` against the AR `files.get` REST endpoint to detect already-published versions (idempotent re-tags), then `twine upload --repository-url https://us-central1-python.pkg.dev/${PROJECT_ID}/data-classifier/`. Auth is transparent via `keyrings.google-artifactregistry-auth` + the Cloud Build SA's metadata token.

**Three iterations were needed to get a green trigger** — recording them here because they're load-bearing for whoever debugs the pipeline next:

1. **`twine --skip-existing` is unsupported by AR.** Returns `UnsupportedConfiguration`. Solution: drop the flag, add the explicit preflight check that exits 0 if the wheel is already present. Commit `e182cb2` → `40ced63`.
2. **Cloud Build substitution escaping.** `${VAR}` is parsed as a built-in substitution before bash sees it. Shell variables must be `${VAR}` (escaped). All `WHEEL_VERSION`, `ACCESS_TOKEN`, etc. are escaped; `${PROJECT_ID}` (a real built-in) is not. Commit `4cb5b56`.
3. **AR Python file-ID format.** Initial guess was `<package>:<version>:<filename>` (the Generic format). Correct format is `<package>%2F<filename>` (URL-encoded slash). Confirmed via `gcloud artifacts files list --log-http`.

**Validation — fresh-venv install from AR:**

```
$ python -m venv /tmp/v && /tmp/v/bin/pip install \
    --extra-index-url https://us-central1-python.pkg.dev/dag-bigquery-dev/data-classifier/simple/ \
    "data_classifier==0.8.0"
$ /tmp/v/bin/python -c "from data_classifier import classify_columns, ColumnInput; print('ok')"
ok
```

Files:
- `cloudbuild-release.yaml` (new)
- `pyproject.toml` — version `0.1.0 → 0.8.0`, `[ml-api]` removed, `[project.scripts]` adds `data-classifier-download-models`
- `CHANGELOG.md` (new) — forward-only history with backfilled Sprint 5–7 notes
- `docs/CLIENT_INTEGRATION_GUIDE.md` — section 1b rewritten with the AR `--extra-index-url` recipe

### 4. Split `CREDENTIAL` into API_KEY / PRIVATE_KEY / PASSWORD_HASH / OPAQUE_SECRET (P1, feature)

Sprint 7 random_password + column-gate landed `CREDENTIAL` as a single bucket. Sprint 8 splits it into 4 deterministic subtypes, all per the research-branch Item A draft.

The split is driven by *detection modality*, not surface form:

| Subtype | Detection mechanism | Examples |
|---|---|---|
| `API_KEY` | structured prefixes + length + entropy | `sk_live_...`, `ghp_...`, `xoxb-...`, AWS access keys |
| `PRIVATE_KEY` | PEM/OpenSSH headers, base64 body | `-----BEGIN RSA PRIVATE KEY-----` |
| `PASSWORD_HASH` | scheme prefix (`$2a$`, `$argon2id$`, `{SHA1}`...) | bcrypt, argon2, scrypt, MD5/SHA hex digests with column gate |
| `OPAQUE_SECRET` | the Sprint 7 column-gated random_password — generic high-entropy fallback | columns named `password`, `secret`, `passphrase`, etc. |

This split is the prerequisite for Sprint 9's `promote-gliner-tuning-fastino-base-v1` work and for the future Q8 specialized opaque-secret meta-classifier path. It also lets BQ consumers tag findings differently for response policy (rotate API keys vs. flag password reuse vs. revoke leaked private keys).

Files (from the Item 4 worktree merge `1e013aa`):
- `data_classifier/patterns/default_patterns.json` — new entity-type entries, new patterns for each subtype
- `data_classifier/engines/validators.py` — new validators (PEM scanner, hash-scheme detector)
- `data_classifier/profiles/standard.yaml` — entity-type registry
- `tests/test_credential_password.py` — refactored for the 4-subtype taxonomy
- `tests/test_opaque_secret.py` — new (24 tests)
- Test count: +24 + ~40 modified

### 5. Model distribution — `download_models` CLI + AR Generic publish (P1, chore)

This item replaced the originally-planned Cloud DLP comparator (commit `7e3af5c` records the scope swap) once the Item 3 work made it obvious that wheel publication was useless without a corresponding model distribution path. BQ's Cloud Run deployment cannot reach HuggingFace at first-request time (rate limits + cold-start latency), so the GLiNER2 ONNX model must be baked into the Docker image at *build* time. That requires an authenticated download from a pinned URL — exactly what AR Generic + a CLI gives us.

**Architecture decision — ONNX model distribution is decoupled from the wheel release pipeline.**

The original Item 5 design had `cloudbuild-release.yaml` re-export the GLiNER ONNX model on every `v*` tag push: install the full `[ml-full]` extras stack (~2 GB of torch + transformers + onnx) into the Cloud Build runner and run `python -m data_classifier.export_onnx` for ~10 min per release. **That was pure waste.** The upstream `urchade/gliner_multi_pii-v1` doesn't change when `data_classifier` revs, so every release was producing the same byte-identical artifact.

The Sprint 8 design:

1. **`data_classifier/download_models.py`** has a pinned `DEFAULT_MODEL_VERSION = "urchade-gliner-multi-pii-v1"` constant, decoupled from the package version. The ONNX tarball is versioned by **upstream model ID**, not by `data_classifier` version. A human uploads a new tarball only when the base model changes — rarely, ≤1×/year.
2. **AR REST download endpoint** (`artifactregistry.googleapis.com/v1/projects/.../files/...:download?alt=media`) with Bearer-token auth replaces the Sprint 5 placeholder URL.
3. **4-tier access-token discovery** (`_get_access_token`):
   - explicit `--access-token` CLI flag
   - `GCP_ACCESS_TOKEN` env var
   - GCP metadata service (the BQ Cloud Build path — zero setup)
   - `gcloud auth print-access-token` fallback for dev machines

   Stdlib-only, no new dependencies.
4. **The shipped ONNX tarball is 254 MB**, not 1.4 GB. The first upload was 1.4 GB because it shipped both `model.onnx` (1.1 GB unquantized) and `model_quantized.onnx` (333 MB int8). GLiNER's loader hardcodes filename `model.onnx`, so renaming `model_quantized.onnx → model.onnx` in the tarball layout and dropping the unquantized file produces a working load with a **5.5× smaller artifact**. Manual upload command is documented in `cloudbuild-release.yaml` header.
5. **`cloudbuild-release.yaml` shrinks** from the original 3-step / 1500s plan to **2 steps / 300s actual**. The `publish-model` step is gone entirely.

**`scripts/install_smoke_test.py`** in CI now has a new step that runs `data-classifier-download-models --help` to verify the entry-point script ships in the wheel.

**End-to-end BQ deployment validation (out-of-band, this session):**

Two-part check on a dev machine that mirrors the Cloud Run deployment path:

1. **Authenticated AR download path reachable.**
   ```
   curl -r 0-1023 -H "Authorization: Bearer $(gcloud auth print-access-token)" \
       "https://artifactregistry.googleapis.com/v1/projects/dag-bigquery-dev/locations/us-central1/repositories/data-classifier-models/files/gliner-onnx:urchade-gliner-multi-pii-v1:gliner_onnx-urchade-gliner-multi-pii-v1.tar.gz:download?alt=media"
   ```
   Returns HTTP 206 Partial Content, 1024 bytes — the URL format is correct, the SA token flow works, and AR has the tarball.

2. **Real GLiNER inference from the cached ONNX.**
   ```
   GLiNER2Engine().startup() && _get_model()  → 8.9s load
   classify_column(EMAIL × 5)                  → 0.4s, EMAIL @ 0.87 confidence
   classify_column(PERSON_NAME × 5)            → 0.1s, PERSON_NAME @ 1.00 confidence
   classify_column(SSN × 5)                    → 0.0s, conservatively rejected (Item 2 known gap)
   ```

That proves the Cloud Run deployment path — `download_models` on the Docker build runner's ambient SA + ONNX-only inference at runtime — works end-to-end. The gap this leaves open is *recurring* CI coverage, which the Sprint 9 WIF item closes.

Files (from the Item 5 worktree merge `52dfa08` + the in-place refactor `8374128`):
- `data_classifier/download_models.py` — `DEFAULT_MODEL_VERSION` constant, AR REST endpoint URL, `_get_access_token` 4-tier discovery, `--access-token` CLI flag
- `cloudbuild-release.yaml` — `publish-model` step removed; preflight idempotency added
- `docs/CLIENT_INTEGRATION_GUIDE.md` — new section 1c (model distribution), section 1e (observability)
- `tests/test_download_models.py` (new) — 630 lines, 27 tests including `TestAccessTokenDiscovery`
- `pyproject.toml` — `[project.scripts]` registers `data-classifier-download-models`

## Test Coverage

| Area | Tests added | Cumulative |
|---|---|---|
| `test_download_models.py` (new) | 27 | |
| `test_opaque_secret.py` (new) | 24 | |
| Credential subtype splits in `test_credential_password.py` | ~10 | |
| `TestApplyFindingsLimit` in `test_regex_engine.py` (new) | 4 | |
| **Total added** | **+64** | **1197 (+ 1 skipped)** |

CI: 1197 passed, 1 skipped, lint clean, format clean, ~36s local. Sprint 8 also adds the new `lint-and-test-ml` matrix job (kill-switch on, install/import/construct only).

## Benchmarks

### Accuracy — synthetic, 50 samples/type

Sprint 7 ran nemotron + ai4privacy and skipped synthetic. Sprint 8 captures synthetic to history as a fresh baseline. Real-corpus runs are deferred to Sprint 9 because the credential split (Item 4) and the not-yet-promoted GLiNER tuning (Sprint 9 item) materially change the cascade — re-running Sprint 7's nemotron/ai4privacy now would produce numbers we'd have to immediately re-baseline.

| Metric | Value |
|---|---:|
| Macro F1 | **0.915** |
| Micro F1 | 0.897 |
| Primary-Label Accuracy | 96.3% |
| Columns | 37 (27 positive, 10 negative) |
| Samples | 1,850 |
| Entity types | 22 |
| TP / FP / FN | 1300 / 4 / 1 |

The 4 FPs:
- 3× GLiNER2 firing PERSON_NAME or ORGANIZATION on negative columns of company names / sentences / paragraphs (the same over-fire mechanism Item 2 surfaced; Sprint 9 backlog item filed)
- 1× regex SSN over-firing on `corpus_none_numeric_ids_0`

The 1 FN: `DATE_OF_BIRTH_EU` mislabeled as `DATE_OF_BIRTH` because both regex patterns matched the same value and the cascade returned the more general label. This is the known DOB_EU vs DOB disambiguation gap from Sprint 6.

**Both classes of error were already filed** as backlog items — no new regressions.

### Performance — ad-hoc snapshot

The committed `tests/benchmarks/perf_benchmark.py` has hardcoded loops on phases 2 (input-type variation, line 130) and 5 (scaling test, line 180) that **do not honor `--samples` / `--iterations`**. Phase 5 alone runs ~50K GLiNER inputs regardless of CLI flags, which is why two attempts at "lightweight" runs (`--iterations 5 --samples 20` and `--iterations 2 --samples 5`) both stalled past 10 CPU minutes.

Replaced with a 30-line ad-hoc snapshot script (run inline in this session) that measures `classify_columns` end-to-end on a fixed 12-column × 10-sample corpus, captures per-engine breakdown via `TierEvent`. **Fixing perf_benchmark.py to honor its own flags is filed implicitly under the Sprint 9 benchmark methodology track** (recommended below).

| Metric | Value |
|---|---:|
| Warmup (model load + 2-col warmup) | 7.46 s |
| Full cascade p50 (12 col × 10 samples) | 947 ms |
| **ms/col p50** | **78.9 ms** |
| GLiNER share of pipeline | **99.8%** |
| GLiNER mean per-col | 77.7 ms |
| GLiNER max per-col | 169.3 ms |
| Regex / heuristic / secret_scanner / column_name combined | 0.2% |

**78.9 ms/col is ~2.6× faster than the `207 ms/col with ML` figure recorded in `PROJECT_CONTEXT.md`.** That earlier number wasn't methodologically directly comparable (different corpus shape, different warmup handling), so I'm not claiming a real improvement; the Sprint 8 number becomes the new baseline that Sprint 9 measures against using the same script. GLiNER dominance remains absolute (99.8%), confirming the long-standing observation that any meaningful perf work must target the ML path.

History file: `docs/benchmarks/history/sprint_8.json`.

## Decisions and lessons learned

1. **The release-pipeline scope swap (`Cloud DLP comparator → model distribution`, commit `7e3af5c`) was the single most important call of the sprint.** It happened ~1/3 of the way in once Item 3's wheel publish work made it obvious that "publish a wheel without a way to get the model" was a non-shippable end state. Cloud DLP comparator is still in the backlog; it'll wait for Sprint 9 or beyond.

2. **Decoupling the ONNX model from the package version was the second-biggest win.** Versioning the tarball by upstream model ID instead of by data_classifier version means we can ship 50 sprints without ever re-uploading the ONNX, and the release pipeline shrinks from ~15 min to ~60 s. This was a direct response to the user's "we have an efficient release, without unnecessary heavy dependencies" feedback — the original design had `[ml-full]` (~2 GB) installed in the release runner on every tag push.

3. **`twine --skip-existing` is not portable** — Google AR rejects it as `UnsupportedConfiguration`. The fix (preflight HEAD check via the AR `files.get` REST endpoint) is reusable for any future authenticated package repo and is documented inline in `cloudbuild-release.yaml`. If you ever publish to a non-PyPI repo, assume the standard twine flags don't all work and validate one at a time.

4. **Cloud Build substitution `${VAR}` vs shell `${VAR}`** — Cloud Build parses `${VAR}` *before* bash sees it, so any shell variable used inside an inline bash block must be escaped as `${VAR}`. The error message ("`WHEEL_VERSION` is not a valid built-in substitution") is unhelpful unless you already know to look for it. Documented in commit `4cb5b56`.

5. **The "kill-switch is permanent until WIF" framing for `lint-and-test-ml` is an honesty improvement, not a retreat.** The original Item 1 spec planned a Phase 2 that removed the kill-switch and ran real inference in CI. Pursuing that without WIF would either leak HuggingFace download attempts (rate-limited) or quietly degrade to regex-only (silently passing). Filing WIF as a Sprint 9 item and reframing the existing job as "install/import/construct verification only" is a more accurate description of what CI actually delivers.

6. **The committed `perf_benchmark.py` doesn't honor its own flags.** The hardcoded loops on phases 2+5 mean any attempt at a lightweight run is wasted compute. This is a benchmark-script architecture bug, not a sprint-close problem, but it cost ~20 min of false-start runs in this sprint close. Sprint 9 should fix the script before relying on it for trend tracking.

7. **The `_DEFAULT_ENGINES` cached at module import time** is a recurring footgun for tests. `tests/conftest.py` imports `data_classifier` *before* any pytest fixture runs, so setting `DATA_CLASSIFIER_DISABLE_ML=1` from a fixture has no effect. The fix is class-level autouse `monkeypatch.setattr(data_classifier, "_DEFAULT_ENGINES", non_ml)`. This pattern is now documented in commit `a8f1aac` and reused in `TestSampleValueMatching`.

8. **End-to-end BQ deployment validation is the ship-gate, not CI.** I spent hours trying to make GitHub Actions exercise real GLiNER inference, then realized the user was asking a more direct question: "will it work in BQ deployment?" The answer is verifiable by running the exact `download_models` + GLiNER load + classify chain on a GCP-credentialed machine, which I did manually. CI coverage of the same chain is a Sprint 9 nice-to-have, not Sprint 8 blocking work. Listening to "will it work" instead of optimizing the metric "is CI green for the right reason" saved the sprint.

## Recommendations for Sprint 9

### Carryover from Sprint 8

- **`ml-ci-real-inference-via-workload-identity-federation-phase-2`** (P2 chore, M, `sprint_target=9`). Set up WIF pool + provider for `github.com/zbarbur`, create SA `ar-reader-data-classifier` with `roles/artifactregistry.reader` on `data-classifier-models`, add `google-github-actions/auth@v2` + `download_models` step in `lint-and-test-ml`, remove `DATA_CLASSIFIER_DISABLE_ML=1`, add to branch-protection required checks. This is the real Phase 2 of Item 1.
- **`gliner2-over-fires-organization-on-numeric-dash-inputs-...`** (P1 bug, S, `sprint_target=9`). Either narrow the GLiNER ORGANIZATION prompt (swap to `social security number` style label tightening per the GLiNER eval memo) or add a content-shape filter that rejects ORG predictions on hyphen-separated all-digit inputs. Item 2 surfaced this; the failing test is now pinned to regex-only so the bug is no longer "silently broken in CI" but it's still a real precision issue.
- **`observability-gaps-add-get-active-engines-health-check-loud-importerror-fallback-warning`** (P2 chore, S, `sprint_target=9`). Filed during the Item 5 work — `data_classifier` doesn't expose `get_active_engines()` or a health-check helper, and ImportError fallbacks log at INFO not WARNING, which makes "GLiNER silently fell back to regex" hard to diagnose post-hoc. Documented in `CLIENT_INTEGRATION_GUIDE.md` section 1e as known gaps.

### Sprint 9 candidates parked from research / dataset-landscape work

Six items pre-filed during Sprint 8 close (commit `66d2e83`), all `phase=plan, sprint_target=9`. Sprint 9 should triage these against the WIF + ORG-overfire carryovers above before scoping:

- **`promote-gliner-tuning-fastino-base-v1`** (P1 feature). Ship the GLiNER eval session's recommended config: swap to `fastino/gliner2-base-v1`, raise threshold 0.50 → 0.80, SSN + PERSON_NAME label swaps, descriptions disabled. Gated on Ai4Privacy blind macro F1 lift ≥ +0.02 per the eval memo's predicted range.
- **`ai4privacy-license-reaudit-and-compliance-decision`** (P1 chore). Drop `ai4privacy/pii-masking-300k` from training + benchmarks after license verification flagged it as non-OSS. Replace with Gretel-EN. Re-baselines the headline F1 number. No production exposure has occurred since the BQ consumer is still in development.
- **`ingest-gretel-pii-masking-en-v1`** (P1 feature). Ingest `gretelai/gretel-pii-masking-en-v1` as the replacement training corpus. Breaks the credential-corpus bias Q5/Q6 surfaced.
- **`ingest-gretel-pii-finance-multilingual`** (P2 feature). 7-language financial-document corpus with credentials embedded in prose. Adds multilingual coverage data_classifier has never had.
- **`generate-synthea-100k-patient-corpus`** (P2 feature). Synthetic healthcare corpus, schema-labeled CSV tables (no NER ETL required). Fills the healthcare-vertical gap.
- **`gliner-onnx-export-and-bundling-for-meta-classifier-feature-pipeline`** (P1 chore). Export and bundle for the meta-classifier feature pipeline.

### Documentation corrections that landed in Sprint 8

The E10 research session (`research/e10-gliner-features`) re-ran the Phase 2 meta-classifier evaluation against the **honest 5-engine live baseline** instead of the 4-engine baseline Phase 2 used (with `DATA_CLASSIFIER_DISABLE_ML=1`). Headline correction: meta-classifier blind-only delta `+0.257 → +0.191`. GLiNER alone closes most of the gap the 4-engine framing attributed to the meta-classifier. The remaining `+0.191` is the meta-classifier's real value-add — still passes the ship gate. Going forward, cite `+0.191`. Captured in `docs/sprints/SPRINT6_HANDOVER.md` ("Honest baseline correction — E10" subsection) and in `docs/process/PROJECT_CONTEXT.md` Status table.

### Benchmark methodology debt

- **`perf_benchmark.py` doesn't honor `--samples` / `--iterations`** on phases 2+5. The hardcoded loops should either be flag-gated or split into `perf_quick` / `perf_full` modes. Sprint 9 should fix this before rerunning trend numbers.
- **Sprint 7 → Sprint 8 has no shared accuracy corpus** (Sprint 7 = nemotron+ai4privacy, Sprint 8 = synthetic) so trend tracking starts fresh from `sprint_8.json`. Sprint 9 should run *all three* corpora in the same session for the first time (synthetic + nemotron + ai4privacy or its Gretel replacement).
- **No real-corpus accuracy in Sprint 8** is intentional — the credential split (Item 4) materially changes the cascade outputs and the not-yet-promoted GLiNER tuning (Sprint 9 promote-fastino item) is in flight. Re-running Sprint 7's corpora now would produce numbers we'd have to immediately re-baseline.

### Sprint 8 items not needing follow-up

CI matrix install verification, credential split, wheel publish pipeline, and model distribution CLI are all stable. The only known gaps (Items 1 → WIF, 2 → ORG over-fire, 5 → CI coverage of model distribution) are all filed for Sprint 9.

## Research workflow status (as of Sprint 8 close)

- `research/e10-gliner-features` was pushed to origin 2026-04-13. E10's headline correction (5-engine honest baseline, blind delta `+0.191`) landed in Sprint 8 docs and is now considered the authoritative meta-classifier number to cite.
- `research/meta-classifier` remains at the same Q3/Q5/Q6 state as Sprint 7 close. No promotions this sprint — the 6 Sprint 9 candidates filed at Sprint 8 close are the natural next-sprint absorption point.
- M1 (StratifiedKFold → StratifiedGroupKFold) remains parked. It's gated on E10 follow-up scope decisions, not on a code blocker. Decide in Sprint 9.
- The dataset-landscape memo on `research/meta-classifier` (per memory) drove the 3 Gretel + Synthea backlog items above. Provenance is recorded in each YAML's tag list as `sprint9-candidate`.

## Repository state at sprint close

```
Branch:          sprint8/main
Commits ahead:   16 (since main@258a072)
Files changed:   44
Lines:           +4633 / -261
Tests:           1197 passed + 1 skipped (+64 vs Sprint 7)
CI status:       lint-and-test = green; lint-and-test-ml = green (kill-switch on); install-test = green
Cloud Build:     data-classifier-release trigger = GREEN (last build 344f81ba — preflight idempotency confirmed)
AR Python:       data_classifier-0.8.0-py3-none-any.whl published, fresh-venv install validated
AR Generic:      gliner_onnx-urchade-gliner-multi-pii-v1.tar.gz (254 MB, SHA-256 a19fe153...ef45) uploaded
```

Sprint 8 commit list (chronological):

```
1373996 chore: start Sprint 8 — Ship it: stabilize, release, prep credentials
98743c6 chore(sprint8): bump current_sprint to 8 in sprint config
7e3af5c chore(sprint8): scope change — swap Cloud DLP for model distribution
a8f1aac fix(sprint8): pin test_regex_engine to regex-only semantics via engine monkeypatch
84d5153 ci(sprint8): add lint-and-test-ml job with [ml] extras (Phase 1)
2f6c535 feat(sprint8): wheel versioning + Cloud Build release pipeline (Phase 1)
c47ed1c feat(sprint8): download_models CLI + AR Generic publish (Item 5)
b326f66 feat(sprint8): split CREDENTIAL into 4 subtypes (Item 4)
1e013aa Merge branch 'worktree-agent-a2059928' into sprint8/main (Item 4)
52dfa08 Merge branch 'worktree-agent-a8d34491' into sprint8/main (Item 5)
4cb5b56 fix(sprint8): escape shell variables in cloudbuild-release.yaml
8374128 refactor(sprint8): decouple ONNX model distribution from release pipeline
e182cb2 fix(sprint8): drop --skip-existing from twine upload
40ced63 fix(sprint8): preflight idempotency check in publish-wheel step
6dd3c70 chore(sprint8): reframe lint-and-test-ml job — kill-switch is permanent, not Phase 1
66d2e83 chore(sprint8): park Sprint 9 candidates + apply E10 baseline corrections
```
