# Sprint 11 Handover — data_classifier

> **Theme:** Measurement honesty + Sprint 10 cleanup + meta-classifier v3 / family taxonomy
> **Dates:** 2026-04-14 → 2026-04-15
> **Branches:** `sprint11/main` (8 cleanup items, 17 commits) + `sprint11/scanner-tuning-batch` (meta-classifier v3 batch, 14 commits, PR #12)
> **Test count:** 1374 → **1520** (+146 net-new)
> **Released as:** TBD — merge-pending (`v0.11.0` tag after `sprint11/main` lands on `main`)

---

## Sprint theme in one paragraph

Sprint 11 was a two-track sprint. The **main session** ran a "cleanup before the gated architecture" pass — closing Sprint 10's taxonomy-drift debt, wiring the Gretel-finance corpus into the accuracy CLI, tightening two secret-scanner match patterns, adding a corpus-loader drift lint, fixing a test env leak, and writing two pieces of durable documentation (the full Engines Reference and the fail-fast stretch-item dispatch protocol). A **parallel research session** ran a 10-phase meta-classifier uplift batch: feature schema v2 → v3, Chao-1 cardinality estimator, new structural validators (Bitcoin base58check/bech32, Ethereum), placeholder-credential validator with stopwords expansion, Tier-1 pattern-hit gate (observability-only), and — the headline — a new `family` taxonomy public API field on `ClassificationFinding` plus a canonical family-level accuracy benchmark adopted as the new quality gate. The two tracks met at `b05c896` / `3e35514` via a clean rebase with zero conflicts despite both touching `CLIENT_INTEGRATION_GUIDE.md`.

---

## Delivered — main session cleanup track (8 items)

### 1. `nemotron-corpus-loader-taxonomy-refresh` (P1 chore · M) — `bc22f2e`, `96b10fb`, `affea35`

**Goal.** Map legacy `CREDENTIAL` label to the 4 Sprint 8 subtypes (`API_KEY` / `PRIVATE_KEY` / `PASSWORD_HASH` / `OPAQUE_SECRET`) across Nemotron, Gretel-EN, and `_DETECT_SECRETS_TYPE_MAP`. Sprint 10 handover identified this drift as the root cause of the Nemotron blind -0.047 "regression."

**What shipped.** Updated `NEMOTRON_TYPE_MAP`, `GRETEL_EN_TYPE_MAP`, and `_DETECT_SECRETS_TYPE_MAP` in `tests/benchmarks/corpus_loader.py` to emit post-split subtypes. Updated existing `TestSecretBenchLoader` / `TestGitleaksLoader` / `TestDetectSecretsLoader` assertions to check the new subtypes. Added `TestLoaderTaxonomyRefresh` class with 6 drift guards — including `test_all_loader_maps_emit_only_valid_entity_types` which became the baseline for item #3's drift lint. Created `docs/plans/nemotron-corpus-loader-taxonomy-refresh.md` with the full mapping table.

**Scope expansion during execution.** The item was originally Nemotron-only but execution surfaced that all 3 loaders carried identical drift, so scope was expanded via Option A mid-sprint. The F1 recovery AC (#5) was explicitly relaxed when the mid-sprint diagnostic spike (see "Key decisions" below) proved the recovery required a corpus-side fix (item #8), not this item alone.

### 2. `wire-gretel-finance-corpus-into-accuracy-benchmark-cli` (P1 chore · S) — `7435add`

**Goal.** Wire the Sprint 10 Gretel-finance loader into `tests/benchmarks/accuracy_benchmark.py` so `--corpus gretel_finance` works from the CLI.

**What shipped.** Extracted a `_build_parser() -> argparse.ArgumentParser` helper from the inline `if __name__ == "__main__":` block and added `"gretel_finance"` to the `--corpus` choices tuple. New test file `tests/test_accuracy_benchmark_cli.py` with 3 tests: positive (flag accepted), negative (unknown corpus rejected), backwards-compatibility (all Sprint 10 choices preserved).

**Why no plan doc.** S-complexity, 10-line behavior change, fully covered by direct inline execution.

### 3. `corpus-loader-entity-taxonomy-drift-lint` (P2 chore · S) — `cee128a`

**Goal.** Build a CI check that walks every `*_TYPE_MAP` / `*_POST_ETL_IDENTITY` dict in the corpus-loader module and fails when any emitted value isn't a valid `entity_type` in `data_classifier/profiles/standard.yaml`. This is the structural fix for the failure mode that caused Sprint 10's drift.

**What shipped.** New module `tests/benchmarks/lint_corpus_taxonomy.py` with `DriftViolation` dataclass, `load_valid_entity_types()` yaml reader, `lint_loader_vocabulary(module)` walker, and a `__main__` CLI entry point (exits 0/1 for pre-commit / CI use). Explicit `_SKIP_MAPS_WITH_EXPIRY` dict that requires every skipped map to carry an expected-removal sprint (restructured during review remediation — see below). Raises `ValueError` if zero dicts are walked, guarding against silent-coverage regressions. New test file `tests/test_corpus_taxonomy_lint.py` with 7 tests: positive baseline on current loaders, 2 negative regression cases (stale CREDENTIAL + arbitrary typo), valid-subtype sanity check, filter-skip invariant, zero-maps guardrail, and an `__main__` entry-point exit-code test.

### 4. `tighten-id-token-and-token-secret-match-type` (P2 chore · S) — `e434bd1`

**Goal.** Flip `id_token` and `token_secret` in `secret_key_names.json` from `match_type: substring` to `match_type: word_boundary`. The pre-Sprint-11 substring rule caused over-fires on compound keys like `rapid_token`, `bigtoken_secret`, `atoken_secrets`.

**What shipped.** 2 edits in `data_classifier/patterns/secret_key_names.json` (JSON schema only — no behavior change beyond the match-type tightening). New `TestMatchTypeTightening` class in `tests/test_secret_scanner.py`: 2 JSON invariants (pin the field values), 5+5 positive cases (legitimate keys still match), 4+4 negative parametrized cases (compound keys like `rapid_token` no longer match), and one end-to-end `SecretScannerEngine` integration test (added during review remediation) that passes `rapid_token=<value>` KV pairs through the full engine and asserts no finding cites `id_token` / `token_secret`.

**Not measurable in benchmarks.** The current corpora don't exercise the compound-substring over-fire case — none of Nemotron/Gretel-EN/Gretel-finance contains columns like `rapid_token`. The regression tests exist to pin the invariant for real-world production columns (BQ customer data) that triggered the fix.

### 5. `hygiene-test-meta-classifier-training-py-env-leak` (P2 bug · S) — `46ec23a`

**Goal.** `tests/test_meta_classifier_training.py` was calling `os.environ.setdefault("DATA_CLASSIFIER_DISABLE_ML", "1")` at module import time and never reverting, leaking the env var into subsequent test modules in the same pytest session.

**What shipped.** Replaced the module-level `os.environ.setdefault` with a module-scoped autouse `pytest.MonkeyPatch` fixture that reverts on teardown via `yield`. Added `test_disable_ml_env_fixture_is_active` as a sanity check that the setup side still works.

### 6. `document-all-engines-in-client-facing-docs` (P2 docs · M) — `82fb445`

**Goal.** Give connector teams a canonical, per-engine reference they can use to predict and debug classification behavior without reading `data_classifier/engines/*.py`.

**What shipped.** New §5A "Engines Reference" section in `docs/CLIENT_INTEGRATION_GUIDE.md` (~329 lines). Per-engine subsections for `column_name`, `regex`, `heuristic_stats`, `secret_scanner`, `gliner2` covering purpose, fire conditions, input requirements, config signals, scoring formulas, output format, and confidence ranges. §5A.6 documents the orchestrator's 7-pass merge / dedup / suppression pipeline (authority-weighted merge, engine priority weighting, ML suppression when non-ML is strong, collision pair resolution, generic CREDENTIAL suppression, URL-embedded IP suppression, sibling-context adjustment). Every fact was audited against code paths at Sprint 11 tip; during review remediation, all hard-coded line-number citations were replaced with symbol-only references (20 replacements across §5A.1–§5A.6) for drift resistance. Appendix B trimmed to a quick-reference summary pointing at §5A.

### 7. `document-fail-fast-stretch-dispatch-protocol` (P2 docs · S) — `75ce6b2`

**Goal.** Codify Sprint 10 Lesson #3 (the fastino promotion revert) as a durable process doc so the REVERT-and-file-Sprint-N+1 pattern survives across sessions.

**What shipped.** New `docs/process/FAIL_FAST_STRETCH_DISPATCH.md` with: TL;DR, "when to use" (with a 5-question stretch-vs-core test), full dispatch prompt template (including the non-negotiable REVERT PROTOCOL block), Sprint N+1 retry YAML filing template, the "preserve the patch" rule, the worked Sprint 10 fastino example with exact failure magnitudes (-0.198 Gretel-EN / -0.295 Nemotron, the two broken integration tests, "~5 minutes" main-session cost), 6 anti-patterns, and a status-annotated "Integration with sprint workflow" section (reframed during review remediation to distinguish active rules from planned hooks). Linked from `docs/process/PROJECT_CONTEXT.md`.

### 8. `nemotron-credential-shape-partitioner` (P2 chore · S — rescoped from P1 bug mid-sprint) — `1fe3e61`

**Goal.** Partition Nemotron's raw `password` / `CREDENTIAL` bucket by value shape so JWT-shaped values route to `API_KEY` and PEM blocks route to `PRIVATE_KEY` before `NEMOTRON_TYPE_MAP` is applied. Completes the item #1 taxonomy refresh by fixing the ground-truth labeling artifact that was initially mis-diagnosed as a scanner over-fire.

**What shipped.** `_classify_credential_value_shape(value) -> str` helper in `tests/benchmarks/corpus_loader.py` with an explicit `_JWT_SHAPE_RE` regex and a tightened PEM check requiring `"PRIVATE KEY"` in the header window (the initial `"KEY"` substring match was flagged during review as too loose and fixed). Hooked into `load_nemotron_corpus` via a pre-mapping loop that unconditionally rewrites `entity_type` for credential-bucket records (unconditional rewrite landed during review remediation to remove implicit coupling with `NEMOTRON_TYPE_MAP["password"]`). 3 identity entries (`API_KEY` / `PRIVATE_KEY` / `OPAQUE_SECRET`) added to `NEMOTRON_TYPE_MAP` so rewritten records flow through the shared `_records_to_corpus` path unchanged. New `TestNemotronCredentialShapePartitioning` class with 7 regression tests covering JWT / PEM / plaintext / PIN / UUID / empty / public-key-PEM (negative case).

**Measured impact.** Nemotron blind corpus: 13 → **14 columns** (new API_KEY column); **81 JWT values** correctly relocated from OPAQUE_SECRET → API_KEY; zero JWT leaks remaining. This drove the Nemotron blind F1 recovery from 0.7742 → 0.8333 (above the Sprint 9 baseline).

### Review remediation pass (9 findings addressed) — `855f60c`, `b05c896`

A formal two-stage code review was dispatched via `feature-dev:code-reviewer` (6 code items) + `general-purpose` reviewer (2 docs items) after the 8 items were initially marked `phase=review`. The review surfaced 2 🔴 must-fix findings and 7 🟡 worth-considering findings; all 9 were addressed in a single remediation commit:

| Finding | Type | Fix |
|---|---|---|
| 🔴 PEM detection too loose (item #8) | Correctness | Match `"PRIVATE KEY"` explicitly; 3-case public-key PEM negative test |
| 🔴 Table-context boost stated as +0.02 in §5A.1 (actual 0.05) | Docs accuracy | Corrected and switched cite to symbol-only |
| 🟡 `print` in lint CLI (item #3) | Style | Added `# noqa: T201` + docstring rationale |
| 🟡 `_SKIP_MAPS` no machine-readable expiry (item #3) | Drift risk | Restructured as `_SKIP_MAPS_WITH_EXPIRY` dict with per-entry target-removal sprint |
| 🟡 Scanner integration test gap (item #4) | Test coverage | Added engine-level `rapid_token` KV integration test (also surfaced the generic `token` entry still fires at strong tier — out of scope for item #4) |
| 🟡 Partitioner asymmetry (item #8) | Maintainability | Unconditional `entity_type` rewrite for all credential-bucket records |
| 🟡 Pattern counts stale in §5A | Docs accuracy | 73 → 77 patterns, 32 → 35 entity types, 400+ → ~700 variants |
| 🟡 Hard-coded line numbers in §5A | Drift risk | 20 symbol-only replacements |
| 🟡 Aspirational `stretch: true` hooks in fail-fast doc | Docs honesty | Status callout separating active rules from planned hooks |

All 8 items carry `code_reviewed: true` + `design_reviewed: true` after remediation.

---

## Delivered — scanner-tuning-batch research track (PR #12, 14 commits)

The parallel `sprint11/scanner-tuning-batch` session ran a 10-phase meta-classifier uplift batch on the `research/meta-classifier` long-lived branch, rebased onto `sprint11/main` tip (`b05c896`) with zero conflicts. Full detail in PR #12. Summary of what the batch delivered:

### New public API — family taxonomy (non-breaking)

- `data_classifier.FAMILIES` — 13-family tuple (new export)
- `data_classifier.family_for(entity_type: str) -> str` — entity → family dispatch (new export)
- `data_classifier.ENTITY_TYPE_TO_FAMILY` — full mapping dict (new export)
- `ClassificationFinding.family: str` — auto-populated from `entity_type` in `__post_init__`, additive field (no existing client code breaks; `category` unchanged)

Connector teams see a new field on every finding but no existing behavior changes. Migration note in `CLIENT_INTEGRATION_GUIDE.md` v0.11.0+ entry.

### Meta-classifier v2 → v3 (shipped artifact)

- **Schema v2** — primary_entity_type one-hot encoding, fixes the shard-twin leak from primary_split
- **Schema v3** — adds `heuristic_dictionary_word_ratio` feature + Chao-1 bias-corrected cardinality estimator
- **v3 trained and shipped** — Phase 10 rebuild + retrain on Chao-1. Chao-1 is the #1 feature coefficient (4.72) — it replaces the saturated naive cardinality ratio.
- **Shadow path headline metric (10,170 shards):**
  - Family `cross_family_rate`: **5.85%** (down from 47.71% prior-shadow baseline — **8.2× reduction**)
  - Family `macro_f1`: **0.9286**
  - Subtype macro F1: **v3 +0.39 over v2**

### New validators

- `b3544e7` — Bitcoin base58check + bech32 + Ethereum structural validators (catches malformed coin-address strings that superficially match shape regex but fail cryptographic check-character validation)
- `fef2f12` — Placeholder-credential validator + stopwords expansion (rejects common placeholder credential values that look high-entropy but are dummy)
- `8818af8` — Stopwords XOR decode support (for test fixtures that trip GitHub push protection)

### New detection infrastructure

- `987144c` — **Chao-1 bias-corrected cardinality estimator** — drop-in replacement for `compute_cardinality_ratio` in `heuristic_engine.py`. Naive case is the `f₁=0` special case so zero existing tests regressed. Distinguishes "fully unique" from "high singleton tail" — the naive ratio was saturated at 1.0 for high-distinctness columns.
- `bb1644f` — **Tier-1 credential pattern-hit gate (11-F, observability-only)** — emits `GateRoutingEvent` telemetry but does not modify routing decisions. Same landing pattern as the Sprint 6 shadow meta-classifier: ship telemetry one sprint before policy. Sprint 12 stretch item proposes promoting it to a directive after the NEGATIVE / CONTACT family items land.

### New quality gate — canonical family accuracy benchmark

- `170ae98` — **Canonical family accuracy benchmark (11-I)** — the new Sprint 11+ quality gate. Measures detection at the family level (CONTACT, FINANCIAL, HEALTH, GOVERNMENT_ID, CREDENTIAL, NETWORK, DEVICE, GEO, DEMOGRAPHIC, VEHICLE, CRYPTOCURRENCY, OPAQUE, NEGATIVE — 13 families) instead of the subtype level, which is noisier and punishes correct within-family rerouting. Benchmark committed at `docs/research/meta_classifier/sprint11_family_benchmark.json` for `--compare-to` use in future runs.

### Memos shipped

- `docs/research/meta_classifier/sprint11_phase10_batch_result.md` — Phase 10 retrain CV / held-out / LOCO numbers, top features, per-class deltas
- `docs/research/meta_classifier/sprint11_family_ab_result.md` — family-level reframe, per-family P/R/F1 table, taxonomy decision rationale, Sprint 12 priorities
- `docs/research/meta_classifier/sprint11_family_benchmark.json` — committed baseline

### Sprint 12 backlog filed from PR #12

- `sprint12-validator-rejected-credential-feature.yaml` (P1) — target NEGATIVE family F1 0.595 → 0.75
- `sprint12-has-dictionary-name-match-feature.yaml` (P1) — target CONTACT family precision 0.882 → 0.95
- `sprint12-retire-date-of-birth-eu-subtype.yaml` (P2) — taxonomy cleanup
- `sprint12-shadow-directive-promotion-gate.yaml` (P2 stretch) — gated on items 1+2

---

## Sprint 11 benchmark — accuracy deltas vs Sprint 10

Run at `b05c896` via `python -m tests.benchmarks.consolidated_report --sprint 11 --samples 50` (Nemotron + Gretel-EN) plus `python -m tests.benchmarks.accuracy_benchmark --corpus gretel_finance --samples 50` (both modes, merged into `sprint_11.json`).

| Corpus | Mode | Sprint 9 | Sprint 10 | **Sprint 11** | Δ vs Sprint 10 |
|---|---|---|---|---|---|
| **Nemotron** | named | 0.923 | 0.923 | **1.000** | **+0.077** ✅ |
| **Nemotron** | blind | 0.821 | 0.774 | **0.833** | **+0.059** ✅ (above Sprint 9 baseline) |
| **Gretel-EN** | named | 0.917 | 0.917 | **0.917** | flat |
| **Gretel-EN** | blind | 0.611 | 0.611 | **0.611** | flat |
| **Gretel-finance** | named | — | — | **0.917** | NEW baseline |
| **Gretel-finance** | blind | — | — | **0.806** | NEW baseline |

**Headline:** both Nemotron numbers improved materially. Named went to **perfect 1.000** (item #1 + item #8 both contributed — column-name engine unlocked on credential columns and a new API_KEY column with 81 clean JWTs). Blind went to **0.833, above the Sprint 9 baseline of 0.821** — item #8's shape partitioner moved 81 JWT values to the correct column so the regex engine's `jwt_token` matches score as TPs instead of FPs.

**Gretel-EN flat** as expected — the loader ships post-ETL labels so there's no raw `password` bucket to repartition, and item #8 is Nemotron-only by design.

**Gretel-finance first formal measurement** — 0.917 named / 0.806 blind. Notably higher blind number than Gretel-EN (0.611) despite its CREDENTIAL column still emitting the legacy label, validating the Sprint 10 hypothesis that long-form financial-document prose gives the regex engine richer context windows.

**Family-level benchmark** (PR #12 new quality gate): `cross_family_rate` 5.85%, `family_macro_f1` 0.9286 on the 10,170-shard shadow evaluation.

Full per-corpus notes and count deltas in `docs/benchmarks/history/sprint_11.json`.

---

## Deferred / out of scope

Nothing deferred from the main-session cleanup track — all 8 items shipped. PR #12's batch also shipped in full; its 4 Sprint 12 follow-up items are the natural next priorities (not deferrals — they're next-sprint targets that came out of the family-level A/B analysis).

**Gretel-finance fixture refresh** remains explicitly out of scope per the Sprint 11 item #1 plan doc. The fixture still emits the legacy `CREDENTIAL` label because rebuilding it requires per-record `raw_label` / `source_context` metadata. Filed as a Sprint 12+ chore (`gretel-finance-fixture-refresh-drop-legacy-credential-label`).

---

## Architecture changes

1. **New public API — family taxonomy.** `ClassificationFinding.family` is a new additive field auto-populated from `entity_type`. Three new exports: `FAMILIES`, `family_for`, `ENTITY_TYPE_TO_FAMILY`. Non-breaking — existing consumers see the new field but no behavior change; `category` is unchanged. This is the architectural change that will drive Sprint 12+ detection work (cross-family confusion is the remaining pain).
2. **New quality gate — family accuracy benchmark.** The family-level benchmark at `docs/research/meta_classifier/sprint11_family_benchmark.json` becomes the new Sprint 11+ quality gate (replacing / supplementing the per-subtype benchmark). Cross-family rate < 0.06 and family macro F1 > 0.92 are the new targets.
3. **New engine infrastructure — Chao-1 cardinality estimator.** `compute_cardinality_ratio` in `heuristic_engine.py` is now Chao-1 bias-corrected. The naive special case is preserved so the public surface is unchanged, but columns with long singleton tails now produce more informative cardinality values.
4. **New engine infrastructure — Tier-1 credential pattern-hit gate (observability-only).** Emits `GateRoutingEvent` telemetry but does not modify routing. Will be promoted to a directive in Sprint 12+ after the prerequisite family-feature work lands.
5. **New structural validators.** Bitcoin base58check + bech32, Ethereum checksum, placeholder-credential. Each is an additive validator in the orchestrator's validation pass — shape-positive findings that fail the structural check are dropped.
6. **New linter — corpus-loader taxonomy drift.** `tests/benchmarks/lint_corpus_taxonomy.py` is a pre-commit / CI tool that prevents the Sprint 10 drift failure mode from silently reoccurring. Enforces that every corpus loader's `*_TYPE_MAP` / `*_POST_ETL_IDENTITY` dict emits values that exist in `standard.yaml`.
7. **New docs section — Engines Reference.** `docs/CLIENT_INTEGRATION_GUIDE.md` §5A is now the canonical per-engine reference for connector teams. Every fact cross-referenced against code paths, symbol-only citations for drift resistance.
8. **New process doc — fail-fast stretch dispatch.** `docs/process/FAIL_FAST_STRETCH_DISPATCH.md` codifies the Sprint 10 Lesson #3 revert-and-refile playbook as the standard stretch-item dispatch pattern.

---

## Key decisions

### Decision 1 — Item #1 AC #5 relaxation (Option A)

Item #1's acceptance criterion #5 originally required Nemotron blind F1 to recover to ≥0.82 (the Sprint 9 baseline). Mid-execution, the subagent ran the post-fix benchmark and found identical TP/FP/FN counts (11/5/2) pre- and post-taxonomy-refresh, contradicting the Sprint 10 handover's "fake taxonomy drift" diagnosis. A focused kill-and-diagnose move produced the finding that the F1 gap was a separate issue, not a taxonomy drift artifact. **Decision:** relax AC #5 (remove the F1 recovery requirement) and file a separate P1 bug to close the actual gap. The code fix (the taxonomy refresh itself) was still correct and unlocked Nemotron named → 1.000. The relaxation was the right call because the F1 recovery AC was based on a flawed hypothesis — chasing it would have been a lost cause.

### Decision 2 — P1 bug rescoped after diagnostic spike (not a scanner bug)

The P1 bug filed during Decision 1 (`secret-scanner-over-fires-api-key-and-email-on-plaintext-password-pin-uuid-values-nemotron-col-7-surface`) was investigated via a 30-minute diagnostic spike that ran the secret_scanner and regex engines directly against Nemotron col_7. The spike produced three findings:

1. **The secret_scanner produces ZERO findings on col_7.** The parsers find no `key=value` shape in plaintext secrets — the scanner doesn't even touch the column.
2. **The regex engine correctly fires `API_KEY` on 3 JWT values** (100% precision in the initial spike; full run found 81 JWTs). JWTs ARE API keys by taxonomy.
3. **No `EMAIL` finding is reproducible** — the "over-fires API_KEY and EMAIL" framing in the original bug title was a mis-attribution.

**Decision:** rescope the P1 bug in place as a P2 chore (`Nemotron loader — partition credential values by shape`) and ship the real fix — a 20-line value-shape partitioner in `corpus_loader.py`. The originally-anticipated scanner fix was a non-starter because there was no scanner bug to fix. This decision is the direct cause of the Nemotron blind F1 win.

### Decision 3 — Tier 3 docs proceed in current session (Option A)

After Tier 2 review, offered the user (A) proceed to Tier 3 docs in-session, (B) pause for fresh session, (C) defer docs to Sprint 12. User chose (A). Rationale: the 2 docs items (engines reference + fail-fast dispatch) were both draft-once with clear scope and didn't materially benefit from fresh context.

### Decision 4 — Tiered review (Option C)

Offered (A) one batched review, (B) 8 parallel reviews, (C) tiered — one code reviewer + one docs reviewer in parallel. User chose (C). Rationale: code and docs benefit from different review lenses (bugs / edge cases vs. cross-reference accuracy / drift risk). The two-agent dispatch found 2 must-fix + 7 yellow findings; remediation landed in `855f60c`.

### Decision 5 — Fix yellow findings beyond must-fixes (Option B)

Offered (A) fix must-fixes only, (B) fix must-fixes + all yellow findings, (C) fix must-fixes + tag rest for Sprint 12. User chose (B). All 9 findings addressed in a single remediation commit. During remediation, the new scanner integration test surfaced that the generic `token` dict entry still fires on `rapid_token` at the strong tier — correctly out-of-scope for item #4 and pinned by the narrowed assertion.

### Decision 6 — Scanner-tuning batch waits for its own PR merge (Option B)

At Phase 2 of sprint-end, the parallel `meta-classifier-feature-schema-v2-scanner-tuning-batch` item was the only remaining `doing` item (phase=build). User chose (B): wait for the parallel session's PR #12 to land on `sprint11/main` before closing Sprint 11. This is the reason Sprint 11 closes with both tracks in one release.

---

## Known issues & carryovers

1. **Gretel-EN blind remains the weakest real-corpus F1 (0.611).** The loader ships post-ETL labels so item #8's shape partitioner doesn't apply. Gretel-EN's blind mode is the hardest benchmark: column-name signal stripped, values credential-shaped, no domain context. Filed as a Sprint 12+ candidate.
2. **Gretel-finance CREDENTIAL column still emits legacy flat label.** Explicitly skipped by item #1's scope (fixture refresh requires rebuilding per-record metadata). Filed as a Sprint 12 chore (`gretel-finance-fixture-refresh-drop-legacy-credential-label`).
3. **Generic `token` dict entry still fires on compound keys** (e.g., `rapid_token`). Surfaced by the item #4 review remediation integration test. Item #4 deliberately scoped to `id_token` / `token_secret` only — broader tightening would need its own analysis of which dict entries benefit from `word_boundary`. Not filed yet; decide Sprint 12 whether to batch a generic tightening pass.
4. **Tier-1 credential pattern-hit gate is observability-only.** Emits `GateRoutingEvent` telemetry but does not modify routing. Promotion to a directive is the Sprint 12 stretch item (`sprint12-shadow-directive-promotion-gate.yaml`), gated on the NEGATIVE and CONTACT family-feature items.
5. **Fail-fast dispatch sprint-YAML integration hooks are planned but not wired.** The `stretch: true` marker and "Attempted, reverted" handover section referenced in `FAIL_FAST_STRETCH_DISPATCH.md` are not yet in `SPRINT_START_CHECKLIST.md` / `SPRINT_END_CHECKLIST.md`. The doc's status callout makes this explicit. Follow-up chore not yet filed.
6. **v0.11.0 release not yet tagged.** `v0.8.0` is the latest published wheel in AR. Sprint 9 + Sprint 10 + Sprint 11 are all unreleased. The decision on when to tag and whether to bundle with the BQ consumer bump is deferred to post-sprint-end — user-owned.

---

## Lessons learned

### Lesson 1 — Diagnostic spikes beat premature execution

The "P1 scanner bug" was the clearest case of this in the sprint. The Sprint 10 handover's "fake taxonomy drift" diagnosis was directionally correct but incomplete, and the mid-sprint assumption that item #1 alone would close the F1 gap was wrong. A 30-minute diagnostic spike (Decision 2 above) saved the sprint from chasing a non-existent scanner bug and pointed at the actual fix (a 20-line loader patch) which recovered the F1 gap and then some.

**Action:** When a Sprint N+1 item is filed from a Sprint N handover's root-cause diagnosis, run a diagnostic spike to VERIFY the diagnosis before scoping the item. Sprint 10 handover said "scanner over-fires"; reality was "corpus bucketing artifact"; the two call for completely different fixes.

### Lesson 2 — Corpus-side fixes can unlock bigger wins than engine-side fixes

Item #8 was a 20-line loader patch. It contributed the entire Nemotron blind F1 recovery (+0.059) plus the Nemotron named F1 win (+0.077, in combination with item #1). No engine code changed. This is a reminder that the detection quality pipeline has three layers — corpus → engines → orchestrator — and corpus-side fixes are often cheaper and higher-leverage than engine tuning when the benchmark regression traces to ground-truth labeling.

**Action:** When the benchmark moves in the wrong direction, the diagnostic protocol should be: (1) dump the values behind the FPs / FNs, (2) check whether the ground truth is correct before touching engine code, (3) only then tune engines.

### Lesson 3 — Two-track sprints need upfront deconfliction

Sprint 11 ran a main-session cleanup track and a parallel research track simultaneously. Zero merge conflicts at the end despite both tracks editing `CLIENT_INTEGRATION_GUIDE.md` — because both sides knew about the file-ownership contract from the `parallel research workflow` memory. The deconfliction message exchanged at sprint start (see the session log) was the critical moment.

**Action:** Continue using the file-ownership contract. When sprints run multi-track, exchange an explicit deconfliction message at sprint start naming which files each track will touch.

### Lesson 4 — Review remediation is a real sprint phase

The sprint-execute flow moved items to `phase=review` but the actual code review didn't happen until the user asked "all code reviewed?". This gap shipped a 🔴 must-fix (the PEM detection bug) in `phase=review` for ~2 hours before it was caught. The review fixed it before merge, so no harm done, but the process-level lesson is that `phase=review` should be a gate with an explicit review step, not just a status label.

**Action:** `/sprint-execute` should either (a) dispatch the per-item code review agent as part of moving items to `phase=review`, or (b) `/sprint-end` should refuse to close a sprint with `code_reviewed: false` items. Filed as a follow-up to the sprint-execute skill, not yet in backlog.

### Lesson 5 — The family taxonomy reframe was the right architecture bet

The 10-phase meta-classifier batch's headline finding was that **subtype-level F1 was measuring the wrong thing**. Cross-family rate (5.85% post-batch, from 47.71% baseline) is the metric that actually matters for connector consumers — they care whether a column is classified as `CREDENTIAL` vs `CONTACT`, not whether it's `API_KEY` vs `PRIVATE_KEY` within the credential family. The new canonical family accuracy benchmark is the Sprint 11+ quality gate.

**Action:** Use family-level F1 + cross-family rate as the primary ship gates going forward. Subtype F1 becomes secondary — informative for within-family disambiguation but not a blocker.

---

## Test coverage

| Category | Pre-Sprint-11 | Post-Sprint-11 | Delta |
|---|---|---|---|
| Total passing | 1374 | **1520** | +146 |
| Skipped | 1 | 1 | 0 |
| Main-session adds (items #1–#8 + review) | — | **+38** | (new loader tests, drift lint, scanner tightening, engine integration, partitioner, public-key PEM negative, scanner KV integration) |
| Scanner-tuning-batch adds (PR #12) | — | **+100** | (meta-classifier v2/v3, Chao-1, new validators, family benchmark, gate observability) |
| Lint | 100% clean | 100% clean | — |
| Format | 100% clean | 100% clean | — |
| Total runtime | ~55s | ~67s | +12s |

---

## Commits

### Main-session track (`sprint11/main`, 17 commits at `b05c896`)

1. `bc22f2e` — test(sprint11): add loader taxonomy refresh tests (failing baseline)
2. `96b10fb` — fix(sprint11): refresh corpus loader taxonomy maps to post-Sprint-8 4-subtype
3. `affea35` — chore(sprint11): item #1 benchmark results and plan doc
4. `694e97e` — merge: pull item #1 backlog updates (AC adjustment + scanner bug) from main
5. `7435add` — feat(sprint11): wire gretel_finance corpus into accuracy_benchmark CLI
6. `6564db3` — merge: pull phase=review backlog updates for items #1 and #2
7. `cee128a` — feat(sprint11): corpus-loader entity-taxonomy drift lint
8. `e434bd1` — fix(sprint11): tighten id_token and token_secret match_type to word_boundary
9. `46ec23a` — fix(sprint11): restore DATA_CLASSIFIER_DISABLE_ML env after meta_classifier_training tests
10. `40afd96` — merge: pull Tier 2 phase=review backlog updates
11. `75ce6b2` — docs(sprint11): add fail-fast stretch-item dispatch protocol doc
12. `82fb445` — docs(sprint11): add comprehensive Engines Reference to client integration guide
13. `25da435` — chore(sprint11): move items #6 and #7 to phase=review
14. `1fe3e61` — chore(sprint11): partition Nemotron credential values by shape (JWTs→API_KEY)
15. `560241d` — chore(sprint11): move rescoped credential-shape partitioner to phase=review
16. `855f60c` — chore(sprint11): address Sprint 11 code review findings
17. `b05c896` — chore(sprint11): mark 8 reviewed items code_reviewed + design_reviewed

### Scanner-tuning-batch track (`sprint11/scanner-tuning-batch`, 14 commits on top of `b05c896`, PR #12)

1. `c8a145c` — feat(sprint11): meta-classifier feature schema v2 — primary_entity_type one-hot
2. `ff70775` — feat(sprint11): train and ship meta-classifier v2 artifact
3. `d04e3d6` — fix(sprint11): remove shard-twin leak from meta-classifier primary_split
4. `b3544e7` — feat(sprint11): bitcoin base58check + bech32 and ethereum structural validators
5. `fef2f12` — feat(sprint11): placeholder-credential validator + stopwords expansion
6. `8818af8` — chore(sprint11): file follow-up — stopwords XOR decode support
7. `d3d29d8` — feat(sprint11): heuristic dictionary-word-ratio feature (schema v3)
8. `987144c` — feat(sprint11): Chao-1 bias-corrected cardinality estimator (11-E)
9. `bb1644f` — feat(sprint11): tier-1 credential pattern-hit gate (11-F)
10. `1547fd8` — feat(sprint11): Phase 10 — rebuild + retrain v3 on Chao-1 + batch memo
11. `bc741d9` — feat(sprint11): family taxonomy on ClassificationFinding (11-H)
12. `170ae98` — feat(sprint11): canonical family accuracy benchmark (11-I)
13. `7444354` — chore(sprint11): Sprint 12 backlog items from family benchmark analysis
14. `3e35514` — chore(sprint11): flip scanner-tuning batch to phase=review

---

## Recommendations for Sprint 12

Priority-ordered, with the 4 PR #12 follow-ups first since they come out of measured family-benchmark analysis and the cleanup items second:

1. **`sprint12-validator-rejected-credential-feature`** (P1) — target NEGATIVE family F1 0.595 → 0.75. Feature engineering on the meta-classifier to exploit the new validators' rejection signal.
2. **`sprint12-has-dictionary-name-match-feature`** (P1) — target CONTACT family precision 0.882 → 0.95. Column-name dictionary match as a meta-classifier feature.
3. **`sprint12-retire-date-of-birth-eu-subtype`** (P2) — taxonomy cleanup surfaced by the family A/B analysis.
4. **`sprint12-shadow-directive-promotion-gate`** (P2 stretch, gated on items 1+2) — promote the Tier-1 credential pattern-hit gate from observability to a directive once the prerequisite family-feature work lands. This is the natural graduation of the 11-F observability shipment.
5. **`gretel-finance-fixture-refresh`** (P2 chore) — rebuild the Gretel-finance fixture to drop the legacy CREDENTIAL label so item #1's taxonomy refresh becomes complete and `_SKIP_MAPS_WITH_EXPIRY` can be emptied.
6. **Gretel-EN blind detection lift** (P2 feature) — targeted work on the weakest real-corpus measurement (0.611 blind, flat across Sprint 9–11). Investigate whether the Gretel-EN shape partitioner analog is feasible despite the post-ETL loader format.
7. **Generic `token` dict entry tightening** (P2 chore, surfaced by review remediation) — evaluate which other dict entries benefit from `word_boundary` match_type on compound keys. Rapid_token / bigtoken_secret test fixtures pin the target cases.
8. **`v0.11.0` release tagging + BQ consumer bump** (P1 release ops) — tag v0.11.0, publish the wheel to AR, coordinate the BQ consumer bump (Sprint 9 + 10 + 11 all unreleased).
9. **Sprint-execute review gate** (P2 process) — make the `phase=review` transition actually require a dispatched code-reviewer agent, or block `/sprint-end` on `code_reviewed: false` items. Driven by Sprint 11 Lesson 4.

---

## Handover signoff

Sprint 11 delivered its headline goal (measurement honesty + Sprint 10 cleanup) plus an unplanned architectural addition from the parallel research track (family taxonomy as a public API field + canonical family benchmark as the new quality gate). Both Nemotron benchmark numbers recovered and now sit above the Sprint 9 baseline; the Nemotron blind F1 win came from a corpus-side fix that the Sprint 10 handover's diagnosis had pointed at incorrectly. The two-track execution finished with zero merge conflicts, full code review on both tracks, and 2 must-fix + 7 yellow review findings remediated pre-merge.

**Total test delta:** 1374 → **1520** (+146). **Main-session commits:** 17. **Scanner-tuning-batch commits:** 14 (PR #12). **Benchmark wins:** Nemotron named +0.077 → 1.000, Nemotron blind +0.059 → 0.833. **Release status:** pending v0.11.0 tag after PR #12 lands and `sprint11/main` → `main` merge.
