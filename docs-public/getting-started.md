# Getting Started

## Installation

Install from PyPI (or a local editable install for development):

```bash
pip install data_classifier
```

For development:
```bash
pip install -e ".[dev]"
```

## Basic Classification

The core workflow: load a profile, build column inputs, classify.

```python
from data_classifier import classify_columns, load_profile, ColumnInput

# 1. Load the bundled standard profile
profile = load_profile("standard")

# 2. Describe columns to classify
columns = [
    ColumnInput(
        column_name="email_address",
        column_id="users.email",
        data_type="STRING",
        sample_values=["alice@example.com", "bob@company.org"],
    ),
    ColumnInput(
        column_name="phone",
        column_id="users.phone",
        data_type="STRING",
        sample_values=["(555) 123-4567", "212-555-0199"],
    ),
]

# 3. Classify
findings = classify_columns(columns, profile)

for f in findings:
    print(f"{f.column_id}: {f.entity_type} (confidence={f.confidence:.2f})")
```

## Loading Profiles

The library ships with a `standard` profile. You can also load from YAML or from a dict:

=== "Bundled profile"

    ```python
    from data_classifier import load_profile

    profile = load_profile("standard")
    ```

=== "From YAML file"

    ```python
    from data_classifier import load_profile_from_yaml

    profile = load_profile_from_yaml("custom", "/path/to/profiles.yaml")
    ```

=== "From dict"

    ```python
    from data_classifier import load_profile_from_dict

    data = {
        "profiles": {
            "minimal": {
                "description": "Only detect emails",
                "rules": [
                    {
                        "entity_type": "EMAIL",
                        "category": "PII",
                        "sensitivity": "HIGH",
                        "regulatory": ["PII", "GDPR"],
                        "confidence": 0.9,
                        "patterns": ["email"],
                    }
                ],
            }
        }
    }
    profile = load_profile_from_dict("minimal", data)
    ```

## Category Filtering

Restrict classification to specific data categories:

```python
# Only detect PII and Credentials, skip Financial and Health
findings = classify_columns(
    columns,
    profile,
    categories=["PII", "Credential"],
)
```

Valid categories: `PII`, `Financial`, `Credential`, `Health`.

## Confidence Thresholds

Control the precision/recall tradeoff with `min_confidence`:

```python
# High recall -- more findings, more noise
findings = classify_columns(columns, profile, min_confidence=0.3)

# High precision -- fewer findings, less noise
findings = classify_columns(columns, profile, min_confidence=0.8)
```

The default is `0.5`.

## Computing Rollups

Aggregate column-level findings to table and dataset levels:

```python
from data_classifier import compute_rollups, rollup_from_rollups

# Map column IDs to table IDs
col_to_table = {
    "users.email": "users",
    "users.phone": "users",
    "orders.cc": "orders",
}

# Table-level rollups
table_rollups = compute_rollups(findings, col_to_table)
for table_id, rollup in table_rollups.items():
    print(f"{table_id}: {rollup.sensitivity}, {rollup.classifications}")

# Dataset-level rollups
table_to_dataset = {"users": "main_db", "orders": "main_db"}
dataset_rollups = rollup_from_rollups(table_rollups, table_to_dataset)
```

## Event Telemetry

Monitor classification with pluggable event handlers:

```python
from data_classifier import classify_columns
from data_classifier.events.emitter import EventEmitter, LogHandler, CallbackHandler

# Option 1: Log events via Python logging
emitter = EventEmitter()
emitter.add_handler(LogHandler())

findings = classify_columns(columns, profile, event_emitter=emitter)

# Option 2: Custom callback
events_collected = []

emitter = EventEmitter()
emitter.add_handler(CallbackHandler(lambda e: events_collected.append(e)))

findings = classify_columns(columns, profile, event_emitter=emitter)
print(f"Collected {len(events_collected)} events")
```

Events emitted:

- **TierEvent** -- after each engine runs on a column (tier, latency, outcome)
- **ClassificationEvent** -- after all engines complete for a column
