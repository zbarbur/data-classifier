# Sprint 15 Session Handoff — Phase 1 Complete

> **Last session:** 2026-04-21 → 2026-04-23
> **Branch:** `sprint15/main` (pushed)
> **Next task:** Phase 2, Task 6 — Confidence model rethink

---

## What to do next

Resume subagent-driven development from the implementation plan at:
`docs/superpowers/plans/2026-04-21-sprint15-dataset-foundation-scoring-honesty.md`

Start at **Task 6** (confidence model rethink). Tasks 6, 7, 8 are Phase 2 (scoring fixes), all unblocked.

### Remaining tasks

| # | Task | Size | Status |
|---|---|---|---|
| 6 | Confidence model rethink — validated matches floor at 0.95, drop count multiplier | M | Ready |
| 7 | Char-class evenness metric + diversity boost (Python + JS parity) | S | Ready |
| 8 | NEGATIVE corpus cleanup — extend relabeling with scan_text opaqueTokenPass | M | Ready |
| 9 | Build WildChat eval dataset — scan 3,515 prompts, JSONL with XOR | S | Ready |
| 10 | Text-path benchmark — `tests/benchmarks/text_path_benchmark.py` | S | Blocked by 9 |
| 11 | Sprint quality gate — lint, tests, parity, benchmarks | — | Blocked by all |

---

## What was completed (Phase 1)

### Task 1: DVC Migration
- ~45MB of data files moved from git to DVC+GCS
- Corpus fixtures, benchmark predictions, research artifacts all DVC-tracked
- CI workflow updated with `dvc pull` step (soft-fail — GCS auth needs separate config)
- Commit: `6890d57`

### Task 2: Gretel Uncapped
- `max_per_type` default changed from 1000 → None (unlimited)
- Gretel-EN: 315 → 131,596 records
- Gretel-finance: 360 → 73,702 records
- Also removed obsolete fixture size assertions in test_corpus_loader.py
- Commit: `06499f6`

### Task 3: openpii-1m Ingest
- New `download_openpii_1m()` in `scripts/download_corpora.py` using streaming mode
- 40,000 records, 8 entity types × 5,000 each
- **Type map corrected** — 5 labels from Sprint 14 spec were wrong:
  - PHONENUMBER → TELEPHONENUM (actual label)
  - USERNAME, ACCOUNTNUM, STATE, COUNTY — don't exist in dataset (removed)
- BANK_ACCOUNT dropped (no equivalent source label)
- Both `corpus_loader.py` and `download_corpora.py` type maps updated
- DVC-tracked, pushed to GCS
- Commit: `495fd37`

### Task 4: Shard Builder Wiring
- `_openpii_1m_pool()` added to `shard_builder.py`
- Wired into `build_real_corpus_shards()`
- NATIONAL_ID now has real-corpus coverage (first time ever)
- Commit: `d0d13bd`

### Task 5: scan_text FP Parity + opaqueTokenPass (P0)
- **P0 filed mid-sprint** from research/prompt-analysis branch (21% precision on free text)
- Root cause: `scan_text._regex_pass()` had ZERO FP filters — the Python functions existed in `secret_scanner.py` but weren't called
- Added `_value_is_obviously_not_secret` + `_is_placeholder_value` calls to `_regex_pass()`
- Added 2 missing filters to Python `_value_is_obviously_not_secret()`: CJK/Cyrillic/Arabic check + `_CODE_CALL` regex
- Added JWT-safe guard on `_CODE_DOT_NOTATION` (segment >32 chars skips check)
- Added `_opaque_token_pass()` as third detection pass (matches JS scanner-core.js)
- 10 new tests (TestFPFilters + TestOpaqueTokenPass), test assertions strengthened after spec review
- Commits: `1b34e60`, `cacead6`, `42aa5eb`

---

## Key design decisions (approved, ready to implement)

### Confidence model (Task 6)
- `confidence` = match quality, `match_ratio` = prevalence (no schema change)
- Validated matches: `confidence = max(base, 0.95)` — floor, not +0.05
- No count multiplier — drop 0.65/0.85/1.0 scaling entirely
- Unvalidated matches: `confidence = base` from pattern definition
- File: `data_classifier/engines/regex_engine.py`, function `_compute_sample_confidence`
- Ripple: meta-classifier retrain needed, CLIENT_INTEGRATION_GUIDE.md update

### Char-class evenness (Task 7)
- New `compute_char_class_evenness()` — normalized Shannon entropy over 4-class histogram
- Boost formula: `evenness * 0.15` (calibrate later against WildChat)
- Used in secret scanner strong/contextual tiers
- JS parity in `entropy.js` + `scanner-core.js`
- File: `data_classifier/engines/heuristic_engine.py`, `data_classifier/engines/secret_scanner.py`

### NEGATIVE cleanup (Task 8)
- Extend `_relabel_negative_by_regex` to also use `scan_text` (catches opaque tokens)
- With new corpora, NEGATIVE pool gains diverse genuinely-non-sensitive values

---

## Spec and plan locations
- **Design spec:** `docs/superpowers/specs/2026-04-21-sprint15-dataset-foundation-scoring-honesty-design.md`
- **Implementation plan:** `docs/superpowers/plans/2026-04-21-sprint15-dataset-foundation-scoring-honesty.md`

## How to resume

```
# Verify state
git checkout sprint15/main
git log --oneline -5   # should show d0d13bd at HEAD
.venv/bin/python -m pytest tests/ -v   # all green

# Resume execution
# Read the plan, start at Task 6
# Use subagent-driven development skill
```
