# Sprint 1 Handover — data_classifier Bootstrap

> **Date:** 2026-04-10
> **Theme:** Library bootstrap, RE2 regex engine, pattern library, test suite, API freeze

## Delivered

### Core Library
- **Package:** `data_classifier` installable via `pip install -e .`
- **Engine:** RE2 two-phase regex engine (Set screening + individual extraction + validators)
- **43 content patterns** across 4 categories (PII: 15, Financial: 6, Credential: 20, Health: 2)
- **15 profile rules** (column name matching) in bundled `standard.yaml`
- **Validators:** Luhn (credit card), SSN zero-group, IPv4 reserved
- **Orchestrator:** Engine cascade with event telemetry, budget awareness, mode-based filtering
- **Events:** Pluggable EventEmitter with TierEvent + ClassificationEvent

### API Surface (Frozen)
- `classify_columns(list[ColumnInput], profile, *, min_confidence, categories, budget_ms, run_id, config, mask_samples, max_evidence_samples)`
- `load_profile()`, `load_profile_from_yaml()`, `load_profile_from_dict()`
- `compute_rollups()`, `rollup_from_rollups()`
- `get_supported_categories()`, `get_supported_entity_types()`, `get_supported_sensitivity_levels()`, `get_pattern_library()`
- Types: `ColumnInput`, `ColumnStats`, `ClassificationFinding`, `SampleAnalysis`, `ClassificationProfile`, `ClassificationRule`, `RollupResult`

### Key Design Decisions
- **Confidence vs Prevalence:** Confidence = "entity exists in column" (match count based). Prevalence = `SampleAnalysis.match_ratio`.
- **Category dimension:** PII / Financial / Credential / Health on every rule and finding
- **RE2 from day 1:** Linear-time guarantee, Set matching, GIL release
- **Connector-agnostic:** ColumnInput abstracts all database specifics
- **Category filtering:** `categories=["PII"]` on classify_columns()
- **XOR-encoded credential examples:** Bypass GitHub push protection

### Tests
- **234 tests passing** in 0.34s (local), ~19s CI
- CI green on Python 3.11, 3.12, 3.13
- Pattern self-tests (43 × 4 checks), engine behavior, golden fixtures (BQ compat), rollups, confidence, masking, validators, introspection

### Documentation
- `docs/CLIENT_INTEGRATION_GUIDE.md` — shared with BQ team
- `docs/migration-from-bq-connector.md` — Sprint 27 migration plan, consumer-by-consumer
- `docs/ROADMAP.md` — iterations 1-4 with Presidio coverage analysis
- `docs/PATTERN_SOURCES.md` — 6 sources documented with license/IP position and gap closure plan
- `docs/pattern-library.html` — generated HTML reference for pattern curation
- `CLAUDE.md` — project rules adapted for Python library

### Infrastructure
- GitHub repo: https://github.com/zbarbur/data-classifier
- CI: GitHub Actions (ruff check + ruff format --check + pytest)
- Backlog: 44 items via agile-backlog, 5 done, 39 future
- 9 sprint skills installed from agile-backlog

## Deferred to Iteration 2

- HTTP wrapper (FastAPI `/classify/column`, `/health`)
- Column name semantics engine (400+ variants, fuzzy matching)
- Heuristic statistics engine
- Dictionary lookup engine
- Structured secret scanner
- Pattern expansion to 50+ (URL, crypto, ABA, NPI, ITIN, country-specific)
- Property-based testing (Hypothesis)
- Performance benchmark tests
- `/classify/text` endpoint

## Known Issues

1. **Profile rule ordering matters:** More-specific rules must come before less-specific (fixed: IP_ADDRESS before ADDRESS)
2. **GitHub push protection:** Credential pattern examples require XOR encoding. The `docs/pattern-library.html` masks credential examples.
3. **No `examples_match` for 4 credential patterns** (Slack xoxp, Shopify, Databricks, Slack bot) — GitHub detects even all-zeros formats. XOR encoding covers the rest.

## Decisions Made

1. Clean `list[ColumnInput]` API (Option A) — no dict backward compat
2. Category dimension added (PII/Financial/Credential/Health) — gap identified by BQ team
3. RE2 from iteration 1 (not deferred) — build it right
4. Pattern library externalized to JSON with XOR-encoded credential examples
5. Confidence = match count based, not prevalence based
6. Post-filter category approach (pre-filter in iteration 3 for ML engines)
7. agile-backlog for backlog management
8. Testing: phased approach — structural now, corpus-based later

## Open Threads (Carry to Sprint 2)

### 1. Testing Strategy — Corpus Collection
Agreed on phased approach: structural tests now (done — 234 passing), corpus-based later. **Open question:** Where do we get a labeled dataset for precision/recall benchmarks? Options discussed:
- Synthetic labeled columns (generate fake schemas with known PII types)
- Presidio's test data (MIT licensed)
- Production data sample from BQ connector scans (anonymized)
- StarPii dataset (20,961 annotated secrets — for credential testing)

**Action needed:** Decide corpus source and start collection. This gates the accuracy benchmark backlog item.

### 2. Pattern Licensing — Deeper Review
Documented in `docs/PATTERN_SOURCES.md` with license/IP position. All patterns are original implementations. **Open question:** As we expand to 50+ patterns (iteration 2), should we:
- Establish a formal review process for each new pattern (source, license, original vs referenced)?
- Create a pattern contribution guide for future contributors?
- Set up automated checks that verify no pattern regex was copied verbatim from AGPL sources (trufflehog)?

### 3. BQ Connector Coordination
Client integration guide shared. **Open items with BQ team:**
- DB migration needed: `category TEXT` column on `classification_findings` table
- `evidence TEXT` and `match_ratio FLOAT` columns also needed
- Sampling implementation: what sample size? Configurable per-profile?
- When does Sprint 27 migration start? Need to coordinate timing.
- Profile YAML: will BQ connector add `category` to their DB-stored profiles?

### 4. Performance Measurement Strategy
Library captures timing via `TierEvent.latency_ms` and `ClassificationEvent.total_ms`. **Open questions:**
- Should we add a timing report to `classify_columns()` return value (not just events)?
- How do we expose per-column timing to the connector for their dashboards?
- `budget_ms` is accepted but not enforced in iteration 1. When do we implement the budget engine?
- Should RE2 Set compilation time be measured separately from matching time?

### 5. Custom Regexp from Consumers
Discussed: consumers will want to add their own patterns (e.g., `EMP-\d{6}` for employee IDs). **Open questions:**
- How do custom patterns interact with the RE2 Set? (Recompile on each request? Cache per consumer?)
- False positive management: if a custom pattern produces too many FPs, how does the consumer tune it?
- Should custom patterns have a lower default confidence than curated patterns?
- The `config` parameter on `classify_columns()` is the entry point — needs design spec.

### 6. Engine Category Pre-Filtering
Currently category filtering is post-match (fine for regex). **Open question for iteration 3:**
- ML engines (GLiNER2, embeddings) take 10-30ms each. If client only wants Credentials, we should skip them entirely.
- Should `supported_categories` be added to the `ClassificationEngine` interface now (forward declaration)?
- Or should the orchestrator infer categories from the pattern/rule registry?

### 7. HTML Pattern Reference Usability
Current HTML shows credential examples as "click to decode" (XOR + JS). **Open questions:**
- Is this workflow acceptable for pattern curation? Or do we need a local-only unencoded view?
- Should we add search/filter to the HTML reference?
- Should the HTML include a "test this pattern" feature (paste a value, see if it matches)?

## Commits

| # | Hash | Description |
|---|---|---|
| 1 | 10d62d6 | feat: bootstrap data_classifier library |
| 2 | 2a9f405 | feat: RE2 two-phase engine + pattern library + category dimension |
| 3 | a4e8555 | feat: expand patterns to 43, category filtering, introspection API |
| 4 | 95638ce | docs: pattern sources inventory + gap closure plan |
| 5 | 1ca66d3 | docs: add license & IP position to pattern sources |
| 6 | d8cad4f | test: 234 tests — patterns, engine, golden fixtures, rollups |
| 7 | cd90537 | docs: Sprint 27 migration plan |
| 8 | (next) | Sprint 1 handover |
