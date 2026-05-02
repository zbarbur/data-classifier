# Sprint 17 Handover — Browser Scanner v2 + Measurement Honesty

**Dates:** 2026-04-28 → 2026-05-02
**Version:** v0.17.0 (in `pyproject.toml`; **git tag v0.17.0 held — see B3 plan**)
**Tests:** 2,593 passed, 2 failed (pre-existing — filed S18 P0), 1 skipped, 1 xfailed
**Branch:** `sprint17/main` → main (PR pending)

## Theme

Two parallel tracks merged in Sprint 17:

1. **Browser scanner v2** — promote `research/prompt-analysis` (~140
   commits) into main: unified Rust/WASM detector replaces the Sprint 14
   JS-regex scanner. Cross-runtime parity is byte-identical between
   PyO3 native and WASM (`scripts/cross_runtime_parity.sh`).
2. **Measurement honesty** — replace `shadow.cross_family_rate` (which
   mostly tracks router-suppression policy) with
   `system.overall.joint_miss_rate` (true system-level miss rate) as
   the canonical sprint gate. Decomposes router suppression and shows
   the headline 36.9% was 5× larger than the honest 6.56%.

## Benchmark (canonical, ML disabled)

| Metric | S16 | S17 | Delta |
|---|---|---|---|
| LIVE `family_macro_f1` | 0.9732 | 0.9542 | -0.0190 |
| LIVE `cross_family_rate` | 0.0808 | 0.1029 | +0.0221 |
| SHADOW `family_macro_f1` | 0.8305 | 0.6932 | -0.1373 |
| SHADOW `cross_family_rate` | 0.3139 | 0.3695 | +0.0556 |
| **SYSTEM `joint_miss_rate`** | n/a (new) | **0.0656** | new gate metric |
| `router_suppression_rate` | n/a | 0.3302 | (3,903 / 11,820) |

**Why the headline shadow regression is not a real regression:** the
Sprint 16 baseline was measured on a 4,620-shard subset (corpus
fixtures missing). The Sprint 17 baseline is on the full 11,820 shards.
Re-measuring Sprint 16's code on the same full corpus yields identical
metrics within ±0.0002 (verified during the diagnostic spike). The
delta shown above is a **measurement honesty correction**, not a code
regression. See `docs/research/meta_classifier/sprint17_router_suppression_decomposition.md`.

### Sprint gate metric

`system.overall.joint_miss_rate` is the new canonical gate. Decomposition
on the Sprint 17 corpus:

```
joint_miss_rate    = 6.56%  (736 / 11,220 non-NEGATIVE shards)
live_only_miss     = 426    (LIVE wrong, SHADOW caught — value of meta-classifier)
shadow_only_miss   = 3,206  (SHADOW wrong/suppressed, LIVE caught — value of cascade)
both_correct       = 6,852

By family:  CONTACT=497, FINANCIAL=79, GOV_ID=75, CREDENTIAL=46, URL=36, DATE=3
By shape:   opaque_tokens=368, free_text_heterogeneous=186, structured_single=182
```

The biggest concrete recall hole is **CONTACT in free-text-heterogeneous
shapes** (333 of the 893 raw joint misses, before NEGATIVE exclusion),
filed as a Sprint 18 P1 item.

Saved to `docs/research/meta_classifier/sprint17_family_benchmark.json`.

## Items Completed (4/4 + close-out)

### 1. Merge research/prompt-analysis unified WASM detector (P1, L, feature)

PR #22: ~140 commits promoted from `research/prompt-analysis`. Adds
the Rust crate `data_classifier_core` with format/structural/syntax/data/
prose detectors, PyO3 + WASM bindings. `scan_text.py` prefers the Rust
`UnifiedDetector` when available; falls back to pure-Python `TextScanner`.

**Files:** `data_classifier_core/`, `data_classifier/clients/browser/`,
`data_classifier/scan_text.py`, `scripts/cross_runtime_parity.sh`,
`scripts/scan_wildchat_unified.py`.

**Cross-runtime parity verified:** 14 Rust + 8 WASM fixtures pass.

### 2. Source diverse NEGATIVE corpus (P1, M, feature)

5 structurally-distinct NEGATIVE sources × 500 values = 2,500 samples:
config (PORT=8080), code (function defs), business (Faker catch_phrase),
numeric (measurements), prose (synthetic documentation).

**Files:** `tests/benchmarks/negative_corpus.py`,
`docs/research/negative_corpus_sources.md`,
`tests/test_negative_corpus.py`.

**Surfaced bug:** the `[business]` and `[prose]` contamination tests
fail at 12.0% / 11.3% (ceiling 5%) because GLiNER's ORGANIZATION label
fires on Faker `catch_phrase()` outputs. The corpus is doing its job —
the test is supposed to expose this kind of FP. Filed as Sprint 18 P0.

### 3. Clean Nemotron synthetic CC corpus (P2, S, bug)

Luhn filter at corpus-load time drops invalid synthetic credit-card
values (52 shards expected per S14 finding).

**Files:** `tests/benchmarks/corpus_loader.py`.

### 4. Promote multi-label architecture memo to docs/spec (P2, S, docs)

`docs/research/multi_label_philosophy.md` (research/meta-classifier) →
`docs/spec/11-multi-label-architecture.md` (main). Closes the
self-described promotion plan from the memo's own header (originally
targeted Sprint 12 close-out, never executed).

**Files:** `docs/spec/11-multi-label-architecture.md` (new, 18,861 bytes),
`docs/experiments/prompt_analysis/queue.md` (cross-ref updated).

### 5. (Close-out) `joint_miss_rate` metric + audit (in this commit)

System-level joint miss metric replaces `shadow.cross_family_rate` as
the canonical sprint gate per Sprint 17 router-suppression
decomposition memo. Includes 4 unit tests, regenerated baseline,
CLAUDE.md update, and a benchmark-process audit (4 P0/P1 gaps filed
for Sprint 18).

**Files:** `tests/benchmarks/family_accuracy_benchmark.py`,
`tests/test_family_benchmark_metrics.py`, `CLAUDE.md`,
`docs/research/meta_classifier/sprint17_family_benchmark.json`.

## Key Decisions

- **B3 plan: merge integration without v0.17.0 git tag.** PR #22 lands
  on `sprint17/main`; pyproject version bumps to 0.17.0; CHANGELOG entry
  written; **but the v0.17.0 git tag is held until** (a) 7 EU validators
  ported to Rust, (b) Cloud Build dry-run passes. Both deferred to
  Sprint 18.
- **`joint_miss_rate` over `cross_family_rate` as sprint gate.**
  `cross_family_rate` correlates with router-suppression policy (which
  is determined by corpus shape composition); adding harder corpora
  mechanically increases it without code change. `joint_miss_rate` is
  invariant to corpus shape composition.
- **NEGATIVE excluded from `joint_miss_rate` denominator.** Per memo
  §5: for NEGATIVE ground truth, "predict nothing" is the correct
  answer; symmetric metric counts it as wrong. Excluding NEGATIVE gives
  6.56% vs 7.6% headline (Sprint 17 audit).

## Architecture Changes

- **`scan_text.py` two-implementation dispatch** — Rust
  `UnifiedDetector` (PyO3) when available, pure-Python `TextScanner`
  fallback. Public API unchanged.
- **Browser bundle** — WASM + unified patterns instead of S14 JS-regex
  scanner. `data_classifier/clients/browser/dist/` is built artifact
  (gitignored).
- **`summary["system"]` in family benchmark JSON** — new top-level key
  alongside `live` and `shadow`. Contains joint-miss decomposition by
  family and shape.

## Audit findings — benchmark process gaps

A holistic audit identified 4 gaps blocking sprint-close confidence
(filed as Sprint 18 backlog items):

| ID | Severity | Issue |
|---|---|---|
| `ci-silences-dvc-pull-failures-...` | P0 | `.github/workflows/ci.yaml:41,213` uses `\|\| echo` for `dvc pull` — same pattern that caused the S17 4620-vs-11820 measurement artifact |
| `organization-fp-from-gliner-fires-on-faker-business-names-...` | P0 | 2 pre-existing test failures: GLiNER's ORGANIZATION label fires on Faker business names (12.0% / 11.3% contamination vs 5% ceiling) |
| `ml-enabled-benchmark-variant-add-joint-miss-rate-ml-active-...` | P0 | Canonical gate is ML-disabled; production uses ML; GLiNER/ONNX/onnxruntime regressions are silent |
| `promote-summarise-shards-minimum-count-check-...` | P1 | 9 silent `return []` sites in `corpus_loader.py` — lift assertion to `build_shards()` aggregator |

## Known Issues

- **2 pre-existing test failures** (filed S18 P0): GLiNER ORGANIZATION
  FPs on Faker business and prose generators.
- **v0.17.0 git tag deferred** (B3 plan): EU validators not ported to
  Rust + Cloud Build dry-run not yet run.
- **Cross-runtime parity gap (case 2975)** (filed S18 P1): Rust
  `regex_pass.rs` Category 18 over-suppresses
  `mysql+pymysql://...{database}` connection-string regex matches.
  Python finds at conf 0.9; Rust drops.

## Lessons Learned

- **Silent-empty-list is a recurring class.** Sprint 17's measurement
  artifact (4620 vs 11820 shards) was caused by the same pattern that
  appears 9 times in `corpus_loader.py`, plus once in CI's `dvc pull`,
  plus a sibling already filed in Sprint 16. The fix is one
  fail-loud assertion at the aggregator level, not 10 individual
  rewrites.
- **Confidence-aware FP gating > scheme-blind FP gating.** Rust's
  `value_is_obviously_not_secret` runs on every regex match including
  high-confidence scheme-anchored patterns like `connection_string`.
  Python's two-stage pipeline (regex_engine + secret_scanner) protects
  high-conf matches from FP filters; Rust merged both stages and lost
  this separation. The Sprint 18 P1 fix is to skip Category 18 when
  confidence ≥ 0.85.
- **The diverse NEGATIVE corpus surfaced ORGANIZATION FPs that the
  synthetic shard benchmark couldn't see.** This validates the
  Sprint 17 decision to invest in real corpora coverage. Sprint 18's
  ML-enabled gate variant will close the remaining blind spot.
- **Sprint gate metric must be invariant to corpus composition.**
  `cross_family_rate` was 5× larger than the honest joint miss rate
  because it conflated router policy with system quality. Adding harder
  shapes mechanically inflates it; pruning easy shapes mechanically
  deflates it. `joint_miss_rate` is composition-invariant.

## Recommendations for Sprint 18

Theme: **benchmark hardening + parity completion.** Sprint 18 closes
the measurement blind spots, ports the EU validators to Rust, and
unblocks the v0.17.0 git tag.

Filed backlog items:

1. `organization-fp-from-gliner-fires-on-faker-business-names-...` (P0)
2. `ci-silences-dvc-pull-failures-change-echo-to-exit-1-in-ci-yaml` (P0)
3. `ml-enabled-benchmark-variant-add-joint-miss-rate-ml-active-...` (P0)
4. `port-7-eu-validators-to-rust-sprint-16-parity-blocks-v0-17-0-tag` (P0, pre-existing)
5. `rust-regex-pass-over-suppresses-connection-string-via-category-18-brace-check` (P1)
6. `lift-contact-recall-in-free-text-heterogeneous-shape-333-shard-joint-miss` (P1, pre-existing)
7. `add-joint-miss-rate-metric-to-family-benchmark-use-as-sprint-gate` (P1, **closed by Sprint 17 close-out**)
8. `fail-loud-benchmark-fixture-loader-replace-silent-empty-list-fallback` (P1, pre-existing)
9. `promote-summarise-shards-minimum-count-check-to-hard-assertion-in-build-shards` (P1)

Suggested sprint scope: 5–6 items. P0s + P1 #5 (Rust regex_pass bug) +
either #6 (CONTACT recall) or #9 (shard-count assertion). Skip the
Cloud Build dry-run until the EU validators are ported.
