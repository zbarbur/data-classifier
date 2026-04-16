# M4c — Heterogeneous gold-set scaffolding

**Date:** 2026-04-16
**Branch:** `research/meta-classifier`
**Status:** 🟡 Scaffolding complete — awaiting human review of 50 pre-filled rows

## Summary

Shipped the full M4c infrastructure: builder script, interactive
labeler CLI, schema validator with 22 unit + contract tests, and the
annotator guide. Built the 50-row gold set from 6 BQ public sources +
6 Sprint 12 safety-audit fixtures, applied per-source encoding
(plaintext for already-public structured data, XOR for user-
contributed free-text), and pre-filled `true_labels` with Claude
Opus 4.6's best-guess reading of each source's expected shape.

The 50 rows are **not gold yet** — they carry `review_status=prefilled`
across the board. Human review via `gold_set_labeler.py` is the next
step, and is the only thing that flips `review_status=human_reviewed`.

## What shipped

| File | Purpose |
|---|---|
| `scripts/m4c_build_gold_set.py` | BQ fetcher + Sprint 12 fixture extractor + encoder + pre-fill |
| `tests/benchmarks/meta_classifier/heterogeneous_gold_set.jsonl` | 50 rows, 4 616 total values |
| `tests/benchmarks/meta_classifier/gold_set_labeler.py` | Interactive review CLI, atomic writes |
| `tests/benchmarks/meta_classifier/gold_set_schema.py` | Structural validator |
| `tests/benchmarks/meta_classifier/test_gold_set_schema.py` | 22 tests (15 unit, 7 contract) |
| `docs/research/multi_label_gold_set_annotator_guide.md` | 1-page annotator protocol |

## Per-source coverage

| Source | Rows | Shape | Encoding |
|---|---|---|---|
| `sprint12_safety_audit` | 6 | free_text_heterogeneous (5) + opaque_tokens (1) | xor |
| `cfpb_complaints.complaint_database.consumer_complaint_narrative` (by product) | 15 | free_text_heterogeneous | xor |
| `stackoverflow.users.about_me` (by reputation bucket) | 10 | free_text_heterogeneous | xor |
| `hacker_news.full.text[type=comment]` (by year) | 5 | free_text_heterogeneous | xor |
| `stackoverflow.users.location` (by reputation) | 3 | structured_single | plaintext |
| `austin_311.incident_address` (by council district) | 3 | structured_single | plaintext |
| `new_york_311.incident_address` (by borough) | 2 | structured_single | plaintext |
| `github_repos.commits.author.name` | 2 | structured_single | plaintext |
| `github_repos.commits.author.email` | 1 | structured_single | plaintext |
| `crypto_ethereum.transactions.from_address` (by block range) | 3 | opaque_tokens | plaintext |

**Totals:** 50 rows. By shape: 35 free-text-heterogeneous, 11
structured-single, 4 opaque-tokens. By encoding: 36 xor, 14 plaintext.

### FEC / NPPES substitution

The M4c spec listed FEC indiv20 (2 rows) and NPPES (3 rows) as
structured anchors. Neither dataset is in `bigquery-public-data`,
so those 5 slots were filled by substitutes that preserve the
"structured_single PII" shape class:

- FEC indiv20 → `new_york_311.incident_address` (2 rows)
- NPPES → `github_repos.commits.author.{name,email}` (3 rows)

Both substitutes are already-public and carry real PII shapes
(addresses, person names, emails from public Git history). The
substitution is documented here and in the builder's `fetch_structured_anchors()`
docstring so future M4d work knows why this diverges from the queue
spec.

## Decisions made during scaffolding

### Decision 1 — Pre-fill authorship: Claude, with human review

Per user preference 2026-04-16 ("A - I'll review"), I pre-filled
`true_labels` for every row. Each pre-fill draws on the source's
expected shape (CFPB narratives → conservative because of XXXX
redaction; Git commits → `PERSON_NAME` or `EMAIL`; crypto
transactions → `ETHEREUM_ADDRESS`), not on value-by-value reading.

**Contamination caveat for M4d:** the M4d validation loop compares
an LLM-labeler's output against this gold set. If the M4d labeler
is also Claude Opus (or Claude 4.x class), the comparison measures
Claude self-consistency, not Claude-vs-human agreement. M4d must
use GPT-4 class, Gemini, or a materially different prompt
shape. Documented in annotator guide §"M4d contamination note".

### Decision 2 — Per-source encoding policy

Per user preference 2026-04-16 ("B - what about xor method for
commit?"), per-source encoding:

| Source class | Encoding | Rationale |
|---|---|---|
| Sprint 12 synthetic fixtures | xor | fixture values embed synthetic credentials (Stripe/GitHub/AWS shapes) that trip GitHub push protection; source file already XOR-encodes them — re-encoding here keeps the committed JSONL scanner-safe |
| Structured-single anchors (austin/ny/SO location, git, crypto) | plaintext | public-by-law or public-by-design; no credential-shaped substrings |
| Free-text narratives (CFPB/SO about_me/HN comments) | xor | scanner-dodge for credential-shaped substrings users paste into narratives; values are already public on source sites |

XOR's role is established: it uses `data_classifier.patterns._decoder.encode_xor`
and `decode_encoded_strings` to bypass GitHub push-protection secret
scanners. The XOR key is in the repo; this is **not** a PII-
confidentiality control.

**Bug caught during first push attempt:** initial policy called Sprint
12 fixtures "plaintext (already in the codebase as plaintext)" — but
the codebase stores them XOR-encoded at source and decodes at import.
My builder fetched the runtime-decoded form and wrote it plaintext,
which is how the scanner tripped. Fixed by extending XOR to the
Sprint 12 fixture path before the first clean push to origin.

### Decision 3 — Interactive labeler CLI (not JSONL hand-edit)

Per user preference 2026-04-16 ("C - let's do labeler"), shipped
`gold_set_labeler.py` as an interactive terminal UI with pagination,
decoded-value display, edit-with-confirmation, and atomic writes.
Trade-off: more code (≈ 300 lines) vs. JSONL hand-edit, but for 50
rows × decoded-value-pagination the UX dividend is meaningful.

Atomic writes mean Ctrl-C mid-session is safe — the `.tmp` + rename
idiom guarantees the canonical file is either the pre-session state
or includes the just-accepted row.

### Decision 4 — Label granularity: fine-grained + auto-derive family

Storage is fine-grained entity types (25 values, e.g. `EMAIL`,
`SSN`, `ETHEREUM_ADDRESS`). The corresponding 13-family mapping is
computed at read time via
`data_classifier.core.taxonomy.family_for()` and stored alongside in
`true_labels_family`. This gives M4b / M4e the freedom to score at
either granularity without requiring re-labeling.

The validator enforces consistency: if a human edits `true_labels`
via the CLI and forgets to update `true_labels_family`, the test
suite fails the contract test.

### Decision 5 — Validator-as-contract-test

`test_gold_set_schema.py::TestCommittedGoldSet::test_zero_errors`
runs the full structural validator against the committed JSONL on
every test run. This catches any drift introduced by hand-editing
or partial-write corruption — the gold set's integrity is now
continuously verified, not just at build time.

## Test results

| Suite | Tests | Result |
|---|---|---|
| `test_multi_label_metrics.py` (M4a) | 41 | ✓ 41 passed |
| `test_gold_set_schema.py::TestValidRow` | 1 | ✓ |
| `test_gold_set_schema.py::TestStructuralFailures` | 3 | ✓ |
| `test_gold_set_schema.py::TestEnumFailures` | 3 | ✓ |
| `test_gold_set_schema.py::TestLabelFailures` | 3 | ✓ |
| `test_gold_set_schema.py::TestPrevalenceFailures` | 3 | ✓ |
| `test_gold_set_schema.py::TestXorRoundtrip` | 1 | ✓ |
| `test_gold_set_schema.py::TestCrossRow` | 2 | ✓ |
| `test_gold_set_schema.py::TestCommittedGoldSet` | 6 | ✓ (all pass against the 50-row committed JSONL) |
| **Total** | **63** | **✓ 63 passed** |

Ruff check + format both clean across all new files.

## What human review looks like

Step 1 — launch the labeler:

```bash
python -m tests.benchmarks.meta_classifier.gold_set_labeler \
    --annotator "guy.guzner"
```

Step 2 — for each of the 50 rows:

- Press `x` to expand sample values from 20 to all N values (only if
  the first 20 don't give you a confident read)
- Press `a` to accept the pre-filled labels, or `e` to edit them
  (labeler validates labels against `ENTITY_TYPE_TO_FAMILY`)
- Press `s` to skip a row you're unsure about, come back later
- Press `q` to save progress and quit

Step 3 — periodic validation:

```bash
pytest tests/benchmarks/meta_classifier/test_gold_set_schema.py -v
```

Step 4 — session-end commit:

```bash
git add tests/benchmarks/meta_classifier/heterogeneous_gold_set.jsonl
git commit -m "research(m4c): hand-review N rows"
```

Estimated clock-time for all 50 rows: 2–4 focused hours at
~3-5 min/row. Resumable across sessions.

## Hand-off to downstream M4 sub-items

- **M4e (dual-report harness, ~2 days):** unblocked by M4a + this
  scaffolding. Wire `aggregate_multi_label()` into
  `family_accuracy_benchmark.py` with the gold set as its
  evaluation target.
- **M4d (LLM-labeled scale corpus, ~1 week):** blocked until this
  gold set has `≥80%` rows in `review_status=human_reviewed` state
  so the "Jaccard agreement ≥ 0.8 vs gold" acceptance gate has
  something to measure against. M4d task description must specify
  a non-Claude labeler model.
- **M4b (gate vs downstream harness, ~3-4 days):** blocked on
  Sprint 13 Item A landing on main. Independent of M4c progress.

## Follow-ups

- Consider adding `true_labels_prevalence` population to the
  labeler CLI's edit flow (currently labeler accepts/sets labels
  but doesn't prompt for prevalence; prevalence stays at the
  pre-fill value unless manually edited in the JSONL).
- If the labeler CLI gets heavy use, add a `--diff-prefill` flag
  that shows how the human labels differ from Claude's pre-fills
  in aggregate (instructive baseline for M4d: Claude vs human
  Jaccard agreement, computable from this dataset alone).
- FEC / NPPES substitution is pragmatic but not identical — if a
  public BQ mirror of FEC / NPPES appears, re-fetch those 5 rows.

## References

- M4c spec: `docs/experiments/meta_classifier/queue.md` lines
  2241-2287
- M4a metric helper (prerequisite): `docs/experiments/meta_classifier/runs/20260416-m4a-metric-helper/result.md`
- Multi-label philosophy (framing): `docs/research/multi_label_philosophy.md`
- Sprint 12 safety-audit fixtures (6 source rows): `tests/benchmarks/meta_classifier/sprint12_safety_audit.py::_build_heterogeneous_fixtures`
- Annotator guide: `docs/research/multi_label_gold_set_annotator_guide.md`
