# data_classifier — Project Rules

> **Scope:** Static rules, commands, and conventions that apply to every session.
>
> **Not here:** Evolving state belongs in `.claude/MEMORY.md`. Sprint status belongs in sprint handover docs.

## Context System

| File | Purpose | Updated by | Frequency |
|---|---|---|---|
| `CLAUDE.md` (this file) | Session rules, commands, code style | Human | Rarely |
| `.claude/MEMORY.md` | Decisions, patterns, lessons | Agent | Every sprint |
| `docs/process/PROJECT_CONTEXT.md` | Full project snapshot | Agent | Every sprint end |
| `docs/sprints/SPRINT{N}_HANDOVER.md` | Per-sprint delivery log | Agent | Sprint closure |

## What This Project Is

Standalone, stateless Python library for detecting and classifying sensitive data in structured database columns. Connector-agnostic — works with BigQuery, Snowflake, Postgres, or any structured data source.

**Architectural source of truth:** `docs/spec/` contains the full specification.
Only docs 01-05 are relevant for iteration 1 (regex engine).

## Critical Rules

1. This library has its OWN git repo, backlog, and CI. It is NOT part of BigQuery-connector.
2. Do NOT modify any files in `../BigQuery-connector/`.
3. The Python API is defined in `docs/CLIENT_INTEGRATION_GUIDE.md` — any change requires updating that doc.
4. Library is stateless: never connects to a database, never writes to disk.
5. Library is connector-agnostic: no BQ/Snowflake/Postgres-specific concepts in library code.

## Commands

### Testing & Quality
- **Run tests**: `.venv/bin/python -m pytest tests/ -v`
- **Lint**: `ruff check . && ruff format --check .`
- **Format**: `ruff check --fix . && ruff format .`
- **Full CI**: `ruff check . && ruff format --check . && .venv/bin/python -m pytest tests/ -v && bash scripts/ci_browser_parity.sh`
- **Browser release**: `cd data_classifier/clients/browser && npm run release`
- **IMPORTANT**: Always use `.venv/bin/python` — homebrew python3 is missing ML deps (gliner2, torch). Never use bare `pytest` or `python3`.
- **Browser parity**: Any change to Python detection logic (validators, patterns, scoring) must be followed by `bash scripts/ci_browser_parity.sh` to verify JS stays in sync.

### Development
- **Install (editable, preferred)**: `uv venv .venv --python 3.14 && uv pip install -e ".[dev,meta,ml-full]"` then `uv pip install gliner2==1.2.6` (gliner2 isn't in pyproject extras but is imported by `gliner_engine.py`). Plain `pip install -e ".[dev]"` still works as a fallback.
- **Import check**: `python -c "from data_classifier import classify_columns, ColumnInput"`

## Code Style — Python

- **Formatter/linter**: ruff (line-length 120, target py311)
- **Rules**: E, F, I, N, W (N815 ignored for API schemas)
- **Type hints** on all public interfaces
- **Dataclasses** for library types (not Pydantic — keep lightweight)
- **Pydantic** only in `data_classifier/api/` (HTTP request/response validation)
- **No print statements** — use `logging`
- **Tests**: pytest, fixtures in `tests/fixtures/`, parameterized where possible

## Project Structure

```
data_classifier/
├── __init__.py              # Public API: classify_columns, load_profile, types
├── core/types.py            # All dataclasses (ColumnInput, ClassificationFinding, etc.)
├── engines/
│   ├── interface.py         # ClassificationEngine base class
│   └── regex_engine.py      # Regex pattern matching (iteration 1 engine)
├── orchestrator/
│   └── orchestrator.py      # Engine cascade coordinator
├── profiles/
│   ├── __init__.py          # load_profile, load_profile_from_yaml, load_profile_from_dict
│   └── standard.yaml        # Bundled default profile (15 entity types)
├── events/
│   ├── types.py             # TierEvent, ClassificationEvent
│   └── emitter.py           # Pluggable event handlers
└── api/                     # HTTP wrapper (secondary, may defer to iteration 2)
    ├── main.py
    ├── models.py
    └── routes/

tests/
├── conftest.py              # Shared fixtures
├── fixtures/                # Input/expected golden-set files
├── test_regex_engine.py
├── test_python_api.py
└── test_golden_fixtures.py  # Parameterized fixture-based contract tests

docs/
├── CLIENT_INTEGRATION_GUIDE.md  # API contract for connector teams
├── process/                     # Sprint planning, coding standards, etc.
└── sprints/                     # Per-sprint handover docs
```

## Sprint Completion Gate

Before closing any sprint:
1. `ruff check .` — zero warnings
2. `ruff format --check .` — zero diffs
3. `pytest tests/ -v` — all green
4. GitHub Actions CI passing on main
5. **Family accuracy benchmark** — run and attach the resulting
   `summary.json` to the sprint handover doc:
   ```
   DATA_CLASSIFIER_DISABLE_ML=1 \
       python -m tests.benchmarks.family_accuracy_benchmark \
       --out /tmp/bench.predictions.jsonl \
       --summary /tmp/bench.summary.json \
       --compare-to docs/research/meta_classifier/sprint12_family_benchmark.json
   ```
   The `shadow.overall.family.cross_family_rate` metric must not
   regress from the committed baseline without a written
   justification in the sprint handover. See
   `tests/benchmarks/README.md` for the full explanation of Tier 1
   vs Tier 2 scoring.
