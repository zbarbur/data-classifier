# data_classifier

General-purpose data classification engine for detecting sensitive data in structured database columns. Stateless, connector-agnostic Python library.

## Quick Start

```bash
pip install -e ".[dev]"
```

```python
from data_classifier import classify_columns, load_profile, ColumnInput

profile = load_profile("standard")
columns = [
    ColumnInput(column_name="customer_ssn", column_id="users:ssn"),
    ColumnInput(column_name="email_address", column_id="users:email"),
    ColumnInput(column_name="record_id", column_id="users:id"),
]

findings = classify_columns(columns, profile)
for f in findings:
    print(f"{f.column_id}: {f.entity_type} ({f.sensitivity}, confidence={f.confidence})")
```

## Features

- **Column name classification** — regex pattern matching against 15+ entity types
- **Sample value analysis** — scan actual column values for PII patterns (SSN, email, credit card, etc.)
- **Connector-agnostic** — works with BigQuery, Snowflake, Postgres, or any structured data source
- **Confidence + prevalence model** — confidence says "entity exists"; prevalence says "how much"
- **Hierarchical rollups** — aggregate findings from columns to tables to datasets
- **Event telemetry** — pluggable event emitter for observability
- **Extensible engine architecture** — add new classification engines without changing the orchestrator

## Architecture

```
ColumnInput → Orchestrator → [Engine Cascade] → ClassificationFinding
                                  ↓
                           Regex Engine (iteration 1)
                           Column Name (iteration 2)
                           Heuristics (iteration 2)
                           NER / GLiNER2 (iteration 2+)
```

## Specification

Full architectural specification: [`classification-library-docs/`](classification-library-docs/)

Client integration guide: [`docs/CLIENT_INTEGRATION_GUIDE.md`](docs/CLIENT_INTEGRATION_GUIDE.md)

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint + format
ruff check .
ruff format --check .
```

## License

MIT
