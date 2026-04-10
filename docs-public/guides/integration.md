# Integration Guide

> **Audience:** Connector teams (BigQuery, Snowflake, Postgres, etc.)

## What Is This Library?

`data_classifier` is a standalone, stateless Python library for detecting and classifying sensitive data in structured database columns.

**Key properties:**

- **Stateless** -- never connects to a database, never writes to disk
- **Connector-agnostic** -- knows nothing about BigQuery, Snowflake, or Postgres
- **The connector's job:** collect column metadata + sample values, pass to library, receive findings, persist results
- **The library's job:** run classification engines, return typed findings with confidence and evidence

## Migration from Embedded Classifier

### Before (embedded engine)

```python
from classifier.engine import classify_columns, compute_rollups, rollup_from_rollups
from classifier.runner import findings_to_dicts, load_profile, write_rollups

cls_profile = load_profile(classification_profile_name)
all_columns = [col for cols in context.columns.values() for col in cols]
findings = classify_columns(all_columns, cls_profile)
```

### After (with data_classifier)

```python
from data_classifier import (
    ColumnInput,
    ClassificationFinding,
    ClassificationProfile,
    RollupResult,
    classify_columns,
    compute_rollups,
    rollup_from_rollups,
    load_profile_from_yaml,
    load_profile_from_dict,
    SENSITIVITY_ORDER,
)

cls_profile = load_profile_from_yaml("standard", yaml_path)

inputs = [
    ColumnInput(
        column_name=col["name"],
        column_id=col["id"],
        data_type=col.get("type", ""),
        description=col.get("description", ""),
        sample_values=col.get("sample_values", []),
    )
    for col in all_columns
]

findings = classify_columns(inputs, cls_profile)

table_rollups = compute_rollups(findings, col_to_table)
dataset_rollups = rollup_from_rollups(table_rollups, table_to_dataset)
```

## Connector Responsibilities

### Column Metadata Collection

Collect column schema from the source and map to `ColumnInput`:

| Connector field | ColumnInput field | Notes |
|---|---|---|
| Column name | `column_name` | **Required.** |
| Unique identifier | `column_id` | Connector-defined format. Library echoes it back. |
| Table name | `table_name` | For context. |
| Schema/dataset | `dataset` | For context. |
| SQL data type | `data_type` | Normalize to generic types: `STRING`, `INTEGER`, `TIMESTAMP`, etc. |
| Column comment | `description` | Catalog description if available. |

### Sample Value Collection

The library accepts `sample_values` for content-based classification. This is where the major accuracy improvement comes from -- column name matching alone misses generically-named columns.

**What the connector must do:**

1. For each table being classified, sample N rows (recommended: 50-100)
2. For each column, collect the non-null values as strings
3. Pass them in `ColumnInput.sample_values`

**Sampling strategies by platform:**

| Platform | Recommended approach |
|---|---|
| **BigQuery** | `SELECT * FROM table TABLESAMPLE SYSTEM (N ROWS)` or `LIMIT N` with `ORDER BY RAND()` |
| **Snowflake** | `SELECT * FROM table SAMPLE (N ROWS)` |
| **Postgres** | `SELECT * FROM table TABLESAMPLE BERNOULLI (pct)` or `ORDER BY random() LIMIT N` |

**Constraints:**

- Coerce all values to strings before passing: `str(value)`
- Exclude nulls from the sample
- The library scans ALL provided values (no internal cap). Control volume through your sampling query
- If sampling is not available, omit `sample_values`. The library still classifies using column name and metadata

### Statistics Collection (optional)

If available, compute `ColumnStats` from the source:

| Platform | How to compute |
|---|---|
| **BigQuery** | `INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` + `APPROX_COUNT_DISTINCT()` |
| **Snowflake** | `SHOW COLUMNS` + `APPROX_COUNT_DISTINCT()` |
| **Postgres** | `pg_stats` view (null_frac, n_distinct, avg_width) |

### Profile Loading

The library ships a bundled `standard` profile via `load_profile("standard")`.

If your connector stores profiles in a database, implement your own wrapper:

```python
from data_classifier import load_profile_from_dict, load_profile as load_bundled_profile

def load_profile(profile_name: str) -> ClassificationProfile:
    """DB-first, bundled fallback."""
    db_profile = _try_load_from_db(profile_name)
    if db_profile is not None:
        return db_profile
    return load_bundled_profile(profile_name)
```

### Result Persistence

The library returns `ClassificationFinding` objects. The connector maps them to its own DB schema:

```python
def findings_to_db_rows(findings: list[ClassificationFinding]) -> list[dict]:
    return [
        {
            "column_node_id": f.column_id,
            "entity_type": f.entity_type,
            "category": f.category,
            "confidence": f.confidence,
            "engine": f.engine,
            "sensitivity": f.sensitivity,
            "regulatory": f.regulatory,
            "evidence": f.evidence,
            "match_ratio": (
                f.sample_analysis.match_ratio if f.sample_analysis else None
            ),
        }
        for f in findings
    ]
```

## Confidence Model

### What confidence means

`confidence` answers: "How sure are we that this entity type EXISTS in this column?"

It does NOT answer "what percentage of the column contains this type" -- that is `sample_analysis.match_ratio` (prevalence).

| Signal | confidence | prevalence |
|---|---|---|
| Column named `ssn`, 95/100 samples match | 0.99 | 0.95 |
| Column named `data`, 3/100 samples are SSNs | 0.81 | 0.03 |
| Column named `notes`, 1/100 samples is SSN | 0.59 | 0.01 |
| Column named `order_num`, 40/100 match format but fail validation | 0.0 | N/A |

### How to use prevalence

`sample_analysis.match_ratio` tells the connector how to act on a finding:

| Prevalence | Interpretation | Suggested action |
|---|---|---|
| > 0.8 | Column IS this type | Apply policy tag / column-level protection |
| 0.3 - 0.8 | Mixed content, significant PII | Flag for review, consider row-level scanning |
| 0.01 - 0.3 | Scattered PII (e.g., notes column) | Content-level redaction, DLP scanning |
| < 0.01 | Rare occurrences | Log for awareness |

## Testing Contract

The library ships with fixture-based tests ported from the BigQuery connector's test suite. These fixtures are the behavioral contract -- if the library passes these tests, the migration cannot regress.

```python
from data_classifier import classify_columns, ColumnInput, load_profile

profile = load_profile("standard")
inputs = [ColumnInput(column_name="email", column_id="t:email")]
findings = classify_columns(inputs, profile)
assert findings[0].entity_type == "EMAIL"
assert findings[0].sensitivity == "HIGH"
```
