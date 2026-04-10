# Migration Plan: BigQuery Connector → data_classifier

> Sprint 27 migration guide. Purely mechanical import rename.
> Generated: 2026-04-10

## Summary

Replace `classifier/engine.py` in BigQuery-connector with the `data_classifier` package.
`classifier/runner.py` stays — it owns DB integration (load_profile_from_db, findings_to_dicts, write_rollups).

**Migration type:** Import rename + `ColumnInput` wrapping. No behavioral change. No new deployment target.

---

## Consumer Inventory

### 1. classifier/runner.py (DB integration layer)

**Current imports (line 15-26):**
```python
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
```

**Sprint 27 change:**
```python
from data_classifier import (
    SENSITIVITY_ORDER,
    ClassificationFinding,
    ClassificationProfile,
    ClassificationRule,
    ColumnInput,              # NEW
    RollupResult,
    classify_columns,
    compute_rollups,
    load_profile_from_dict,
    load_profile_from_yaml,
    rollup_from_rollups,
)
```

**What stays in runner.py** (NOT migrated):
- `load_profile()` — DB-first fallback, calls `load_profile_from_db()` then `load_profile_from_yaml()`
- `load_profile_from_db()` — reads from config table
- `findings_to_dicts()` — maps ClassificationFinding to DB row format
- `write_rollups()` — writes to classification_rollups table

**Additional change in runner.py:** `findings_to_dicts()` should add the `category` field:
```python
def findings_to_dicts(findings: list[ClassificationFinding]) -> list[dict]:
    return [
        {
            "column_node_id": f.column_id,
            "entity_type": f.entity_type,
            "category": f.category,           # NEW
            "confidence": f.confidence,
            "engine": f.engine,
            "sensitivity": f.sensitivity,
            "regulatory": f.regulatory,
            "evidence": f.evidence,            # NEW
            "sample_value": None,
        }
        for f in findings
    ]
```

### 2. connectors/bigquery/connector.py (main consumer, lines 327-377)

**Current imports (lines 327-328):**
```python
from classifier.engine import classify_columns, compute_rollups, rollup_from_rollups
from classifier.runner import findings_to_dicts, load_profile, write_rollups
```

**Current usage (lines 331-332):**
```python
all_columns = [col for cols in context.columns.values() for col in cols]
findings = classify_columns(all_columns, cls_profile)
```

**Sprint 27 change:**
```python
from data_classifier import classify_columns, compute_rollups, rollup_from_rollups, ColumnInput
from classifier.runner import findings_to_dicts, load_profile, write_rollups

# ... existing code ...

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

**Rollup code (lines 342-367):** No change needed. `compute_rollups()` and `rollup_from_rollups()` have identical signatures.

### 3. tests/test_classification_runner.py (365 lines)

**Current imports (lines 15-30):**
```python
from classifier.engine import (
    SENSITIVITY_ORDER, ClassificationFinding, ClassificationProfile,
    ClassificationRule, RollupResult, classify_columns, compute_rollups,
    load_profile_from_yaml, rollup_from_rollups,
)
from classifier.runner import (findings_to_dicts, load_profile, write_rollups)
```

**Sprint 27 change:**
```python
from data_classifier import (
    SENSITIVITY_ORDER, ClassificationFinding, ClassificationProfile,
    ClassificationRule, ColumnInput, RollupResult, classify_columns,
    compute_rollups, load_profile_from_yaml, rollup_from_rollups,
)
from classifier.runner import (findings_to_dicts, load_profile, write_rollups)
```

**Test body changes:** The `_col()` helper method returns a dict. Tests that call `classify_columns()` need to wrap dicts as `ColumnInput`:
```python
# BEFORE
def _col(self, name, col_id=None):
    return {"id": col_id or f"resource:table:proj.ds.tbl:{name}", "name": name, "type": "STRING"}

findings = classify_columns([self._col("email")], profile)

# AFTER
def _col(self, name, col_id=None):
    return ColumnInput(
        column_name=name,
        column_id=col_id or f"resource:table:proj.ds.tbl:{name}",
        data_type="STRING",
    )

findings = classify_columns([self._col("email")], profile, min_confidence=0.0)
```

**Note:** `min_confidence=0.0` is needed because the new library defaults to 0.5. BQ connector tests expect all matches regardless of confidence.

**ClassificationFinding construction in rollup tests:** The new `ClassificationFinding` has `category` as a required field:
```python
# BEFORE
ClassificationFinding("table1:email", "EMAIL", "HIGH", 0.9, ["PII"], "engine")

# AFTER
ClassificationFinding("table1:email", "EMAIL", "PII", "HIGH", 0.9, ["PII"], "engine")
#                                              ^^^^^ category added
```

### 4. tests/test_connector_classification.py (170 lines)

**Current imports (line 8):**
```python
from classifier.engine import ClassificationFinding
```

**Sprint 27 change:**
```python
from data_classifier import ClassificationFinding
```

**Test body:** `_mock_findings()` constructs `ClassificationFinding` directly — add `category` field.

### 5. tests/test_classifications_api.py (71 lines)

**No changes needed.** This tests the HTTP API endpoint, not the classifier directly. The API route imports from `classifier.runner`, not `classifier.engine`.

---

## API Differences Summary

| Symbol | Old (classifier.engine) | New (data_classifier) | Change |
|---|---|---|---|
| `classify_columns()` | `list[dict]` input | `list[ColumnInput]` input | Wrap dicts |
| `classify_columns()` | No min_confidence | Default `min_confidence=0.5` | Add `min_confidence=0.0` for BQ compat |
| `ClassificationFinding` | 6 positional fields | 7 fields (added `category`) | Add category |
| `ClassificationFinding` | `.engine = "classification_profile:standard"` | `.engine = "regex"` | Engine name changed |
| `compute_rollups()` | Same | Same | No change |
| `rollup_from_rollups()` | Same | Same | No change |
| `load_profile_from_yaml()` | Same | Same | No change |
| `load_profile_from_dict()` | Same | Same | No change |
| `SENSITIVITY_ORDER` | Same | Same | No change |
| `ClassificationProfile` | Same | Same (added `category` on rules) | Minor |
| `ClassificationRule` | 5 fields | 6 fields (added `category`) | Profile YAML needs `category` |

## Gap Analysis

| Consumer Need | data_classifier Provides? | Notes |
|---|---|---|
| `classify_columns(list[dict], profile)` | `classify_columns(list[ColumnInput], profile)` | Wrap dicts as ColumnInput |
| `compute_rollups(findings, parent_map)` | Yes, identical | No change |
| `rollup_from_rollups(rollups, parent_map)` | Yes, identical | No change |
| `load_profile_from_yaml(name, path)` | Yes, identical | No change |
| `load_profile_from_dict(name, data)` | Yes, identical | No change |
| `SENSITIVITY_ORDER` | Yes, identical | No change |
| All type exports | Yes + ColumnInput, SampleAnalysis, ColumnStats | Additional types |

**No gaps.** Every current BQ connector consumer maps to the new API without regression.

---

## Migration Steps (Sprint 27)

1. **Add dependency:** `pip install data_classifier` (or `data_classifier @ git+https://github.com/zbarbur/data-classifier.git`)
2. **Update profile YAML:** Add `category` field to each rule in `classification_profiles.yaml`
3. **Update runner.py:** Change import from `classifier.engine` to `data_classifier`
4. **Update connector.py:** Change import + wrap column dicts as `ColumnInput`
5. **Update test imports:** `from classifier.engine` → `from data_classifier`
6. **Update test helpers:** `_col()` returns `ColumnInput`, add `min_confidence=0.0`, add `category` to `ClassificationFinding` constructors
7. **DB migration:** Add `category TEXT` column to `classification_findings` table
8. **Delete:** `classifier/engine.py` (keep `classifier/runner.py`)
9. **Run tests:** All existing tests should pass unchanged (same behavior)

**Estimated effort:** 1-2 hours mechanical work. No design decisions.

---

## Verification

After migration, this should work:
```python
from data_classifier import classify_columns, load_profile, ColumnInput

profile = load_profile("standard")
inputs = [ColumnInput(column_name="email", column_id="test:email")]
findings = classify_columns(inputs, profile, min_confidence=0.0)
assert findings[0].entity_type == "EMAIL"
assert findings[0].category == "PII"
assert findings[0].sensitivity == "HIGH"
```
