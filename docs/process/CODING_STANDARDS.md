# Coding Standards — data_classifier

## Formatting & Linting

### Ruff

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.

| Setting | Value |
|---------|-------|
| Target | Python 3.11 |
| Line length | 120 |
| Rules | E, F, I, N, W |
| Ignored | N815 (mixedCase in Pydantic/API schemas) |

**Commands:**
```bash
ruff check .                    # Lint
ruff check --fix .              # Auto-fix
ruff format --check .           # Check formatting
ruff format .                   # Apply formatting
```

---

## Python

### Version & Syntax

- **Python 3.11+** — use modern type syntax (`list[dict]`, `str | None`)
- `from __future__ import annotations` for forward references
- f-strings for formatting

### Type Hints

1. Type hints on all public interfaces
2. No `Any` — use `object` and narrow with `isinstance`
3. Union syntax: `str | None` not `Optional[str]`
4. Return types on all public functions

### Data Models

| Use Case | Tool |
|----------|------|
| Library core types | `@dataclass` |
| HTTP request/response | `pydantic.BaseModel` |
| Constants | Module-level dicts |

---

## Testing

### pytest

```bash
pytest tests/ -v                           # All tests
pytest tests/test_regex_engine.py -v       # Specific file
pytest tests/ -k "test_ssn" -v             # Pattern match
```

### Test Organization

```
tests/
  conftest.py              # Shared fixtures
  fixtures/                # YAML/JSON test data
  test_patterns.py         # Pattern regex validation
  test_regex_engine.py     # Engine behavior
  test_golden_fixtures.py  # BQ compat contract
```

### Guidelines

1. Descriptive names — describe behavior, not implementation
2. Use fixtures from `conftest.py` and YAML files
3. Parameterize over data — one test function, many inputs
4. No test interdependence
5. Include assertion messages for failure diagnosis

---

## Error Handling

| Type | Behavior | Example |
|------|----------|---------|
| **Required** | Raise exception | Profile loading, pattern compilation |
| **Best-effort** | Log and continue | Single engine failure in cascade |

Rules:
1. Never swallow errors silently
2. Engines must not crash the cascade — orchestrator catches per-engine exceptions
3. Profile/pattern errors fail at startup
4. Include context in error messages

---

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Files | `snake_case.py` | `regex_engine.py` |
| Variables & functions | `snake_case` | `match_ratio` |
| Constants | `UPPER_SNAKE_CASE` | `SENSITIVITY_ORDER` |
| Classes | `PascalCase` | `ClassificationFinding` |
| Private | `_leading_underscore` | `_parse_rules` |
| Tests | `test_*.py` | `test_regex_engine.py` |

---

## File Organization

- One module, one responsibility
- Keep files under 300 lines
- `__init__.py` only re-exports (no logic)
- Use `__all__` for explicit public API

---

## Import Ordering (enforced by Ruff)

```python
from __future__ import annotations     # 1. Future
import logging                          # 2. Standard library
import re2                              # 3. Third-party
from data_classifier.core.types import  # 4. Local
```

---

## Comments & Docstrings

- Comments explain **why**, not **what**
- Public functions get docstrings (Google style)
- TODOs reference task IDs when applicable

---

## Logging

- `logging` module, never `print()`
- One logger per module: `logger = logging.getLogger(__name__)`
- Levels: DEBUG (internals), INFO (operational), WARNING (degraded), ERROR (failures)

---

## Git Commits

Format: `{type}: {short description}`

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

Rules: imperative mood, under 72 chars, one logical change per commit.
