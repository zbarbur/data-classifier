# Classification Library — Iteration 1 Initiation Prompt

**Purpose:** This prompt initiates the standalone `data_classifier` library project. Copy-paste into a fresh Claude Code session running from the `../data_classifier/` directory.

**Context origin:** Spun out of `BigQuery-connector/classifier/engine.py` (266 lines of regex cascade + sensitivity rollup logic). The long-term vision is an 8-engine, stateless classification library serving PII/PHI/PCI/credential detection across structured and unstructured content, with multiple deployment modes: embedded Python package (lowest latency), sidecar, standalone HTTP service, serverless. This is iteration 1 — scope is deliberately narrow.

**Deployment mode for iteration 1:** **Embedded Python package first.** Per `classification-library-docs/01-architecture.md`, embedded mode (`import as Python package, runs in-process`) is the lowest-latency deployment and the simplest migration path for the BigQuery connector. The HTTP API is a *wrapper* on top of the Python API, not the library itself. Iteration 1 freezes the **Python API** as the contract; the FastAPI HTTP wrapper is a secondary deliverable that can slip to iteration 2 if needed.

**Parent project:** `../BigQuery-connector/` (the original consumer). DO NOT modify files there during this session. The BigQuery connector's migration to this library is a Sprint 27 task.

---

## Prompt — paste this into the new session

```
I am initiating a new standalone Python library project called `data_classifier`
at the current working directory (/Users/guyguzner/Projects/data_classifier or
equivalent). This is iteration 1 of a larger library that will be developed
independently over many iterations.

CRITICAL RULES
==============

1. This library has its OWN independent backlog, git repo, and release cadence.
   It is NOT part of the BigQuery-connector project. Do not create backlog
   items in BigQuery-connector/backlog/ — the library has its own.

2. Do NOT modify any files in ../BigQuery-connector/. That project's migration
   to consume this library is explicitly a Sprint 27 task. Read its files for
   context only.

3. The PYTHON API (function signatures, Pydantic model shapes, profile loading
   interface) must be FROZEN against the specification at classification-library-docs/
   and validated against every current consumer in BigQuery-connector/ so the
   Sprint 27 migration is mechanical, not a redesign. This validation is a
   mandatory gate before closing iteration 1.

   Note: We are freezing the PYTHON API, not the HTTP API. HTTP is a wrapper.
   Sprint 27 BigQuery-connector migration is a pure import rename:
     from classifier.engine import classify_columns, load_profile_from_yaml
     →
     from data_classifier import classify_columns, load_profile_from_yaml
   No new service to deploy, no HTTP client, no feature flag, no latency cost.

SCOPE (Iteration 1 = Option B)
==============================

IN SCOPE (primary — Python package):
- Bootstrap a new Python 3.11+ library project using the agentic-agile-template
  as the process/workflow base (Python adaptation required — see below)
- git init + create a new GitHub repo under the same org as BigQuery-connector,
  named `data_classifier`
- Set up the library's own agile-backlog system (separate from BigQuery-connector)
- Package structure: `data_classifier` importable as a Python package
- Port BigQuery-connector/classifier/engine.py regex logic as the first engine
- Port BigQuery-connector/connectors/bigquery/classification_profiles.yaml as the
  bundled default profile
- Freeze the Python API: `classify_columns()`, `load_profile()`, `load_profile_from_yaml()`,
  `load_profile_from_dict()`, `compute_rollups()`, and any data classes/Pydantic models
  (`ClassificationFinding`, `ClassificationProfile`, `ClassificationRule`, `RollupResult`)
  as they exist in BigQuery-connector/classifier/engine.py
- Publish as an installable wheel (`pip install data_classifier` works — at
  least from a local path or a GitHub release)
- Contract validation doc: every current BQ connector consumer maps to the
  new Python API without regression
- Migration plan doc for Sprint 27 BigQuery-connector swap (purely mechanical rename)
- CI green on the new GitHub repo

IN SCOPE (secondary — HTTP wrapper, can slip to iteration 2 if time-constrained):
- FastAPI app at `data_classifier/api/main.py` wrapping the Python API
- `/health` + `/classify/column` endpoints matching classification-library-docs/02-api-reference.md
- Contract tests verifying HTTP shape matches docs
- Dockerfile for standalone deployment
- This exists as a thin wrapper over the Python API — building it should not
  require any internal changes to the library core

OUT OF SCOPE (later iterations):
- ML engines: GLiNER2, EmbeddingGemma, SLM (Gemma 3), LLM fallback
- Cloud DLP integration
- Heuristics engine, dictionary lookup, structural content classifier, boundary detector
- `/classify/text` endpoint (unstructured content)
- `/analyze/prompt` endpoint (prompt analysis module)
- Budget-aware orchestrator (single-engine cascade is sufficient for iteration 1)
- BigQuery-connector migration (Sprint 27 — purely mechanical rename once this lands)
- Event-based observability beyond basic structured logging
- Model serving infrastructure
- Publishing to PyPI (iteration 2+; for iteration 1, local editable install or
  GitHub release is sufficient)

PROCESS — USE THE AGENTIC-AGILE TEMPLATE
=========================================

The agentic-agile-template lives at:
  /Volumes/My Shared Files/Projects/agentic-scrum-template/
  (GitHub: https://github.com/zbarbur/agentic-agile-template)

The template is TypeScript-based (Biome, package.json, Next.js), so we will
adopt it SELECTIVELY — take the process infrastructure, adapt the code tooling
to Python. Specifically:

Take from template:
- Process docs: docs/process/ (sprint planning, execution, closure, kanban)
- Claude Code skills: .claude/skills/sprint-start, sprint-end, commit, etc.
- Engineering guides: docs/engineering/ (error handling, security, API design, testing)
- 140+ gotchas: docs/GOTCHAS.md
- Context management: CLAUDE.md + MEMORY.md + PROJECT_CONTEXT.md three-layer system
- Task templates, coding standards, commit message conventions
- bin/init-project.sh placeholder-replacement pattern (read it, reimplement
  for Python or run it and then convert)

Adapt for Python:
- pyproject.toml instead of package.json (Python 3.11+, FastAPI, pydantic, pytest, ruff)
- ruff check + ruff format instead of Biome
- pytest instead of node --test
- Dockerfile based on python:3.11-slim
- GitHub Actions CI: ruff check + ruff format --check + pytest
- No Next.js dashboard (delete the landing/ and dashboard/ references)

SPECIFICATIONS (READ FIRST, IN ORDER)
=====================================

All specs are in classification-library-docs/ in this project:

1. classification-library-docs/CLAUDE.md — project overview and settled decisions
2. classification-library-docs/01-architecture.md — system architecture, engine stack, deployment modes
3. classification-library-docs/02-api-reference.md — FROZEN API CONTRACT for iteration 1
4. classification-library-docs/04-engines.md — engine interface (only the regex engine section matters for iteration 1)
5. classification-library-docs/05-pipelines.md — orchestrator and cascade logic (iteration 1 is single-engine, simplified)

You do NOT need to read the other docs (ML architecture, prompt analysis,
performance, structural detection) for iteration 1 — those are future scope.

For context on what you are porting:
6. ../BigQuery-connector/classifier/engine.py — the 266-line source file being ported
7. ../BigQuery-connector/connectors/bigquery/classification_profiles.yaml — the default profile
8. ../BigQuery-connector/classifier/runner.py — DB integration layer (STAYS in BQ connector — do NOT port)
9. ../BigQuery-connector/connectors/bigquery/connector.py — search for classifier imports to see current consumption patterns
10. ../BigQuery-connector/sailpoint_api/routes/classifications.py — HTTP consumer in the API

Test fixtures to port (golden set — new library must produce identical results):
11. ../BigQuery-connector/tests/test_classification_runner.py — 365 lines.
    Contains the largest set of test inputs (column metadata + sample values)
    and expected classification outputs. Port the engine-level tests
    (classify_columns, compute_rollups, load_profile_* — NOT the DB runner
    tests that touch psycopg / classification_findings table).
12. ../BigQuery-connector/tests/test_connector_classification.py — 170 lines.
    Contains BQ connector's end-to-end classification invocation patterns.
    Port any test inputs that drive classify_columns() — skip the scanner/
    writer-level orchestration which stays in BQ connector.
13. ../BigQuery-connector/tests/test_classifications_api.py — 71 lines.
    API-level consumer contract. Port the input/expected-output pairs as
    contract test fixtures for data_classifier.

FIXTURE PORTING STRATEGY — the user specifically called this out:
"We will build the library testing based on fixtures we'll take from bigquery project."

This means:
- Copy every test input (columns + sample_values + profile) from the three
  files above into tests/fixtures/ in the new library as YAML or JSON files
- Copy every expected output (ClassificationFinding lists, RollupResult objects)
  as golden-set fixtures alongside the inputs
- Write parameterized pytest tests that load the fixtures and verify the new
  library produces identical outputs on identical inputs
- These fixture-based tests become the primary behavioral contract: if they
  pass, the Sprint 27 BigQuery-connector migration is guaranteed to work
  because the behavior is provably identical

DELIVERABLES CHECKLIST
======================

## Phase 1: Project bootstrap
- [ ] git init in current directory
- [ ] Create new GitHub repo under same org as BigQuery-connector, named `data_classifier`
- [ ] git remote add origin + initial push
- [ ] Adapt agentic-agile-template structure: copy relevant process docs, skills, gotchas
- [ ] pyproject.toml with Python 3.11+, FastAPI, pydantic v2, pytest, pytest-asyncio, ruff, httpx
- [ ] ruff config matching BigQuery-connector conventions (line length 120, target py311, E/F/I/N/W rules, N815 allowed for API schemas)
- [ ] pytest config with testpaths=["tests"], asyncio_mode="auto"
- [ ] Dockerfile (multi-stage, python:3.11-slim base)
- [ ] .gitignore (Python, .venv, .env, __pycache__, etc.)
- [ ] README.md (project description, quick start, link to classification-library-docs/)
- [ ] Adapted CLAUDE.md for this project (reference classification-library-docs/CLAUDE.md as the architectural source of truth)
- [ ] .github/workflows/ci.yaml: ruff check + ruff format --check + pytest

## Phase 2: Library's own backlog
- [ ] agile-backlog initialization: create backlog/ directory, set up sprint-config.yaml
- [ ] Create first sprint: Sprint 1
- [ ] File iteration 2 items as backlog entries (GLiNER2 engine, /classify/text, etc.) so the backlog has continuity

## Phase 3: Package structure
- [ ] data_classifier/ Python package with:
  - [ ] data_classifier/__init__.py — re-exports the public Python API
        (classify_columns, load_profile, load_profile_from_yaml,
        load_profile_from_dict, compute_rollups, ClassificationFinding,
        ClassificationProfile, ClassificationRule, RollupResult)
  - [ ] data_classifier/core/ — shared types, config, data classes
  - [ ] data_classifier/engines/ — engine implementations
  - [ ] data_classifier/engines/regex_engine.py — ported from BigQuery-connector/classifier/engine.py
  - [ ] data_classifier/engines/interface.py — engine abstract base per 04-engines.md
  - [ ] data_classifier/orchestrator/ — cascade orchestrator (single-engine for iteration 1)
  - [ ] data_classifier/profiles/ — bundled classification profiles (ported from BQ connector)
  - [ ] data_classifier/profiles/standard.yaml — default profile
  - [ ] data_classifier/api/ (secondary — optional for iteration 1) — FastAPI wrapper
  - [ ] data_classifier/api/main.py — thin wrapper over the Python API
  - [ ] data_classifier/api/models.py — Pydantic request/response models matching 02-api-reference.md exactly
  - [ ] data_classifier/api/routes/classify.py — /classify/column endpoint
- [ ] tests/ directory:
  - [ ] tests/fixtures/columns/ — input column definitions (name, sample_values, type) ported from BQ connector tests
  - [ ] tests/fixtures/profiles/ — classification profile YAMLs ported from BQ connector
  - [ ] tests/fixtures/expected/ — expected ClassificationFinding and RollupResult outputs paired with inputs
  - [ ] tests/test_regex_engine.py — engine unit tests
  - [ ] tests/test_python_api.py — PRIMARY contract tests for classify_columns(), load_profile(), etc.
  - [ ] tests/test_golden_fixtures.py — parameterized tests that load every fixture and verify identical output vs expected (THIS is the Sprint 27 migration guarantee)
  - [ ] tests/test_classify_column_api.py — FastAPI TestClient integration tests (if HTTP wrapper built)
  - [ ] tests/test_api_contract.py — parses examples from 02-api-reference.md as fixtures (if HTTP wrapper built)

## Phase 4: Regex engine implementation
- [ ] Port regex cascade + sensitivity rollup logic from BigQuery-connector/classifier/engine.py
- [ ] Conform to engine interface defined in classification-library-docs/04-engines.md
- [ ] Preserve existing behavior byte-for-byte (same patterns → same results)
- [ ] Unit tests passing

## Phase 5: Python API freeze (PRIMARY) + HTTP wrapper (SECONDARY, optional)

PRIMARY — Python API:
- [ ] Public functions exported from `data_classifier.__init__`:
      classify_columns(), load_profile(), load_profile_from_yaml(),
      load_profile_from_dict(), compute_rollups()
- [ ] Public types: ClassificationFinding, ClassificationProfile,
      ClassificationRule, RollupResult (port as-is from BQ connector)
- [ ] Function signatures match BigQuery-connector/classifier/engine.py
      where possible (minimal breaking changes to ease Sprint 27 migration)
- [ ] `pip install -e .` from the repo root works; `python -c "from data_classifier import classify_columns"` succeeds
- [ ] Comprehensive Python API tests in tests/test_python_api.py

SECONDARY — HTTP wrapper (build if time permits, otherwise defer to iteration 2):
- [ ] FastAPI app with /health and /classify/column
- [ ] Request/response Pydantic models match classification-library-docs/02-api-reference.md EXACTLY (no drift)
- [ ] /classify/column internally calls the Python API (thin wrapper, no logic duplication)
- [ ] TestClient integration tests passing
- [ ] Contract test parses the example JSON from 02-api-reference.md and verifies the implementation produces matching shape
- [ ] Dockerfile builds a runnable service image

## Phase 6: Python API contract review (MANDATORY GATE)
- [ ] Enumerate every current BigQuery-connector consumer of classifier/engine.py:
      - classifier/runner.py (engine invocation from the DB runner)
      - connectors/bigquery/connector.py (direct engine calls during scan)
      - sailpoint_api/routes/classifications.py (HTTP consumer)
      - Anything else found via grep for "from classifier" in BigQuery-connector
- [ ] For each consumer, document in docs/migration-from-bq-connector.md:
      - What function it imports from classifier.engine
      - What arguments it passes
      - What return value it consumes
      - The exact rename diff for Sprint 27 (old import → new import)
- [ ] Gap analysis: if any current consumer needs a function or type that the
      new data_classifier Python API doesn't export, EITHER add it to this
      iteration's API OR file a clear gap doc that Sprint 27 must resolve
      before migration begins
- [ ] Sprint 27 migration plan (purely mechanical):
      - Add `data_classifier` to BigQuery-connector/pyproject.toml dependencies
      - Run a `sed` (or scripted rewrite) on every `from classifier.engine import`
        → `from data_classifier import` (or similar)
      - Delete BigQuery-connector/classifier/engine.py (keep classifier/runner.py,
        which is the DB integration layer and stays in BQ connector)
      - Verify tests still pass unchanged
      - No feature flag needed — behavior is identical because the code is the same

## Phase 7: CI green
- [ ] ruff check passes
- [ ] ruff format --check passes
- [ ] pytest green
- [ ] GitHub Actions workflow passes on push to main
- [ ] Dockerfile builds cleanly

## Phase 8: Sprint 1 closure + backlog for Sprint 2
- [ ] Sprint 1 handover doc documenting what was delivered, what's deferred
- [ ] Sprint 2 backlog populated with next iteration items:
      - Heuristics engine (statistics-based)
      - Column name semantics engine
      - Dictionary lookup engine
      - Structured secret scanner
      - Event-based observability
      - /classify/text endpoint (unstructured content)

FIXTURE-BASED CONTRACT GUARANTEE
================================

The user's chosen validation strategy: copy every test input + expected output
from BigQuery-connector's classifier tests into this library as fixtures, then
write parameterized tests that load them and verify identical behavior.

Why this works:
- If the new library produces identical output on identical input for every
  BQ connector test case, then Sprint 27 migration cannot regress.
- The fixture files become the behavioral contract — more concrete and testable
  than any prose API spec.
- Sprint 27 BigQuery-connector will ALSO run these same tests (via its own
  data_classifier dependency), giving a double-verification.
- When iteration 2 adds new engines, these fixtures remain the regression
  baseline — new engines must not change regex-tier outputs.

Port strategy:
- Read the three BQ test files listed above (test_classification_runner.py,
  test_connector_classification.py, test_classifications_api.py)
- Extract every test input dict (columns, sample_values, profile name)
- Extract every assertion (expected findings, expected rollups)
- Convert to YAML fixture files with input + expected pairs
- Parameterize pytest over every fixture file

SUCCESS CRITERIA
================

- New GitHub repo `data_classifier` exists under the same org as BigQuery-connector
- `pip install -e .` from the repo root succeeds; `python -c "from data_classifier import classify_columns, load_profile"` returns no error
- `classify_columns()` called with a list of column metadata + sample values
  returns ClassificationFinding objects with detected entity_type, confidence,
  sensitivity, regulatory — byte-for-byte behaviorally identical to
  BigQuery-connector/classifier/engine.py
- All tests passing, CI green
- docs/migration-from-bq-connector.md demonstrates the new Python API covers
  every current BigQuery-connector consumer without regression, with exact
  import-rename diffs for Sprint 27
- Library has its own backlog, own git repo, own CI, and is ready for
  independent iteration 2 development
- Sprint 27 migration is a pure mechanical rename: add dependency, rewrite
  imports, delete old engine.py — no API redesign, no behavioral drift, no
  new deployment target, no feature flag
- (Secondary) If HTTP wrapper was built: `uvicorn data_classifier.api.main:app`
  serves /health and /classify/column, matches 02-api-reference.md contract

WORKFLOW
========

1. Brainstorm any genuinely uncertain design decisions first (using the
   brainstorming skill from the template)
2. Propose the phase plan — get user approval before executing
3. Phase 1 (bootstrap) first, then Phase 2 (backlog), then Phase 3 (structure),
   then Phase 4 (engine), then Phase 5 (API), then Phase 6 (contract review)
4. Run tests after every phase
5. Commit incrementally — one commit per phase minimum
6. Do NOT touch BigQuery-connector during this session

START HERE: read classification-library-docs/CLAUDE.md and
classification-library-docs/02-api-reference.md, then propose your Phase 1
plan (bootstrap steps: template adaptation, pyproject.toml structure, initial
directory layout). Wait for my approval before writing any code.
```

---

## Notes for the human operator

1. **Template caveat:** The agentic-agile-template is TypeScript-based. The session will need to selectively adopt the process infrastructure (docs, skills, CLAUDE.md pattern) while substituting Python tooling (pyproject.toml, ruff, pytest, FastAPI). Don't let the session run `bin/init-project.sh` directly — it will generate TypeScript scaffolding. Instead, have it manually adapt the structure.

2. **GitHub repo creation:** The session will need `gh` CLI access and appropriate permissions to create a new repo under the same org as BigQuery-connector. Confirm the org name (check BigQuery-connector's remote: `git remote get-url origin`) before starting.

3. **API contract freeze = critical:** This is the one non-negotiable deliverable. Without it, Sprint 27 will turn into "redesign the API we just shipped" instead of "wire up the already-agreed API."

4. **BQ connector is read-only:** The session should read BigQuery-connector files for context but never modify them. If it wants to, stop it — the migration is Sprint 27 work, not Sprint 26.

5. **Use the brainstorming skill:** If the session hits a genuinely uncertain design decision (e.g., engine interface shape, profile loading strategy, orchestrator abstraction), have it invoke the brainstorming skill before coding. Don't skip ahead to implementation for nuanced trade-offs.
