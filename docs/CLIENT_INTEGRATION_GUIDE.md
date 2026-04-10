# data_classifier — Client Integration Guide

> **Audience:** Connector teams (BigQuery, Snowflake, Postgres, etc.)
> **Version:** 0.1.0 (Iteration 1 — API freeze draft)
> **Date:** 2026-04-10
> **Status:** DRAFT — review and confirm before implementation begins

---

## 1. What Is This Library?

`data_classifier` is a standalone, stateless Python library for detecting and classifying sensitive data in structured database columns. It replaces the `classifier/engine.py` module currently embedded in the BigQuery connector.

**Key properties:**

- **Stateless** — never connects to a database, never writes to disk
- **Connector-agnostic** — knows nothing about BigQuery, Snowflake, or Postgres
- **The connector's job:** collect column metadata + sample values → pass to library → receive findings → persist results
- **The library's job:** run classification engines → return typed findings with confidence and evidence

Install: `pip install data_classifier` (from GitHub release or local editable install for now)

---

## 2. What Changes for Connectors

### Before (current BigQuery connector)

```python
# connector.py — current
from classifier.engine import classify_columns, compute_rollups, rollup_from_rollups
from classifier.runner import findings_to_dicts, load_profile, write_rollups

cls_profile = load_profile(classification_profile_name)
all_columns = [col for cols in context.columns.values() for col in cols]
#              ↑ list[dict] with keys: id, name, type, mode, description, policy_tag, table
findings = classify_columns(all_columns, cls_profile)
```

### After (with data_classifier)

```python
# connector.py — after migration
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

# 1. Load profile (connector still owns DB-first fallback if desired)
cls_profile = load_profile_from_yaml("standard", yaml_path)

# 2. Convert connector's internal column dicts → library's ColumnInput
inputs = [
    ColumnInput(
        column_name=col["name"],
        column_id=col["id"],
        data_type=col.get("type", ""),
        description=col.get("description", ""),
        # NEW: pass sample values if collected (see Section 4)
        sample_values=col.get("sample_values", []),
    )
    for col in all_columns
]

# 3. Classify
findings = classify_columns(inputs, cls_profile)

# 4. Rollups — same API as before
table_rollups = compute_rollups(findings, col_to_table)
dataset_rollups = rollup_from_rollups(table_rollups, table_to_dataset)
```

**What stays in the connector** (not in the library):
- `load_profile()` with DB-first fallback — connector owns persistence
- `findings_to_dicts()` — connector owns DB schema mapping
- `write_rollups()` — connector owns DB writes
- Sample value collection — connector owns data access

---

## 3. Python API Reference (Frozen)

### Input Models

```python
from dataclasses import dataclass, field


@dataclass
class ColumnInput:
    """Everything the library needs to classify a single column.

    Only column_name is required. All other fields are optional and
    improve accuracy when provided. Engines use what they can,
    ignore what they don't need.
    """

    # ── Required ──────────────────────────────────────────
    column_name: str
    # The column name. Highest-signal input for classification.
    # Examples: "customer_ssn", "email_address", "data_field"

    # ── Identity (optional) ───────────────────────────────
    column_id: str = ""
    # Caller-defined unique identifier. Opaque to the library —
    # echoed back in ClassificationFinding.column_id.
    # BQ example:  "resource:table:proj.ds.tbl:col_name"
    # PG example:  "public.users.email"
    # Snowflake:   "DB.SCHEMA.TABLE.COL"

    # ── Context (optional metadata) ───────────────────────
    table_name: str = ""
    # Parent table name. Provides context for ambiguous column names.

    dataset: str = ""
    # Dataset, schema, or database name.

    data_type: str = ""
    # SQL data type as string: "STRING", "INTEGER", "TIMESTAMP", etc.
    # Not tied to any specific database's type system.

    description: str = ""
    # Column description/comment from the catalog.

    # ── Content (optional sample data) ────────────────────
    sample_values: list[str] = field(default_factory=list)
    # 10-100 sampled non-null values, coerced to strings by the connector.
    # Enables content-based engines (regex on values, NER, heuristics).
    # If empty, only metadata-based engines run (column name, data type).
    #
    # The library scans ALL provided values. Connector controls volume
    # via its own sampling strategy and the budget_ms parameter.

    # ── Statistics (optional) ─────────────────────────────
    stats: "ColumnStats | None" = None
    # Pre-computed column statistics. Connector computes these from the
    # source database; library uses them for heuristic classification.


@dataclass
class ColumnStats:
    """Column-level statistics computed by the connector."""
    null_pct: float = 0.0         # Null ratio 0.0-1.0
    distinct_count: int = 0       # Number of distinct non-null values
    total_count: int = 0          # Total row count
    min_length: int = 0           # Minimum string length (non-null values)
    max_length: int = 0           # Maximum string length
    avg_length: float = 0.0       # Average string length
```

### Output Models

```python
@dataclass
class SampleAnalysis:
    """How sample values contributed to a finding."""
    samples_scanned: int
    # Total values scanned for this column.

    samples_matched: int
    # How many matched this entity_type's pattern.

    samples_validated: int
    # How many passed secondary validation (Luhn checksum, format checks).

    match_ratio: float
    # matched / scanned. This is PREVALENCE — what fraction of the column
    # contains this entity type. NOT the same as confidence.
    # Use this to decide handling strategy:
    #   ratio ~1.0 → column IS this type (apply policy tag)
    #   ratio 0.01-0.3 → column CONTAINS some instances (flag for redaction)

    sample_matches: list[str] = field(default_factory=list)
    # First N matching values as evidence for audit.
    # Controlled by max_evidence_samples parameter.
    # When mask_samples=True, values are partially redacted:
    #   SSN:         "1**-**-6789"
    #   Credit card: "****-****-****-4321"
    #   Email:       "j***@acme.com"


@dataclass
class ClassificationFinding:
    """Result of classifying a single column."""

    # ── Identity ──────────────────────────────────────────
    column_id: str
    # Echoed from ColumnInput.column_id — opaque to the library.

    # ── Classification ────────────────────────────────────
    entity_type: str
    # Detected entity type: "SSN", "EMAIL", "CREDENTIAL", "CREDIT_CARD",
    # "PHONE", "DATE_OF_BIRTH", "PERSON_NAME", "ADDRESS", etc.

    sensitivity: str
    # Sensitivity level: "CRITICAL", "HIGH", "MEDIUM", "LOW"

    confidence: float
    # 0.0-1.0. Represents "how sure are we this entity type EXISTS
    # in this column?" — NOT scaled by prevalence.
    # 3 valid SSNs in 100 samples → high confidence (those are real SSNs).
    # See Section 5 for confidence model details.

    regulatory: list[str]
    # Applicable regulatory frameworks: ["PII", "HIPAA", "GDPR", "PCI_DSS", ...]

    # ── Provenance ────────────────────────────────────────
    engine: str
    # Which engine produced this finding: "regex", "column_name", "gliner2", etc.

    evidence: str = ""
    # Human-readable explanation:
    #   "Regex: US SSN format matched 87/100 samples (87%)"
    #   "Column name 'customer_ssn' matches SSN pattern"

    # ── Sample detail ─────────────────────────────────────
    sample_analysis: "SampleAnalysis | None" = None
    # Populated when finding was derived from sample value analysis.
    # None when finding was derived from column name/metadata only.


@dataclass
class ClassificationProfile:
    """A named set of classification rules."""
    name: str
    description: str
    rules: list["ClassificationRule"]


@dataclass
class ClassificationRule:
    """A single classification rule within a profile."""
    entity_type: str              # "SSN", "EMAIL", etc.
    sensitivity: str              # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    regulatory: list[str]         # ["PII", "HIPAA"]
    confidence: float             # Base confidence for this rule (0.0-1.0)
    patterns: list[str]           # Regex patterns


@dataclass
class RollupResult:
    """Aggregated classification summary for a parent node."""
    sensitivity: str              # Highest sensitivity from children
    classifications: list[str]    # Sorted unique entity types
    frameworks: list[str]         # Sorted unique regulatory frameworks
    findings_count: int           # Total findings count


SENSITIVITY_ORDER: dict[str, int] = {
    "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4,
}
```

### Functions

```python
def classify_columns(
    columns: list[ColumnInput],
    profile: ClassificationProfile,
    *,
    min_confidence: float = 0.5,
    # Findings below this threshold are not returned.
    # Default 0.5 filters noise while keeping moderate signals.
    # Lower (0.1) for maximum recall; raise (0.8) for precision.

    budget_ms: float | None = None,
    # Latency budget in milliseconds. None = no budget, full engine cascade.
    # When set, faster engines run first; slower engines skipped if budget
    # would be exceeded. Iteration 1: accepted but not enforced (single engine).

    run_id: str | None = None,
    # Associates findings with a run for telemetry event tagging.

    config: dict | None = None,
    # Per-request overrides: custom patterns, dictionaries, confidence thresholds.
    # Iteration 1: accepted but not used.

    mask_samples: bool = False,
    # When True, sample_matches in SampleAnalysis are partially redacted.
    # SSN "123-45-6789" → "1**-**-6789". Useful when findings are logged
    # or stored where PII should not appear in cleartext.

    max_evidence_samples: int = 5,
    # Maximum number of matching sample values to include in
    # SampleAnalysis.sample_matches.
) -> list[ClassificationFinding]:
    """Classify columns using the engine cascade.

    Returns one or more ClassificationFinding per column that has
    detectable sensitive data. Columns with no matches are omitted.
    A single column may have multiple findings (e.g., a "notes" column
    with both emails and phone numbers in its sample values).
    """
    ...


def load_profile_from_yaml(
    profile_name: str,
    yaml_path: str | Path,
) -> ClassificationProfile:
    """Load a named profile from a YAML file.

    Raises ValueError if profile_name not found in the YAML.
    Raises FileNotFoundError if yaml_path doesn't exist.
    """
    ...


def load_profile_from_dict(
    profile_name: str,
    data: dict,
) -> ClassificationProfile:
    """Load a named profile from an already-parsed dict.

    Raises ValueError if profile_name not found.
    """
    ...


def load_profile(
    profile_name: str = "standard",
) -> ClassificationProfile:
    """Load a profile from the library's bundled profiles.

    The library ships with a 'standard' profile. This function loads
    it from the package's bundled YAML — no file path needed.

    Connectors that store profiles in a database should implement their
    own load_profile() that tries DB first, then falls back to this.
    """
    ...


def compute_rollups(
    findings: list[ClassificationFinding],
    parent_map: dict[str, str],
) -> dict[str, RollupResult]:
    """Aggregate findings into parent-level rollups.

    Args:
        findings: Classification findings to aggregate.
        parent_map: Maps column_id → parent_id (e.g., column → table).
    """
    ...


def rollup_from_rollups(
    child_rollups: dict[str, RollupResult],
    parent_map: dict[str, str],
) -> dict[str, RollupResult]:
    """Aggregate child rollups into grandparent rollups (table → dataset)."""
    ...
```

---

## 4. Connector Responsibilities

The library is connector-agnostic. Each connector is responsible for:

### 4a. Column Metadata Collection

Collect column schema from the source and map to `ColumnInput`:

| Connector field | ColumnInput field | Notes |
|---|---|---|
| Column name | `column_name` | **Required.** |
| Unique identifier | `column_id` | Connector-defined format. Library echoes it back. |
| Table name | `table_name` | For context. |
| Schema/dataset | `dataset` | For context. |
| SQL data type | `data_type` | Normalize to generic types: "STRING", "INTEGER", "TIMESTAMP", etc. |
| Column comment | `description` | Catalog description if available. |

### 4b. Sample Value Collection (NEW — connector must implement)

The library now accepts `sample_values` for content-based classification. **This is where the major accuracy improvement comes from** — column name matching alone misses generically-named columns.

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

**Important constraints:**
- Coerce all values to strings before passing: `str(value)` — the library doesn't parse SQL types
- Exclude nulls from the sample — the library wants non-null values only
- The library scans ALL provided values (no internal cap). Control volume through your sampling query. Budget_ms also provides a timing escape hatch
- If sampling is not available or too expensive for a scan, omit `sample_values`. The library still classifies using column name and metadata — just with lower coverage

### 4c. Statistics Collection (optional, future)

If available, compute `ColumnStats` from the source:

| Platform | How to compute |
|---|---|
| **BigQuery** | `INFORMATION_SCHEMA.COLUMN_FIELD_PATHS` + `APPROX_COUNT_DISTINCT()` |
| **Snowflake** | `SHOW COLUMNS` + `APPROX_COUNT_DISTINCT()` |
| **Postgres** | `pg_stats` view (already has null_frac, n_distinct, avg_width) |

### 4d. Profile Loading

The library ships a bundled `standard` profile accessible via `load_profile("standard")`.

**If your connector stores profiles in a database**, implement your own wrapper:

```python
# In your connector (NOT in the library):
from data_classifier import load_profile_from_dict, load_profile as load_bundled_profile

def load_profile(profile_name: str) -> ClassificationProfile:
    """DB-first, bundled fallback."""
    db_profile = _try_load_from_db(profile_name)  # your DB logic
    if db_profile is not None:
        return db_profile
    return load_bundled_profile(profile_name)
```

### 4e. Result Persistence

The library returns `ClassificationFinding` objects. The connector maps them to its own DB schema:

```python
# In your connector (NOT in the library):
def findings_to_db_rows(findings: list[ClassificationFinding]) -> list[dict]:
    return [
        {
            "column_node_id": f.column_id,
            "entity_type": f.entity_type,
            "confidence": f.confidence,
            "engine": f.engine,
            "sensitivity": f.sensitivity,
            "regulatory": f.regulatory,
            "evidence": f.evidence,
            "match_ratio": f.sample_analysis.match_ratio if f.sample_analysis else None,
            "sample_value": None,  # or masked sample if desired
        }
        for f in findings
    ]
```

---

## 5. Confidence Model

### What confidence means

`confidence` answers: **"How sure are we that this entity type EXISTS in this column?"**

It does NOT answer "what percentage of the column contains this type" — that's `sample_analysis.match_ratio` (prevalence).

| Signal | confidence | prevalence |
|---|---|---|
| Column named `ssn`, 95/100 samples match | 0.99 | 0.95 |
| Column named `data`, 3/100 samples are SSNs | 0.81 | 0.03 |
| Column named `notes`, 1/100 samples is SSN | 0.59 | 0.01 |
| Column named `order_num`, 40/100 match SSN format but fail validation | 0.0 | N/A (discarded) |

### How confidence is computed

**Column name match:**
Uses the base confidence from the profile rule (e.g., SSN rule = 0.95).

**Sample value match:**
Base confidence adjusted by match count (not ratio):

| Matches | Adjustment | Rationale |
|---|---|---|
| 0 | 0.0 (no finding) | Nothing to report |
| 1 | base * 0.65 | Single match could be noise |
| 2-4 | base * 0.85 | Probably real |
| 5-20 | base * 1.0 | Solid evidence |
| 20+ | min(base * 1.05, 1.0) | Abundant evidence |

Validation failures reduce confidence: if only 50% of matches pass secondary validation (Luhn, format check), confidence is halved.

### Minimum threshold

`classify_columns()` accepts `min_confidence` (default: 0.5). Findings below this are not returned. Connectors can adjust:
- `min_confidence=0.3` — high recall, more noise (audit/discovery mode)
- `min_confidence=0.7` — high precision, fewer findings (production tagging)

### How to use prevalence

`sample_analysis.match_ratio` tells the connector how to **act** on a finding:

| Prevalence | Interpretation | Suggested action |
|---|---|---|
| > 0.8 | Column IS this type | Apply policy tag / column-level protection |
| 0.3 - 0.8 | Mixed content, significant PII presence | Flag for review, consider row-level scanning |
| 0.01 - 0.3 | Scattered PII (e.g., notes/comments column) | Content-level redaction, DLP scanning |
| < 0.01 | Rare occurrences | Log for awareness, likely no column-level action |

---

## 6. Migration Plan for BigQuery Connector

### Scope

This replaces `classifier/engine.py` with the `data_classifier` package. `classifier/runner.py` stays in the BQ connector — it handles DB-specific concerns.

### Step-by-step

**1. Add dependency**
```toml
# pyproject.toml
dependencies = [
    "data_classifier>=0.1.0",
    # ... existing deps
]
```

**2. Update runner.py imports**
```python
# BEFORE
from classifier.engine import (
    SENSITIVITY_ORDER,
    ClassificationFinding,
    ClassificationProfile,
    ClassificationRule,
    RollupResult,
    classify_columns,
    compute_rollups,
    load_profile_from_dict,
    load_profile_from_yaml,
    rollup_from_rollups,
)

# AFTER
from data_classifier import (
    SENSITIVITY_ORDER,
    ClassificationFinding,
    ClassificationProfile,
    ClassificationRule,
    ColumnInput,           # NEW
    RollupResult,
    classify_columns,
    compute_rollups,
    load_profile_from_dict,
    load_profile_from_yaml,
    rollup_from_rollups,
)
```

**3. Update connector.py classification call**
```python
# BEFORE
from classifier.engine import classify_columns, compute_rollups, rollup_from_rollups
from classifier.runner import findings_to_dicts, load_profile, write_rollups

all_columns = [col for cols in context.columns.values() for col in cols]
findings = classify_columns(all_columns, cls_profile)

# AFTER
from data_classifier import classify_columns, compute_rollups, rollup_from_rollups, ColumnInput
from classifier.runner import findings_to_dicts, load_profile, write_rollups

all_columns = [col for cols in context.columns.values() for col in cols]
inputs = [
    ColumnInput(
        column_name=col["name"],
        column_id=col["id"],
        data_type=col.get("type", ""),
        description=col.get("description", ""),
        sample_values=col.get("sample_values", []),  # when sampling is implemented
    )
    for col in all_columns
]
findings = classify_columns(inputs, cls_profile)
```

**4. Update test imports**
```python
# tests/test_classification_runner.py, test_connector_classification.py
# BEFORE: from classifier.engine import ...
# AFTER:  from data_classifier import ...
```

**5. Delete classifier/engine.py**
The engine logic now lives in `data_classifier`. Keep `classifier/runner.py` — it's the DB integration layer.

**6. (Optional) Add sample collection**
Implement `TABLESAMPLE` in the BQ collector to populate `sample_values` on column dicts. This is independent of the library migration and can be done before or after.

### What does NOT change
- `classifier/runner.py` — stays, still owns DB profile loading + persistence
- `findings_to_dicts()` — stays, maps findings to BQ connector's DB schema
- `write_rollups()` — stays, writes to `classification_rollups` table
- Rollup logic (`compute_rollups`, `rollup_from_rollups`) — same API, just imported from new package
- Profile YAML format — identical, backward compatible

---

## 7. Testing Contract

The library ships with fixture-based tests ported from the BigQuery connector's test suite. These fixtures are the behavioral contract:

- Every test input (columns + profile) from `test_classification_runner.py` is a fixture
- Every expected output (findings, rollups) is a golden-set fixture
- If the library passes these tests, the migration cannot regress

**After migration, the BQ connector should also run:**
```python
# Verify that data_classifier produces identical results
from data_classifier import classify_columns, ColumnInput, load_profile

profile = load_profile("standard")
inputs = [ColumnInput(column_name="email", column_id="t:email")]
findings = classify_columns(inputs, profile)
assert findings[0].entity_type == "EMAIL"
assert findings[0].sensitivity == "HIGH"
```

---

## 8. Timeline

| Milestone | Owner | Target |
|---|---|---|
| Library iteration 1 complete (Python API + tests + CI) | data_classifier team | Current sprint |
| BQ connector sampling implementation | BQ connector team | Can start now (independent) |
| BQ connector migration to data_classifier | BQ connector team | Sprint 27 |
| Library iteration 2 (heuristics, NER engines) | data_classifier team | Sprint 28+ |

---

## 9. Questions / Open Items

1. **Sampling configuration in BQ connector** — what sample size? Configurable per-profile or global? Suggested default: 100 rows per table.

2. **Profile YAML storage** — does the BQ connector want to continue storing profiles in the config DB table, or switch to bundled YAML from the library? The library supports both patterns.

3. **New DB columns** — the `classification_findings` table may want new columns for `evidence` (text) and `match_ratio` (float). Plan the migration.

4. **Confidence threshold** — the library defaults to `min_confidence=0.5`. Does the BQ connector want to use a different default, or make it configurable via `enrichment_config`?

---

## Appendix A: Full Public API Surface

Everything exported from `data_classifier.__init__`:

```python
# Types
ColumnInput
ColumnStats
ClassificationFinding
SampleAnalysis
ClassificationProfile
ClassificationRule
RollupResult

# Functions
classify_columns(columns, profile, *, min_confidence, budget_ms, run_id, config, mask_samples, max_evidence_samples)
load_profile(profile_name)
load_profile_from_yaml(profile_name, yaml_path)
load_profile_from_dict(profile_name, data)
compute_rollups(findings, parent_map)
rollup_from_rollups(child_rollups, parent_map)

# Constants
SENSITIVITY_ORDER
```
