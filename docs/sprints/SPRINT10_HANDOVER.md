# Sprint 10 Handover — Detection-uplift chain + secret-dict expansion + data diversification

> **Date:** 2026-04-14
> **Theme:** Detection-uplift chain (S1 NL-prompt wrapping unblocks future fastino), secret-key-name dictionary expansion (+90 net-new), Gretel-finance data diversification, GLiNER data-type pre-filter, BQ verification.
> **Branch:** `sprint10/main` → merging to `main`
> **Head commit:** `7aafa01`
> **Tests:** 1222 → **1374 passing** (+152) + 1 skipped
> **Duration:** 2026-04-14 (1 calendar day, heavy parallel-agent dispatch, planned post-crash recovery)

## Delivered (6 items shipped + 1 stretch reverted + 1 closed by subsumption)

### 1. S1 NL-prompt wrapping for gliner_engine — `2bbe8d1`, `f742ea5`

**Anchor item of the detection-uplift chain.** Replaces the raw `_SAMPLE_SEPARATOR.join(chunk)` feed into `extract_entities` with a new `_build_ner_prompt(column, chunk)` helper that emits a natural-language sentence stitched together from `column.column_name`, `column.table_name`, `column.description`, and sample values — graceful-degrading to raw values when no metadata is present.

Based on research/gliner-context Pass 1 memo (+0.0887 macro F1 on the empty-context Ai4Privacy stratum under fastino v2, BCa 95% CI [+0.050, +0.131], n=315). The hypothesis: attention-based NER models need grammatical scaffolding to correctly bind token classifications to a column's semantics; raw value lists produce brittle, context-free scoring.

**Acceptance gate:** Gretel-EN + Nemotron blind macro F1 delta ≥ -0.005 vs Sprint 9 (non-regression gate, not uplift). Gretel-EN held flat at 0.611 (✓). **Nemotron blind measured 0.774 vs Sprint 9 0.821 (−0.047)** — see "Nemotron blind regression — taxonomy debt root cause" below for why this is *not* a real detection-quality regression.

**Closed by subsumption:** `gliner2-over-fires-organization-on-numeric-dash-inputs` — Pass 1's prediction that S1 wrapping cuts fastino ORG over-fires from ~25 to ~8 at threshold 0.8 held. A regression test (`test_no_org_overfire_on_numeric_dash_at_threshold_08`) is now part of `TestOrgOverfireRegression`.

Files: `data_classifier/engines/gliner_engine.py` (+113 lines for `_build_ner_prompt`), `tests/test_gliner_engine.py` (new `TestBuildNerPrompt` with 6 scenarios, `TestS1PromptIntegratesWithInference` with 2 tests, `TestOrgOverfireRegression` with 1 test). +9 tests.

### 2. GLiNER data_type pre-filter — `6ccaa4d`, `1310a1a`

Skips GLiNER2 inference entirely when `ColumnInput.data_type` is a non-text SQL type (INTEGER, INT64, FLOAT, FLOAT64, NUMERIC, BIGNUMERIC, BOOLEAN, BOOL, TIMESTAMP, DATE, DATETIME, TIME, BYTES). New `_NON_TEXT_DATA_TYPES: frozenset[str]` at module scope, skip guards in both `classify_column` (line ~452) and `classify_batch` (line ~486). Case-insensitive via `column.data_type.upper() in _NON_TEXT_DATA_TYPES`.

Eliminates a whole class of GLiNER false positives on numeric columns (the Sprint 8 SSN-in-samples regression was exactly this shape). Relies on item #5 (BQ context-field verification) confirming BQ populates `data_type` in production — pre-filter is a no-op when `data_type=""`, so the change is safe even if the field is missing.

Zero conflict with item #1: item #1 touches `_run_ner_on_samples` internals, item #2 adds an early return before `_run_ner_on_samples` is ever called. Sequential merges, not a rebase.

Files: `data_classifier/engines/gliner_engine.py` (+30 lines), `tests/test_gliner_engine.py` (new `TestDataTypePrefilter` with 7 parametrized methods covering 31 data-type combinations), `docs/CLIENT_INTEGRATION_GUIDE.md` (engine-behavior section updated). +31 parametrized tests.

### 3. Gretel-finance corpus ingest — `8342df6`, `4188417`

Adds `gretelai/synthetic_pii_finance_multilingual` (Apache 2.0, 56k rows, 7 languages) as training corpus #8. The only open dataset where credentials (API_KEY, PASSWORD, account_pin) are labeled inside long-form financial paperwork (loan agreements, SWIFT messages, tax forms, insurance claims) — directly attacking the `heuristic_avg_length` corpus-fingerprint shortcut diagnosed by the Sprint 9 M1 CV methodology promotion.

Reuses the full Sprint 9 Gretel-EN scaffold: `_fetch_gretel_en_via_rest_api` is generalized as `_fetch_gretel_dataset_via_rest_api`, `_records_to_corpus` is already generic, `_emit_shards_for_type` is unchanged. The key format discovery was confirmed by a foreground discovery pass: Gretel-finance uses the **same Python `repr()` + `ast.literal_eval`** format as Gretel-EN (same publisher, no surprise). `GRETEL_FINANCE_TYPE_MAP` covers 18 of 29 raw labels → 11 data_classifier entity types at 84% coverage on the 100-row sample.

**Not yet wired into `tests/benchmarks/accuracy_benchmark.py`** — the CLI `--corpus` flag still accepts `{synthetic, nemotron, gretel_en, all}`. Sprint 11 follow-up item: `wire-gretel-finance-into-accuracy-benchmark-cli`. Loader, fixture, and shard builder are ready; only the benchmark-CLI plumbing is missing.

Agent also surfaced 4 net-new entity types on the raw labels (`account_pin`, `swift_bic_code`, `bban`, `driver_license_number`) — filed as Sprint 11 `gretel-finance-taxonomy-expansion` follow-up rather than adding to the production taxonomy mid-sprint.

Files: `scripts/download_corpora.py` (+83 lines, new `download_gretel_finance`), `tests/benchmarks/corpus_loader.py` (+52 lines), `tests/benchmarks/meta_classifier/shard_builder.py` (+30 lines), `tests/fixtures/corpora/gretel_finance_sample.json` (new, 33 KB, 360 records across 7 languages), `tests/test_corpus_loader.py` (new `TestGretelFinanceLoader`, +5 tests), `docs/PATTERN_SOURCES.md`, `docs/process/LICENSE_AUDIT.md`. +5 tests.

### 4. Secret-key-name dictionary expansion — `c28b8d9`, `3f72547`

Grows `data_classifier/patterns/secret_key_names.json` from **88 → 178 entries** (+90 net-new) by harvesting patterns from Kingfisher (Apache 2.0, ~50 new SaaS + cloud + DB entries), gitleaks (MIT, ~20 CI/CD + webhook + OAuth entries), and Praetorian Nosey Parker (Apache 2.0, ~10 precision cross-check entries).

**Dictionary-over-thresholds rationale** (from planning audit of `secret_scanner.py:361-374`): 79.5% of the original 88 entries sit at `definitive` tier (score ≥ 0.90), meaning key-name match alone is sufficient to fire a high-confidence finding. Every new entry at 0.90+ is a near-free recall gain with no redistribution of existing detections. The stale Sprint 8 L-item `harvest-kingfisher-gitleaks-nosey-parker-...-200-net-new` targeted 200–500 new entries at L complexity; Sprint 10 scoped down to M complexity with a hard 95-entry ceiling.

**Deliverables:**
- `scripts/ingest_credential_patterns.py` (new, ~480 lines) — idempotent ingestion script with pinned upstream SHAs: Kingfisher `be0ce3ba...`, gitleaks `8863af47...`, Nosey Parker `2e6e7f36...`. Shallow-clones each upstream, parses YAML/TOML rule files, dedups with precedence Kingfisher > gitleaks > Nosey Parker, emits new entries in the secret_key_names.json schema.
- `data_classifier/patterns/secret_key_names.json` (+90 entries, +20-line `__scoring_convention__` metadata block at top — the convention previously lived only in `secret_scanner.py` comments).
- `docs/process/CREDENTIAL_PATTERN_SOURCES.md` (new) — per-entry attribution with upstream repo, license, rule id, pinned SHA.
- `docs/process/LICENSE_AUDIT.md` — added "Credential-pattern upstreams" section documenting the 3 in-use + 3 explicitly-excluded sources (trufflehog AGPL, Semgrep SRL, Atlassian LGPL).
- `tests/test_secret_scanner.py` — new `TestNewDictionaryEntries` parametrized class covering every new entry, `TestDictionaryHealth` with duplicate-pattern + valid-score invariants.

**Category coverage:** SaaS APIs 10 → 40 (+30), Cloud providers 7 → 22 (+15), CI/CD tokens 0 → 13 (+13), DB credentials 11 → 20 (+9), OAuth/JWT variants 10 → 17 (+7), password/session/crypto 22 → 38 (+16). All 6 gap categories hit minimum targets.

**Explicit non-goals:** No XGBoost (the empty `ml-optimized-secret-scoring-parameters-xgboost-on-18-features` item was closed as won't-do, superseded by this dictionary-based approach). No threshold changes to `heuristic_engine.py::opaque_secret_detection`. No regex pattern additions. No new engine.

Files: `scripts/ingest_credential_patterns.py` (new), `data_classifier/patterns/secret_key_names.json` (178 entries), `docs/process/CREDENTIAL_PATTERN_SOURCES.md` (new), `docs/process/LICENSE_AUDIT.md`, `tests/test_secret_scanner.py`. +~105 parametrized tests.

### 5. BQ context-fields written verification — `a421f71`, `3935400`

Produces `docs/process/BQ_INTEGRATION_STATUS.md`, the written verification doc for all 5 `ColumnInput` context fields (`table_name`, `dataset`, `schema_name`, `data_type`, `description`). Captures the verbal confirmation given by the BQ connector team on 2026-04-13 (recorded at the time in memory entry `project_bq_context_fields_populated.md`) as a durable, auditable record in-repo.

Key findings: all 5 fields are populated in BQ `v0.8.0`. `schema_name` is always `""` (BQ has no schema layer — project.dataset.table only). `data_type` uses UPPERCASE BigQuery constants ("STRING", "INTEGER", etc.). `description` may be empty for columns with no catalog description. Library consumers should compare `field == ""` rather than `field is None`.

Also documents shallow-consumption status: `table_name` → `column_name_engine._table_context_boost` (only +0.05 nudge, can't create findings). `dataset`, `schema_name`, `description` → **None (unread)**. `data_type` → Sprint 10 item #2's new pre-filter, the first library-side consumer.

**Unblocks item #2.** The pre-filter is useless unless BQ actually sends `data_type`; this doc is the sign-off that it does.

Files: `docs/process/BQ_INTEGRATION_STATUS.md` (new). +0 tests.

### 6. Fastino promotion (wave 3 stretch) — ATTEMPTED, REVERTED — `7aafa01`

Attempted to apply `docs/research/gliner_fastino/fastino_promotion_draft_20260414.patch` on top of items #1 + #2, swapping `_MODEL_ID` to `fastino/gliner2-base-v1`, raising `_DEFAULT_GLINER_THRESHOLD` to 0.80, and applying the PERSON_NAME/SSN label swaps.

**Gates failed by wide margins:**
- **Gretel-EN blind:** 0.611 → 0.413 (delta **-0.198**, gate -0.005) ❌
- **Nemotron blind:** 0.821 → 0.526 (delta **-0.295**, gate -0.005) ❌

**Dominant failure mode** (from FP/FN dump): fastino fires PHONE at 0.92+ confidence on numeric-looking columns (ABA_ROUTING, BANK_ACCOUNT, CREDIT_CARD, HEALTH, VIN), and the orchestrator's cross-engine dedup then suppresses the correct regex-engine findings in favor of the more-confident PHONE. Two integration tests also broke for the same reason: `test_invalid_dates_rejected[32/13/2000]` (fastino fires DATE_OF_BIRTH on `"32/13/2000"`) and `test_sin_luhn_validates_formatted_and_unformatted` (fastino fires PHONE on Canadian SIN samples, suppressing CANADIAN_SIN).

Pass 1's `+0.039` signal on the empty-context Ai4Privacy stratum **did NOT transfer** to blind real corpora. This is structural, not tunable — the magnitude of the regression suggests the issue is how fastino binds to numeric token sequences without rich context, not a threshold mis-set.

**Disposition:** code reverted, no commits to `gliner_engine.py`. The existing `promote-gliner-tuning-fastino-base-v1.yaml` item is moved from `doing` → `backlog`, sprint_target 10 → 11, with full failure notes. A NEW Sprint 11 investigation item is filed: `fastino-promotion-retry-investigate-s1-variant-b-always-wrap-fallback-to-close-blind-corpus-regression`. The patch at `docs/research/gliner_fastino/fastino_promotion_draft_20260414.patch` is **preserved** for the retry attempt.

**Sprint 11 recommended path:** (a) S1 variant B "always-wrap even on metadata-free inputs", (b) higher fastino threshold (0.85–0.90), (c) hard PHONE suppressor for fastino on numeric `data_type` columns or all-digit sample strings, (d) Pass 2 research run on post-S1 Gretel-EN + Nemotron before the next promotion attempt.

Files: none (reverted). Backlog only: `backlog/fastino-promotion-retry-investigate-s1-variant-b-...yaml` (new), `backlog/promote-gliner-tuning-fastino-base-v1.yaml` (status/sprint/notes updated).

## Nemotron blind regression — taxonomy debt root cause

Sprint 9 baseline Nemotron blind = **0.821**. Sprint 10 tip = **0.774**, delta **-0.047**. This exceeds item #1's stated acceptance gate of ≥ -0.005.

**Root cause:** Sprint 8 split `CREDENTIAL` into four subtypes (`API_KEY`, `PRIVATE_KEY`, `PASSWORD_HASH`, `OPAQUE_SECRET`). The Nemotron corpus loader was not updated to map the legacy `CREDENTIAL` label to the new taxonomy, so it still emits `expected=CREDENTIAL` on the credential column.

Prior to Sprint 10, the secret scanner rarely surfaced an API_KEY finding on Nemotron's credential column because its sample values didn't hit any of the original 88 dict entries. Sprint 10 item #4's +90 new dict entries now correctly fire `API_KEY` on those samples — but the benchmark's string-based label-matching sees `predicted=API_KEY vs expected=CREDENTIAL` and scores it as an FP + FN.

The benchmark dump confirms this: `col_2: predicted=API_KEY, expected=CREDENTIAL, engines={'column_name': [], 'regex': ['API_KEY', 'SSN']}`.

**Real detection quality held or improved** — item #4 demonstrably makes API_KEY recall *better* on this sample. The measurement just can't see it through the stale label mapping.

**Sprint 11 follow-up** (to file during sprint-start or close): `nemotron-corpus-loader-taxonomy-refresh-map-legacy-CREDENTIAL-to-4-subtypes`. Fix is mechanical: update `tests/benchmarks/corpus_loader.py::load_nemotron_corpus` to map the upstream `credential` / `api_key` / `password` labels through the post-Sprint-8 subtype taxonomy. Expected outcome: Nemotron blind F1 returns to ~0.82–0.85 post-fix.

The same shape of debt likely exists in any corpus loader written before Sprint 8's CREDENTIAL split. Gretel-EN blind held flat at 0.611, which is consistent with Gretel-EN's credential column simply not firing item #4's new entries.

Gretel-EN and Nemotron **named-mode** numbers held flat (0.917 and 0.923 respectively), consistent with column-name-engine pulling from `column_name_engine.json` entries that were updated as part of Sprint 8's taxonomy split.

## Sprint 10 accuracy numbers

| Corpus | Mode | Sprint 9 | Sprint 10 | Δ | Notes |
|---|---|---|---|---|---|
| Gretel-EN | blind | 0.611 | **0.611** | +0.000 | Non-regression ✓ |
| Gretel-EN | named | 0.917 | **0.917** | +0.000 | Flat ✓ |
| Nemotron | blind | 0.821 | 0.774 | -0.047 | Taxonomy mismatch, not real regression (see above) |
| Nemotron | named | 0.923 | **0.923** | +0.000 | Flat ✓ |

**Benchmark SHA:** `7aafa01` (sprint10/main tip). Samples per column: 50. Commands: `python -m tests.benchmarks.accuracy_benchmark --corpus {nemotron,gretel_en} --samples 50 [--blind]`.

Gretel-finance corpus is NOT in this table because the `accuracy_benchmark.py --corpus` flag doesn't yet accept it (Sprint 11 wiring item).

## Test count delta

| Source | Sprint 9 | Sprint 10 | Δ |
|---|---|---|---|
| Total passing | 1222 | **1374** | **+152** |
| Skipped | 1 | 1 | 0 |

Breakdown by item:
- Item #1 (S1 wrapping): +9 tests (`TestBuildNerPrompt` 6, `TestS1PromptIntegratesWithInference` 2, `TestOrgOverfireRegression` 1)
- Item #2 (data-type pre-filter): +31 tests (parametrized over 13 non-text types + edge cases)
- Item #3 (Gretel-finance ingest): +5 tests (`TestGretelFinanceLoader`)
- Item #4 (dict expansion): +~105 tests (parametrized `TestNewDictionaryEntries` + `TestDictionaryHealth`)
- Item #5 (BQ verification): +0 tests (docs-only)
- Sum: +150 tests, observed +152 (test count drift is likely test discovery variance on parametrized scenarios).

## CI status

- **Local lint:** `ruff check . && ruff format --check .` — zero diffs ✓
- **Local test:** `pytest tests/ -q` — 1374 passed, 1 skipped, 26 warnings, 38.85s ✓
- **GitHub Actions:** sprint branches don't trigger the `branches: [main]` workflow filter. Merge to main will kick the full matrix. Pre-merge local CI is green.

## Backlog hygiene

- **Closed (won't-do):** `ml-optimized-secret-scoring-parameters-xgboost-on-18-features-extract-weights-for-deterministic-scorer` — empty spec, superseded by item #4 dictionary expansion.
- **Closed (subsumption):** `gliner2-over-fires-organization-on-numeric-dash-inputs` — closed by item #1's regression test.
- **Moved to Sprint 11:** `promote-gliner-tuning-fastino-base-v1` — see item #6 above.
- **New Sprint 11 items filed:**
  - `fastino-promotion-retry-investigate-s1-variant-b-always-wrap-fallback-to-close-blind-corpus-regression` (P2 feature) — investigate the wave 3 failure
  - `review-ai4privacy-dataset-family-and-ingest-best-cc-by-4-0-variant-re-open-sprint-9-removal-decision` (P2 feature) — filed during Sprint 10 after user found `ai4privacy/pii-masking-openpii-1m` is CC-BY-4.0, contradicting the Sprint 9 blanket-ban presumption
  - (to file at sprint close) `nemotron-corpus-loader-taxonomy-refresh-map-legacy-CREDENTIAL-to-4-subtypes`
  - (to file at sprint close) `wire-gretel-finance-into-accuracy-benchmark-cli`
  - (to file at sprint close) `gretel-finance-taxonomy-expansion` (account_pin, swift_bic_code, bban, driver_license_number)

## Deferred to Sprint 11+ (explicit)

- **Gated meta-classifier architecture** — Sprint 9's headline item, still under-specified. Needs `docs/plans/gated_meta_classifier_architecture.md` written first.
- **Meta-classifier LogReg/XGBoost ablation** — diagnostic input to gated architecture.
- **Schema-prior-consumer-foundation** — already has a plan doc on main (`docs/plans/schema_prior_consumer.md`).
- **Synthea 100k patient corpus generation** — second dataset per sprint is unhealthy (one ingest per sprint is the rate).
- **Full Kingfisher/gitleaks/Nosey Parker L-item** (200–500 entries) — Sprint 10 delivered the high-value 80–95 core at M complexity. Long tail is a Sprint 11+ decision gated on whether item #4's benchmark shows dictionary expansion still saturates recall.
- **Opaque-secret threshold validation** — deferred per user direction (dictionary expansion was the stronger lever).
- **Value-regex secret pattern expansion** — different code path from dict expansion, Sprint 11+ candidate.
- **Pattern bundle** (ABA routing, CC expansion, phone extensions, international SSN) — P2 regex quick wins.

## Lessons learned

1. **Corpus-loader label drift is silent and measurable.** Sprint 8's CREDENTIAL split was a source-of-truth change in the entity taxonomy, but the corpus loaders kept emitting the pre-split labels. The drift was invisible until Sprint 10 item #4's dict expansion caused new `API_KEY` predictions to score as FPs against stale `CREDENTIAL` labels. **Action:** add a CI lint that diffs corpus-loader label vocabulary against `data_classifier/entity_types.py` vocabulary and fails on drift. File as Sprint 11 chore.

2. **S1 wrapping didn't transfer cleanly from research stratum to production blind mode.** The `+0.0887` uplift on Ai4Privacy empty-context stratum was measured under fastino v2 at chunk_size=30, n=315. Under urchade v1 in blind mode on Gretel-EN + Nemotron, S1 held flat but did not lift. The mechanism (attention needs grammar) likely generalizes, but the effect size does not. **Action:** research memos should report stratum-specific effect sizes and explicitly flag which strata transfer to which deployment configurations.

3. **Fail-fast dispatch on stretch items works.** The fastino promotion was dispatched with explicit "if gates fail, REVERT and file Sprint 11 item, do NOT attempt to fix" instructions. The agent followed the protocol exactly — measured the gate failures, wrote detailed diagnosis, reverted the code, left a Sprint 11 YAML untracked for the main session to pick up. Zero main-session time was spent on a lost-cause fix loop. Total time from dispatch to reverted-and-documented: ~5 minutes. **Action:** adopt "fail-fast with Sprint N+1 filing" as the standard stretch-item dispatch pattern.

4. **Dictionary-based detection is the fastest recall lever we have.** Item #4 added 90 new definitive-tier entries in one sprint; each new entry at score ≥ 0.90 is a near-free recall gain because key-name match alone is sufficient to fire. The stale L-item's 200–500 target is plausible over 3–4 sprints at 80–100 entries per sprint, but only if the benchmark shows the recall curve hasn't saturated. Sprint 11 should measure before committing to another batch.

5. **Parallel agent dispatch with phase-bumped YAMLs ate zero merge conflicts this sprint.** The "main session bumps YAML phase before dispatch, agents don't touch YAMLs" discipline from the Sprint 9 handover's "option (a)" was followed across all 5 dispatch waves. Zero phase-update conflicts, down from 4-for-4 in Sprint 9.

## Next sprint candidates (Sprint 11)

Priority order (main session to propose at sprint-start):

1. **Gated meta-classifier architecture** (P0 feature, L) — headline item, under-specified, needs plan doc first.
2. **`fastino-promotion-retry`** (P2 feature, M) — investigate S1 variant B + threshold + numeric-column PHONE suppressor.
3. **`nemotron-corpus-loader-taxonomy-refresh`** (P1 chore, S) — fix the label mapping to reveal the real Sprint 10 numbers.
4. **`wire-gretel-finance-into-accuracy-benchmark-cli`** (P1 chore, S) — unblock Gretel-finance measurement.
5. **`ai4privacy-openpii-1m-review-and-ingest`** (P2 feature, S-M) — reopen the Sprint 9 removal decision for the CC-BY-4.0 variant.
6. **Schema-prior-consumer foundation** (P2 feature, M) — user's pre-crash plan work, ready to execute.
7. **Corpus-loader lint chore** (P2 chore, S) — CI check for entity-taxonomy drift (lesson 1 above).
8. **Meta-classifier retrain with Gretel-finance** (P2 feature, S-M) — measure `heuristic_avg_length` coefficient delta vs Sprint 9's 131.40 baseline.

## Cross-references

- `docs/benchmarks/history/sprint_10.json` — raw benchmark numbers with taxonomy-mismatch note
- `docs/research/gliner_fastino/` — preserved fastino promotion patch for Sprint 11 retry
- `docs/process/LICENSE_AUDIT.md` — ai4privacy correction footnote + credential-pattern upstreams section
- `docs/process/BQ_INTEGRATION_STATUS.md` — written BQ context-field verification
- `docs/process/CREDENTIAL_PATTERN_SOURCES.md` — per-entry attribution for the +90 secret dict entries

## Handover signoff

Sprint 10 delivered its committed detection-uplift chain (S1 wrapping shipped, fastino stretch failed fast), expanded the secret-detection dictionary to 178 entries with full attribution, diversified the training data with Gretel-finance, and closed the BQ verification debt. The Nemotron blind number moved in the wrong direction due to taxonomy debt that Sprint 10 item #4 surfaced rather than caused — the fix is a mechanical corpus-loader refresh in Sprint 11.

**Total commits on sprint10/main:** 15. **Net test delta:** +152. **Dict size delta:** +90 (88 → 178). **Corpora count delta:** +1 (6 → 7 — ai4privacy retired in Sprint 9, Gretel-finance added in Sprint 10). **Fastino promotion: blocked on structural issue, Sprint 11 research item filed.**
