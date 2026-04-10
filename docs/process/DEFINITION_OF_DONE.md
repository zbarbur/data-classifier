# Definition of Done Guide — data_classifier

## Principle

Every DoD checkbox must be **independently verifiable** — by running a command, grepping the codebase, or calling a function. If you cannot verify a checkbox without reading the implementer's mind, it is not a valid DoD item.

---

## Universal DoD Items

Every task, regardless of type:

```markdown
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] Lint clean (`ruff check . && ruff format --check .`)
```

---

## DoD by Task Type

### Engine / Core Library Tasks

```markdown
- [ ] Engine implements ClassificationEngine interface
- [ ] classify_column() returns correct findings for test inputs
- [ ] New patterns compile in RE2 (`re2.compile(pattern)` succeeds)
- [ ] Pattern examples validated (examples_match match, examples_no_match don't)
- [ ] Confidence values in range [0.0, 1.0]
- [ ] Category field populated on all findings
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] Lint clean (`ruff check . && ruff format --check .`)
```

### API / HTTP Endpoint Tasks

```markdown
- [ ] {METHOD} {/endpoint} returns {status code} with {expected shape}
- [ ] Error cases return appropriate status codes (400, 422, 500)
- [ ] Request validates against Pydantic model
- [ ] Response shape matches classification-library-docs/02-api-reference.md
- [ ] TestClient integration test passes
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] Lint clean (`ruff check . && ruff format --check .`)
```

### Pattern Library Tasks

```markdown
- [ ] Pattern compiles in RE2 (no lookahead/lookbehind/backreferences)
- [ ] examples_match values match the regex
- [ ] examples_no_match values do NOT match
- [ ] Validator (if applicable) accepts valid and rejects invalid
- [ ] Credential examples XOR-encoded (GitHub push protection)
- [ ] HTML reference regenerated (`python scripts/generate_pattern_docs.py`)
- [ ] Pattern metadata complete (name, entity_type, category, sensitivity, confidence, description)
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] Lint clean (`ruff check . && ruff format --check .`)
```

### Documentation Tasks

```markdown
- [ ] Doc reflects current code behavior (not aspirational)
- [ ] CLIENT_INTEGRATION_GUIDE.md updated if API changed
- [ ] ROADMAP.md updated if scope changed
- [ ] No broken internal links
```

### Refactoring Tasks

```markdown
- [ ] Old code removed (no dead code)
- [ ] All existing tests still pass without modification
- [ ] No behavior change from consumer perspective
- [ ] Import paths updated across all consumers
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] Lint clean (`ruff check . && ruff format --check .`)
```

---

## Anti-Patterns

| Bad | Good |
|-----|------|
| `[ ] Engine works` | `[ ] classify_column() returns EMAIL finding for "john@acme.com" sample` |
| `[ ] Tests written` | `[ ] test_regex_engine.py: 15 tests covering name match, sample match, confidence, masking` |
| `[ ] Pattern added` | `[ ] us_itin pattern compiles in RE2, matches "912-78-1234", rejects "123-45-6789"` |
| `[ ] Feature implemented and tests pass` | Split into two checkboxes |

---

## Verification Commands

| Check | Command |
|-------|---------|
| Tests pass | `pytest tests/ -v` |
| Lint clean | `ruff check .` |
| Format clean | `ruff format --check .` |
| Import works | `python -c "from data_classifier import classify_columns"` |
| Patterns valid | `pytest tests/test_patterns.py -v` |
| Golden fixtures | `pytest tests/test_golden_fixtures.py -v` |
| Full CI | `ruff check . && ruff format --check . && pytest tests/ -v` |
