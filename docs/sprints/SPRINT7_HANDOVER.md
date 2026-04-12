# Sprint 7 Handover — Compare & measure

> **Date:** 2026-04-13
> **Theme:** Compare & measure — ship evidence-gathering infrastructure while research sessions run in parallel
> **Branch:** sprint7/main → merged to main
> **Tests:** 1009 → **1133 passing** (+124)

## Delivered (4 items)

### 1. Dead `_SSN_ADVERTISING_LIST` entries cleanup (P3, chore)

- `data_classifier/engines/validators.py`: removed 10 unreachable `987-65-4320..4329` entries from `_SSN_ADVERTISING_LIST`. These were shadowed by the Sprint 6 ITIN area rule (900–999 rejected before the advertising list check).
- Module comment updated to explain why the range is no longer listed (points at `TestAdvertisingRangeHandledByAreaRule`).
- `tests/test_ssn_validator.py`: new `TestAdvertisingRangeHandledByAreaRule` class with 20 parametrized cases. Includes a stronger-than-normal `monkeypatch`-based test that strips the advertising range from `_SSN_ADVERTISING_LIST` at runtime and proves the area rule rejects all 10 values independently — this pins down the post-refactor invariant and catches any future regression that weakens the area check.
- **TDD discipline:** characterization tests were added *before* the refactor (Red→Green for refactoring adapts to "test exists before behavior-preserving change"). 31 → 51 SSN validator tests.

### 2. International phone format expansion (P2, feature) — **16.3% → 94.5% on Ai4Privacy**

The Sprint 4/5 benchmarks flagged Ai4Privacy PHONE column at 0% regex match. Fixed by two pattern changes in `data_classifier/patterns/default_patterns.json`:

- **`international_phone` regex**: `\+\d{1,3}[-.\s]?\d{4,14}` → `\+\d{1,3}(?:[-.\s]?\d{1,10}){1,7}`. Allows multi-segment mixed-separator formats the old regex couldn't reach: `+44 20 7946 0958` (UK), `+49 30 1234567` (DE), `+33 1 42 34 56 78` (FR), `+543 51-082.8035` (AR), `+51-063-367.7939` (PE). Up to 7 digit groups with any combination of dash/dot/space separators.
- **New `international_phone_local` regex**: `\b(?:00|0)\d{1,4}[-.\s]\d{2,14}(?:[-.\s]\d{1,14}){0,5}\b`. Content-only (no column gating) for trunk-0 / international-access-00 formats: UK `020 7946 0958`, DE `0911 1234567`, Ai4Privacy `076 1352.8018`, `00758-30091`, `01881.881.151-3030`. Required separator + 2–14 digit second group prevents FPs on decimals (`0.5`, `3.14159`) and isolated short digit strings.

Coverage breakdown on the 45,568-row Ai4Privacy PHONE split (per-value regex match with ≥80% value coverage):

| Pattern | Rows matched | Share |
| --- | ---:| ---:|
| `us_phone_formatted` | 5,626 | 12.3% |
| `international_phone` (updated) | 21,899 | 48.1% |
| `international_phone_local` (new) | 15,516 | 34.0% |
| **Total matched** | **43,041** | **94.5%** |

Tests in `tests/test_phone_international.py` (+33 cases):
- `TestInternationalPhonePlusPrefixed` — 9 multi-segment + formats
- `TestInternationalPhoneLocalPrefixed` — 9 trunk-0/00 formats
- `TestExistingUsFormatsNotRegressed` — 5 US format regression tests
- `TestPhoneRegexPrecision` — 9 FP guards (decimals, IBAN, credit cards, too-short strings)
- `TestAi4PrivacyCoverage` — end-to-end coverage test, asserts ≥70%, currently 94.5%

**Design insight:** The first test pass I wrote was at the `classify_columns` pipeline level and passed falsely because `column_name_engine` (authority 10) emits PHONE findings from column name alone, masking the regex gap. Tests for a regex change must assert at the regex level (`re2.compile().search()`) — pipeline tests hide too much.

### 3. Credential password pattern + column-gate architecture (P2, feature) — **0% → 98.6% on Ai4Privacy**

Fixed the Ai4Privacy CREDENTIAL column's 0% content match rate by adding a new column-name-gated pattern for short random passwords, plus a reusable column-gate mechanism in `ContentPattern`.

**Architecture — new column-hint gate mechanism:**

1. `data_classifier/patterns/__init__.py` — `ContentPattern` gains two fields:
   - `requires_column_hint: bool = False` (default, backward-compatible)
   - `column_hint_keywords: list[str] = field(default_factory=list)`

2. `data_classifier/engines/regex_engine.py` — new `_column_hint_allows_pattern` helper + gate check in `_match_sample_values` Phase 2 loop. Patterns with `requires_column_hint=True` are skipped if the column name doesn't contain any keyword (case-insensitive substring match). Patterns without the gate are unaffected.

3. `data_classifier/engines/validators.py` — new `random_password_check` validator:
   - Length in [4, 64]
   - Contains at least one symbol (non-alphanumeric, non-whitespace)
   - Uses at least 3 of {lowercase, uppercase, digit, symbol}
   - Symbol requirement is load-bearing: plain emails, dates, and IPs have 2 classes total, not 3; mixed-case identifiers with digits (`Hello123`) lack a symbol.

4. `data_classifier/patterns/default_patterns.json` — new `random_password` pattern:
   - `regex: \S{4,64}`
   - `entity_type: CREDENTIAL`
   - `requires_column_hint: true`
   - `column_hint_keywords: [password, passwd, passphrase, passcode, secret, pwd, pass_code, user_password, admin_password]`

**Ai4Privacy CREDENTIAL coverage** (validator-level, 37,738 rows): 0.0% → **98.6%** (37,192 matched). 1.4% unmatched are short low-diversity strings (length < 4 or missing symbols).

**Corpus-driven precision check** — ran the ≥3-classes-and-symbol filter against all 8 Ai4Privacy entity types before shipping:

| Entity type | Total | Password-like | Share |
| --- | ---:| ---:| ---:|
| CREDENTIAL | 37,738 | 37,192 | 98.6% |
| EMAIL | 51,407 | 38,792 | 75.5% |
| DATE_OF_BIRTH | 68,312 | 33,446 | 49.0% |
| IP_ADDRESS | 50,843 | 24,776 | 48.7% |
| SSN | 58,106 | 7,476 | 12.9% |
| ADDRESS | 33,172 | 1,619 | 4.9% |
| PERSON_NAME | 93,814 | 3,838 | 4.1% |
| PHONE | 45,568 | 165 | 0.4% |

The 49%–75% FP rates on EMAIL/DOB/IP look alarming but are handled by the column gate: random_password only fires when `column_name` contains a password keyword, so email under `email_address` or DOB under `date_of_birth` never reaches the validator.

Tests in `tests/test_credential_password.py` (+29 cases):
- `TestRandomPasswordPatternExists` — pattern + gate config sanity
- `TestRandomPasswordValidator` — accepts real passwords, rejects emails/IPs/dates/single-class/too-short/too-long
- `TestPasswordColumnClassification` — end-to-end match_ratio ≥ 0.5 under `column_name='password'`
- `TestColumnGatePreventsFalsePositives` — password-like content under `notes` and `user_id` columns does NOT get CREDENTIAL finding
- `TestAi4PrivacyCredentialCoverage` — full 37,738-row corpus coverage

**Reusable infrastructure:** The `requires_column_hint` + `column_hint_keywords` mechanism can be adopted by any future pattern that has catastrophic FPs absent a column hint (generic API tokens, short numeric IDs, internal product codes).

### 4. Presidio comparator infrastructure (P2, feature)

Builds the comparator layer under `tests/benchmarks/comparators/` so we can run Microsoft Presidio on the same benchmark corpora and compute parallel precision/recall/F1.

**Structure:**

- `tests/benchmarks/comparators/__init__.py` — package marker
- `tests/benchmarks/comparators/presidio_comparator.py` (~290 lines):
  - `STRICT_MAPPING` and `AGGRESSIVE_MAPPING` entity dicts
  - `translate_entities()` — duck-typed on `RecognizerResult` shape (has `.entity_type` + `.score`), so unit tests pass mock stand-ins without importing `presidio_analyzer`
  - `run_presidio_on_column` / `run_presidio_on_corpus` — lazy-import the `AnalyzerEngine`; raises `RuntimeError` with an actionable install hint if the `[bench-compare]` extra is missing
  - `compute_corpus_metrics()` — aggregates per-column TP/FP/FN using `compute_column_comparison` for agreement-level bookkeeping
  - `format_side_by_side_table()` — text-only comparison table
- `docs/benchmarks/presidio_mapping.md` — mapping rationale with update workflow; kept in lockstep with the Python dicts
- `pyproject.toml` — new `[bench-compare]` extra pulling `presidio-analyzer>=2.2` and `spacy>=3.7` (optional; not installed by default)
- `tests/benchmarks/consolidated_report.py` — new `--compare presidio` and `--compare-mode {strict,aggressive}` flags. Runs the 4 standard configs through Presidio too, prints a side-by-side table to stderr, and writes a disagreement JSONL to `docs/benchmarks/SPRINT{N}_PRESIDIO_DISAGREEMENTS.jsonl`

**Dual mapping modes** — shipped together so the same raw Presidio output gets two interpretations:

| Mode | Semantics | Additional pairs (vs strict) |
| --- | --- | --- |
| Strict | 1:1, no semantic drift | 9 pairs (US_SSN→SSN, CREDIT_CARD→CREDIT_CARD, EMAIL_ADDRESS→EMAIL, PHONE_NUMBER→PHONE, IP_ADDRESS→IP_ADDRESS, IBAN_CODE→IBAN, URL→URL, US_DRIVER_LICENSE→DRIVERS_LICENSE, MEDICAL_LICENSE→DEA_NUMBER) |
| Aggressive | Strict + looser cross-category | `PERSON→PERSON_NAME`, `LOCATION→ADDRESS`, `DATE_TIME→DATE_OF_BIRTH`, `US_BANK_NUMBER→BANK_ACCOUNT`, `US_ITIN→NATIONAL_ID`, `US_PASSPORT→NATIONAL_ID`, `UK_NHS→MEDICAL_ID` |

Tests in `tests/test_presidio_comparator.py` (+34 cases across 7 classes): mapping pairs, translation dedup, column comparison agreement flags, corpus metrics aggregation, side-by-side table formatting, CLI flag parsing, and one live-engine integration test gated with `pytest.importorskip("presidio_analyzer")`.

**Execution deferred:** Only the infrastructure is shipped. The actual Presidio run against the benchmark corpora is explicitly deferred to a dedicated session (see the item's notes field in the backlog). Step-by-step resume instructions captured there: install `[bench-compare]`, download spaCy `en_core_web_lg`, run `consolidated_report --compare presidio`, commit the disagreement JSONL + summary note.

## Partial (1 item — docs-only increment, code deferred)

### 5. M1 meta-classifier CV fix — SPRINT6_HANDOVER.md methodology correction (P0, bug — code deferred to Sprint 8)

A brand-new Sprint 7 item added mid-session after reading the `Methodology corrections` section of `docs/experiments/meta_classifier/queue.md` (on `origin/research/meta-classifier`). Discovered by Q3 LOCO investigation — the production `scripts/train_meta_classifier.py` uses `StratifiedKFold` for best-`C` selection, which lets every corpus leak into every CV fold and rewards corpus fingerprinting at C=100.

**What landed in Sprint 7 (docs-only):**

- `docs/sprints/SPRINT6_HANDOVER.md` — new "Methodology correction — M1" subsection under Known Issues. Cites Q3 `result.md` §5a (regularization sweep table with honest LOCO numbers) and §6 (hypothesis verdict). Corrects the Sprint 6 headline "CV macro F1 = 0.916" → flags it as a memorization artifact; honest LOCO mean is ~0.30. Explicitly states what the M1 code fix can and cannot deliver.
- `backlog/m1-meta-classifier-cv-fix-....yaml` — acceptance criteria rewritten. The original spec (written 2026-04-12 based on the queue.md summary) had an impossible criterion — `cv_mean within 0.10 of loco_mean_macro_f1` — that implied the splitter fix would collapse the gap. Q3's primary source shows the splitter fix closes ~6% of the gap (not ≥50%), and the remaining gap is structural (A+C dominate per §6). Corrected criterion targets an honest ~0.034 LOCO improvement toward ~0.3427, not convergence.

**What's deferred to Sprint 8:** The one-line splitter swap, retrain, install smoke test, and `sharding_strategy.md` §6 update. Deferred because:

1. `research/e10-gliner-features` is still running locally in `../data_classifier-e10` as of 2026-04-13 and has not been pushed. Its diff against `scripts/train_meta_classifier.py` is not observable from origin. Rule from `project_active_research.md` forbids reading that worktree directly.
2. Research-ops session (the parallel Claude session merging research results) offered coordination on M1 handoff and E10 landing-order.
3. Retraining needs the `[meta]` optional extra — better batched with a coordinated meta-classifier session.

Resume instructions are in the backlog item's notes field.

## Deferred to Sprint 8 (2 items)

1. **M1 meta-classifier CV fix — code + retrain** (P0 bug). Docs-only increment landed in Sprint 7 (item 5 above). Code+retrain deferred pending E10 visibility and research-ops coordination. Full context in the backlog item's notes.
2. **Cloud DLP comparator benchmark** (P2 feature). Not started. Presidio comparator's infrastructure (module layout, dual mapping pattern, `compute_corpus_metrics`, `format_side_by_side_table`, CLI flag structure, mapping doc format, disagreement JSONL) is ready to reuse with Cloud DLP–specific deltas: `cloud_dlp_comparator.py` mapping Google DLP `InfoType` → our types, likelihood-enum quantization, `[bench-compare-cloud]` optional extra, graceful `GOOGLE_APPLICATION_CREDENTIALS` handling, and a `cloud_dlp_mapping.md` doc.

## Key Decisions

1. **Worktree isolation for parallel Claude sessions is now standard practice.** Mid-session we discovered another Claude session was doing research/meta-classifier merges in the main worktree, which reverted our Sprint 7 edits via branch switches. We stopped, diagnosed via the reflog, created `../data_classifier-sprint7` as an isolated worktree with `sprint7/main` checked out, and finished the sprint there. The research-ops session apologized and created its own `../data_classifier-research-ops`. The new memory file `feedback_never_switch_branches_in_main_worktree.md` captures this rule.

2. **"Compare & measure" theme validated by research workflow.** The sprint's thematic decision was to ship evidence-gathering (comparators) while research sessions investigated the meta-classifier LOCO collapse. Three research sessions (Q3, Q5, E10) ran on isolated worktrees off `research/meta-classifier`. Q3 and Q5 landed during Sprint 7 (both merged into research/meta-classifier with detailed result.md files). E10 is still running. Sprint 7 did not touch any meta-classifier training code, avoiding all collision risk with the research thread.

3. **Column-gate as first-class pattern capability, not a workaround.** The credential regex problem could have been solved by a narrow content regex + aggressive post-filtering in the orchestrator. Instead we introduced `requires_column_hint` + `column_hint_keywords` as new fields on `ContentPattern`, plumbed through `regex_engine._match_sample_values`. This is 10 lines of new production code and is reusable for any future pattern whose precision fundamentally depends on column context. Backward compatible — the default is `False`.

4. **Presidio adapter uses duck typing for testability.** `translate_entities` takes `list[Any]` and reads `.entity_type` + `.score` attributes, rather than importing `RecognizerResult`. This lets 34 unit tests run on a machine where `presidio-analyzer` isn't installed (via a 4-field `_MockRecognizerResult` dataclass). The one live-engine test is gated with `pytest.importorskip`. Same pattern will be reused for Cloud DLP.

5. **Docs-only M1 correction is shipped work.** When reading Q3's primary source revealed my earlier M1 spec had an impossible acceptance criterion ("convergence within 0.10"), the right move was not to silently fix it and ship the code anyway. Instead: flag the spec error explicitly, rewrite the acceptance criteria with honest Q3-backed numbers, land the SPRINT6 methodology correction note as its own commit, and defer the code change. This aligns with the project's `feedback_discuss_deviations.md` rule.

6. **TDD-for-refactoring adapts, doesn't apply rigidly.** For the SSN cleanup (pure behavior-preserving refactor), I couldn't write a test that genuinely fails in the traditional Red sense — removing dead code doesn't change behavior. Instead, the TDD step became "add a characterization test that captures the invariant we want to preserve, confirm it passes against current code (before the refactor), run the refactor, confirm it still passes." The `monkeypatch`-based test that strips entries from `_SSN_ADVERTISING_LIST` at runtime is a particularly strong form of characterization test — it proves the area rule is the *real* mechanism independent of the list.

## Architecture Changes

### New subsystems

- **Column-gate mechanism** (`data_classifier/patterns/__init__.py` + `data_classifier/engines/regex_engine.py`). First-class capability for patterns that require column-name context to fire. Opt-in via the `requires_column_hint` field. Every existing pattern is unaffected.
- **Benchmark comparator framework** (`tests/benchmarks/comparators/`). Package structure, dual mapping pattern (strict/aggressive), `compute_corpus_metrics` aggregation, `format_side_by_side_table` text output, `_run_presidio_comparison` CLI integration in consolidated_report, disagreement JSONL writer. Designed for N-way comparators; Cloud DLP slots in directly.

### Pattern library additions

- `international_phone` — regex expanded from single-separator to multi-segment mixed-separator (Sprint 7 coverage on Ai4Privacy: 48.1% of 45,568 PHONE rows)
- `international_phone_local` — new content-only pattern for trunk-0/00 formats (34.0% of 45,568 PHONE rows)
- `random_password` — new column-gated content pattern for short random mixed-class strings (98.6% of 37,738 CREDENTIAL rows)

Pattern count: 56 → **58**.

### Public API additions

- `ContentPattern.requires_column_hint: bool = False` (dataclass field)
- `ContentPattern.column_hint_keywords: list[str] = []` (dataclass field)
- `VALIDATORS["random_password"]` (validator function, mixed-class + symbol + length check)

### Backward compatibility

- All new fields default to off/empty — existing patterns unchanged.
- Column-gate only fires when `requires_column_hint=True` on a pattern. No existing pattern sets this flag. Zero observable behavior change for existing workflows.
- The Presidio comparator is an additive subsystem in `tests/benchmarks/`. Nothing in `data_classifier/` imports from it; nothing in the library behaves differently based on its presence.
- The `[bench-compare]` optional extra is not pulled by `[dev]`. Default dev environment is unchanged.

## Known Issues

1. **M1 (CV fix) code + retrain deferred.** Sprint 7 landed the docs-only methodology correction with honest numbers. The actual splitter change + model retrain are in Sprint 8, gated on E10 scope visibility. See the M1 backlog item's notes for resume instructions.
2. **Presidio benchmark run deferred.** Infrastructure is shipped and unit-tested (34 tests). The actual Presidio execution against the 4 benchmark configs (+ disagreement JSONL) is deferred to a dedicated session. Resume instructions in the Presidio item's notes field. Likely batched with Cloud DLP when that lands.
3. **Cloud DLP comparator not started.** Deferred to Sprint 8. The Presidio infrastructure makes this mostly mechanical — InfoType mapping, likelihood enum quantization, `[bench-compare-cloud]` extra, auth-error handling.
4. **Inherited from Sprint 6, not addressed here.** The meta-classifier LOCO gap is structural (Q3 A+C verdict, confirmed by Q6). E10 (still running) is the remaining candidate for closing the gap via GLiNER features. No Sprint 7 work touched this.

## Lessons Learned

1. **Measure the corpus before writing regex.** For international phone, I started thinking "fix international_phone" until I ran a distribution analysis on the actual 45,568-row PHONE split and discovered 52% `+`-prefixed / 48% non-`+`. A `+`-only fix would have capped at 52% — 18 points below the 70% target. The `international_phone_local` pattern was only recognizable as necessary after the distribution analysis. Corpus-driven design is not optional for pattern work.

2. **Regex tests must assert at the regex level, not the pipeline level.** The first pass of phone tests I wrote ran through `classify_columns` and passed falsely because `column_name_engine` (authority 10) emits PHONE findings from column name alone. Rewriting them to compile each regex with `re2.compile()` and test full-value coverage revealed the true 16.3% starting coverage. For any test targeting a regex change: **compile the regex directly**.

3. **Primary source beats distilled summary for acceptance criteria.** My M1 spec was written from the queue.md distilled summary of Q3's findings, which was accurate but incomplete. Reading Q3's actual `result.md` §5a and §6 revealed that my "convergence within 0.10" criterion was mathematically impossible from the splitter fix alone. Always read the primary source before writing acceptance criteria for work derived from research.

4. **Worktree isolation is mandatory for concurrent Claude sessions.** Mid-sprint, another Claude session doing research merges in the main worktree silently reverted my edits via branch switches. The reflog made the picture legible, the `using-git-worktrees` skill provided the fix, and the new memory file prevents a repeat. Rule: if any other session might touch the main worktree, use a dedicated sibling worktree (`../<project>-<branch-label>/`).

5. **Docs-only increments are shipped work.** Landing the SPRINT6 methodology correction note is a real deliverable — it prevents a future session from retraining against impossible criteria. When you discover a spec is wrong mid-sprint, the docs fix is often more valuable than the code would be.

6. **Duck-type external-library adapters for testability.** The Presidio `translate_entities` function accepts `list[Any]` and reads `.entity_type` + `.score`. A 4-field mock dataclass lets 34 unit tests run on a machine without Presidio installed. Same pattern will be reused for Cloud DLP, and is worth adopting for any future external-library integration.

7. **Over-measurement is cheap; under-measurement is expensive.** Three items (SSN, phone, credential) shipped with tight quantitative acceptance criteria backed by the Ai4Privacy corpus. Two overshot their targets massively (phone: 70% → 94.5%; credential: 50% → 98.6%). That overshoot is evidence the filter shapes are well-calibrated, not luck — it came directly from measuring the corpus distribution before picking the regex. When a target is set by a real corpus, run the filter over the corpus *during design*, not after shipping.

## Test Coverage

| Area | Tests added | Cumulative |
|---|---|---|
| SSN validator (new TestAdvertisingRangeHandledByAreaRule) | 20 | |
| Phone international (new test_phone_international.py) | 33 | |
| Credential password (new test_credential_password.py) | 29 | |
| Presidio comparator (new test_presidio_comparator.py) | 34 | |
| Miscellaneous (pattern auto-tests for the new pattern) | 8 | |
| **Total added** | **+124** | **1133** |

CI: 1133 passed, 1 skipped (Presidio live-engine integration test, gated on `[bench-compare]` extra), lint clean, format clean, ~13s local.

## Recommendations for Sprint 8

### Carryover from Sprint 7 (highest priority)

- **M1 meta-classifier CV fix — code + retrain** (P0 bug, S, `sprint_target=8`). Gated on E10 landing or research-ops coordination on E10's scope. Spec already corrected with honest Q3-backed numbers; resume instructions in the notes field.
- **Cloud DLP comparator benchmark** (P2 feature, M, `sprint_target=8`). Mostly mechanical given Presidio infrastructure. Expected delta: 30–45 min of TDD build + docs + mapping.
- **Execute the Presidio + Cloud DLP benchmark runs** — the dedicated session (not a separate backlog item today, but worth mentioning). Install `[bench-compare]` + `[bench-compare-cloud]`, download the spaCy model + GCP auth, run `consolidated_report --compare presidio --compare-mode {strict,aggressive}` and `--compare cloud_dlp`, commit the disagreement JSONL files.

### Release engineering — wheel versioning + BQ delivery automation (Sprint 8 candidate)

Discovered during Sprint 7 end: **the BQ connector already consumes `data_classifier` as a vendored wheel**, not via git URL:

```
BigQuery-connector/vendor/data_classifier-0.1.0-py3-none-any.whl  (93,623 bytes, built 2026-04-13 01:08)
BigQuery-connector/pyproject.toml:25  "data_classifier[ml] @ file:vendor/data_classifier-0.1.0-py3-none-any.whl"
```

This means **git-free client deployment works today** — but via a manual copy step that has several problems we should fix in Sprint 8:

1. **Pinned version is permanently `0.1.0`.** `pyproject.toml::version` has said `0.1.0` since Sprint 1 and we never bump it. Every wheel we build is `data_classifier-0.1.0-py3-none-any.whl`. BQ cannot pin to a specific feature set — there's no way to tell "this wheel has the phone expansion from Sprint 7" apart from "this wheel is from Sprint 4" except by file mtime. This is a hard blocker for any multi-client story and even for internal rollback.

2. **No version-bump automation.** Nothing forces us to update the version when we ship. Sprint close is the natural trigger but it's not wired in.

3. **No automated wheel delivery to BQ.** Someone (the BQ session, probably) manually built the wheel at 01:08 AM today and copied it into the `vendor/` dir. Every Sprint ship requires that manual step, which is bug-prone (wrong commit, stale build, forgot to copy).

4. **No release tagging.** Our git tags don't correspond to wheel versions. No CHANGELOG.md. No obvious way for BQ to know "is the vendored wheel current?"

5. **CI already builds the wheel and smoke-tests it** (the Sprint 6 `install-test` job) — but it discards the wheel afterward. The infrastructure that would let us *publish* the wheel artifact already exists; we just need to add 3 lines of `actions/upload-artifact@v4` or an `actions/create-release`-style step.

**Proposed Sprint 8 scoping (new backlog item):**

- **Title:** Wheel versioning + automated release to BigQuery-connector vendor path
- **Priority:** P1 (lifts a blocker for BQ integration and any future client)
- **Complexity:** M (somewhere between the "upload artifact" option and the "Google Artifact Registry" option)
- **Shape:**
  - Bump `pyproject.toml::version` on each sprint close (automate this in the sprint-end skill or via a CI check that fails if the version matches `origin/main`)
  - Define a semver or sprint-keyed version scheme (`0.7.0` for Sprint 7, `0.8.0` for Sprint 8, etc.)
  - Add `CHANGELOG.md` with per-sprint entries generated from the handover docs
  - On tag push (`v*`), CI builds the wheel and uploads it as a GitHub release asset OR to a private PyPI (Google Artifact Registry, if BQ is already on GCP)
  - Update `docs/CLIENT_INTEGRATION_GUIDE.md` with the new install recipe (`pip install data_classifier @ https://github.com/zbarbur/data-classifier/releases/download/v0.7.0/...` or `pip install --index-url <artifact-registry> data_classifier==0.7.0`)
  - Optional: a `release.yml` workflow that opens a PR against `BigQuery-connector/vendor/` with the new wheel, so BQ rolls forward with a review step rather than a manual copy

**Why this is urgent for Sprint 8:** Sprint 7 just shipped 3 correctness/coverage wins (phone, credential, SSN) and 1 new infrastructure subsystem (comparators). The BQ project cannot consume any of them until someone manually rebuilds and copies the wheel — and when they do, the version will still say `0.1.0`, so nothing pins it. Every sprint we defer this, the gap between "what's in sprint7/main" and "what BQ actually runs" grows. The fix is tractable (S or M depending on scope) and removes the "BQ coordination" friction from every future sprint.

**Non-decision:** the wheel+artifact *strategy* (GitHub release asset vs Google Artifact Registry vs private PyPI) is a policy question the user should decide. Don't pre-commit a direction in the backlog spec — leave the `technical_specs` field with "[chosen delivery mechanism — needs user decision]" and tag the item with `needs-decision`.

### Likely Sprint 8 themes (not scoped yet)

- **Research-derived promotions:** Depending on E10's verdict, there may be a "promote meta-classifier v2" item that lands the new model as a live finding (out of shadow).
- **Backlog items that share infrastructure with Sprint 7:** the column-gate mechanism introduced for random_password is reusable for any "looks like content X but only in column Y" pattern. Candidates in the backlog: `consumer-injectable-custom-patterns`, `dictionary-lookup-engine`.

### Sprint 7 items not needing any follow-up

SSN cleanup, international phone, credential regex, and Presidio comparator infrastructure are all stable deliverables with full test coverage. No known bugs.

## Research Workflow Status (as of Sprint 7 close)

- `research/meta-classifier` is on origin at `c61d...c5f6` (Q3, Q5, Q6 all merged)
- `research/e10-gliner-features` is local-only in `../data_classifier-e10`, still running
- Main-thread sessions now use dedicated sibling worktrees for side-branch operations (new memory rule). The `research-ops` session owns `../data_classifier-research-ops`; Sprint 7's own worktree was `../data_classifier-sprint7`.

Merging `research/meta-classifier` into main is still expected to happen at natural Sprint cadence, not ad-hoc — Q3/Q5/Q6 results are authoritative for methodology corrections (M1/M2/M3) and those land via regular sprint items citing research results, not via direct research-branch merges.
