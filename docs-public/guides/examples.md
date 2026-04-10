# Examples

Code recipes for common classification tasks.

## Classify a Single Column

```python
from data_classifier import classify_columns, load_profile, ColumnInput

profile = load_profile("standard")

column = ColumnInput(
    column_name="ssn",
    column_id="customers.ssn",
    data_type="STRING",
    sample_values=["123-45-6789", "987-65-4321", "555-12-3456"],
)

findings = classify_columns([column], profile)
for f in findings:
    print(f"  {f.entity_type}: confidence={f.confidence:.2f}, sensitivity={f.sensitivity}")
    if f.sample_analysis:
        print(f"  Prevalence: {f.sample_analysis.match_ratio:.0%}")
```

## Classify Multiple Columns

```python
from data_classifier import classify_columns, load_profile, ColumnInput

profile = load_profile("standard")

columns = [
    ColumnInput(
        column_name="email",
        column_id="users.email",
        sample_values=["alice@example.com", "bob@company.org"],
    ),
    ColumnInput(
        column_name="phone_number",
        column_id="users.phone",
        sample_values=["(555) 123-4567", "212-555-0199"],
    ),
    ColumnInput(
        column_name="notes",
        column_id="users.notes",
        sample_values=["Great customer", "Call at 555-1234", "Prefers email"],
    ),
]

findings = classify_columns(columns, profile)
for f in findings:
    print(f"{f.column_id}: {f.entity_type} ({f.confidence:.0%})")
```

## Filter by Category

Only detect PII, skip Financial/Credential/Health:

```python
findings = classify_columns(
    columns,
    profile,
    categories=["PII"],
)
```

Only detect Financial and Credential data:

```python
findings = classify_columns(
    columns,
    profile,
    categories=["Financial", "Credential"],
)
```

## Use Custom Profiles from YAML

Create a YAML file with your profile definition:

```yaml
# my_profiles.yaml
profiles:
  pii_only:
    description: "Only detect PII entity types"
    rules:
      - entity_type: EMAIL
        category: PII
        sensitivity: HIGH
        regulatory: [PII, GDPR]
        confidence: 0.9
        patterns: [email]
      - entity_type: SSN
        category: PII
        sensitivity: CRITICAL
        regulatory: [PII]
        confidence: 0.95
        patterns: [ssn]
```

Load and use:

```python
from data_classifier import classify_columns, load_profile_from_yaml, ColumnInput

profile = load_profile_from_yaml("pii_only", "my_profiles.yaml")

columns = [
    ColumnInput(
        column_name="data_field",
        column_id="t.data",
        sample_values=["123-45-6789", "not-an-ssn", "987-65-4321"],
    )
]

findings = classify_columns(columns, profile)
```

## Compute Table-Level Rollups

Aggregate column findings to table and dataset levels:

```python
from data_classifier import (
    classify_columns,
    compute_rollups,
    rollup_from_rollups,
    load_profile,
    ColumnInput,
)

profile = load_profile("standard")

columns = [
    ColumnInput(column_name="email", column_id="users.email",
                sample_values=["a@b.com"]),
    ColumnInput(column_name="ssn", column_id="users.ssn",
                sample_values=["123-45-6789"]),
    ColumnInput(column_name="cc_number", column_id="orders.cc",
                sample_values=["4111111111111111"]),
]

findings = classify_columns(columns, profile)

# Column -> Table mapping
col_to_table = {
    "users.email": "users",
    "users.ssn": "users",
    "orders.cc": "orders",
}

table_rollups = compute_rollups(findings, col_to_table)
for table_id, rollup in table_rollups.items():
    print(f"{table_id}:")
    print(f"  Sensitivity: {rollup.sensitivity}")
    print(f"  Types: {rollup.classifications}")
    print(f"  Frameworks: {rollup.frameworks}")
    print(f"  Findings: {rollup.findings_count}")

# Table -> Dataset mapping
table_to_dataset = {"users": "prod_db", "orders": "prod_db"}
dataset_rollups = rollup_from_rollups(table_rollups, table_to_dataset)
for ds_id, rollup in dataset_rollups.items():
    print(f"\nDataset {ds_id}: {rollup.sensitivity}, {rollup.findings_count} findings")
```

## Use Event Telemetry

Capture classification events for monitoring:

```python
from data_classifier import classify_columns, load_profile, ColumnInput
from data_classifier.events.emitter import EventEmitter, CallbackHandler
from data_classifier.events.types import TierEvent, ClassificationEvent

profile = load_profile("standard")
columns = [
    ColumnInput(column_name="email", column_id="t.email",
                sample_values=["a@b.com", "c@d.org"]),
]

# Collect events
events = []
emitter = EventEmitter()
emitter.add_handler(CallbackHandler(lambda e: events.append(e)))

findings = classify_columns(columns, profile, event_emitter=emitter)

# Inspect events
for event in events:
    if isinstance(event, TierEvent):
        print(f"Engine '{event.tier}': {event.outcome} in {event.latency_ms:.1f}ms")
    elif isinstance(event, ClassificationEvent):
        print(f"Column '{event.column_id}': {event.total_findings} findings, "
              f"{event.total_ms:.1f}ms total")
```

## Mask Sample Evidence

Redact sensitive values in finding evidence:

```python
findings = classify_columns(
    columns,
    profile,
    mask_samples=True,
    max_evidence_samples=3,
)

for f in findings:
    if f.sample_analysis and f.sample_analysis.sample_matches:
        print(f"{f.entity_type} matches (masked): {f.sample_analysis.sample_matches}")
        # e.g. ["1**-**-6789", "9**-**-4321"]
```

## Introspect the Library

Discover what the library can detect at runtime:

```python
from data_classifier import (
    get_supported_categories,
    get_supported_entity_types,
    get_supported_sensitivity_levels,
    get_pattern_library,
)

# List categories
print("Categories:", get_supported_categories())

# List entity types with metadata
for et in get_supported_entity_types():
    print(f"  {et['entity_type']}: {et['category']} / {et['sensitivity']}")

# List sensitivity levels in order
print("Sensitivity levels:", get_supported_sensitivity_levels())

# List all content patterns
patterns = get_pattern_library()
print(f"{len(patterns)} content patterns available")
```
