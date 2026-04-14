# BQ Connector Integration Status — `ColumnInput` Context Fields

> **Purpose:** Source of truth for which `ColumnInput` context fields the BigQuery connector actually populates in production. Supports library-side items (e.g., `gliner-data-type-pre-filter`) that assume these fields are present.
>
> **Scope:** This doc covers only the five context fields on `ColumnInput` — `table_name`, `dataset`, `schema_name`, `data_type`, `description`. Other ColumnInput fields (`column_name`, `sample_values`, `column_id`) have been populated since Sprint 1 and are not in scope here.

## Current status — as of 2026-04-14 (Sprint 10 start)

| Field | Populated by BQ? | Source | Format / notes |
|---|---|---|---|
| `table_name` | **Yes** | BQ table metadata | Plain string, e.g. `"orders"`. No project/dataset prefix — that goes in `dataset`. |
| `dataset` | **Yes** | BQ dataset | Plain string, e.g. `"analytics_prod"`. |
| `schema_name` | **Yes (as empty string)** | N/A — BQ has no schema layer | Empty string `""`. BQ's addressing model is `project.dataset.table`, so there is no schema level to populate. Library code should treat `""` as "not applicable" rather than "missing." |
| `data_type` | **Yes** | BQ column type | BigQuery-style constants: `"STRING"`, `"INTEGER"`, `"INT64"`, `"FLOAT"`, `"FLOAT64"`, `"NUMERIC"`, `"BIGNUMERIC"`, `"BOOLEAN"`, `"BOOL"`, `"TIMESTAMP"`, `"DATE"`, `"DATETIME"`, `"TIME"`, `"BYTES"`. Uppercase, unquoted. |
| `description` | **Yes** | BQ column description catalog | Plain string. May be empty `""` for columns with no catalog description — library should handle both cases. |

## Verification method

**Verbal confirmation on 2026-04-13** from the BQ connector team during Sprint 9 kickoff, recorded at the time in the project memory entry `project_bq_context_fields_populated.md`. This written verification is the Sprint 10 follow-up that captures that confirmation in repo for durability across sessions and auditability for future reviews.

- **Level:** direct attestation from the BQ connector integration owner about the `v0.8.0` deployed state
- **Not verified in this doc:** live BQ traffic packet capture, BQ connector source-code review, staging-environment log grep
- **Project-appropriate confidence level:** sufficient for library-side items that assume these fields are present. Any library-side item that would fail catastrophically if a field is missing must add its own defensive fallback (see "Known gaps" below — there are none at this writing, but the discipline stands).

## Known gaps

None as of 2026-04-14. All five context fields are populated in `v0.8.0` per the verbal confirmation.

If a gap is discovered (e.g., library-side debug surfaces that BQ passes an unexpected field format or null where a string is expected), file it as a bug against the BQ connector and add a row to a "Known issues" section here, then update the Sprint 10 (or later) library-side items that depended on that field with a defensive fallback.

## Library-side consumption of these fields

As of the start of Sprint 10, consumption is **shallow** — most fields are passed through but not used:

| Field | Library consumer | Status |
|---|---|---|
| `table_name` | `column_name_engine.py::_table_context_boost` (lines ~185-200) | 45 hardcoded English keywords → `{PII, Health, Financial}` category boost. Flat `+0.05` confidence when the match category aligns with a nearby column-name match. Only invoked from within `ColumnNameEngine.classify_column`. Cannot create findings, only nudges existing ones across thresholds. |
| `dataset` | **None** | Passed through but unread. `CLIENT_INTEGRATION_GUIDE.md` documents this explicitly. |
| `schema_name` | **None** | Same — unread. |
| `data_type` | **Sprint 10 item** `gliner-data-type-pre-filter-skip-ml-on-numeric-temporal-boolean-columns` | First library-side consumer. Skips GLiNER2 ML inference on non-text `data_type` values (INTEGER, FLOAT, BOOLEAN, TIMESTAMP, DATE, BYTES, etc.) to eliminate a whole class of false positives on numeric columns. Ships in Sprint 10. |
| `description` | **None** | Currently unread. Likely the highest-signal wasted input (catalog descriptions are often classification-ready English prose). Future sprints should explore consumption via LLM fallback or description-pattern matching. |

## Field format contract for library code

Based on the verbal confirmation, library consumers can rely on these invariants for the BQ integration path:

1. **All five fields are strings.** Never `None`. Empty string `""` is a valid "not populated / not applicable" signal. Library code should `field == ""` rather than `field is None`.
2. **`data_type` is UPPERCASE** in BQ convention. Library code that compares against a vocabulary should either normalize with `.upper()` or keep the comparison set in uppercase.
3. **`schema_name` is always `""`** for BQ. Other connectors (Snowflake, Postgres) may populate it in the future; library code should not treat a non-empty `schema_name` as an error.
4. **`description` may be any length**, including empty. Library code that uses descriptions for classification signal should handle empty-description columns gracefully — do not gate behavior on description presence unless the code explicitly requires it.

## Cross-references

- **Memory entry:** `project_bq_context_fields_populated.md` (user memory, 2026-04-13) — the original verbal confirmation record
- **Memory entry:** `project_bq_coordination.md` (user memory) — broader context on which engines consume which fields, and where the shallow-consumption gap matters
- **`ColumnInput` definition:** `data_classifier/core/types.py:54-95` — field declarations with defaults
- **Client guide:** `docs/CLIENT_INTEGRATION_GUIDE.md` §1b — recipe for connector teams to populate these fields
- **Library consumer (current):** `data_classifier/engines/column_name_engine.py:185-200` — `_table_context_boost`
- **Library consumer (Sprint 10):** `data_classifier/engines/gliner_engine.py` (item `gliner-data-type-pre-filter` in progress)

## Update cadence

Update this doc when **any** of the following happens:

1. The BQ connector team announces a change to which fields are populated (a deprecation, a new field, a format change).
2. A library-side item ships that newly consumes one of the fields (e.g., when `description` gets its first consumer).
3. A bug is found that reveals a discrepancy between this doc and BQ's actual behavior.
4. A new field is added to `ColumnInput` that BQ needs to populate.

This doc is deliberately short and field-focused. Deeper BQ integration architecture lives in `docs/migration-from-bq-connector.md`.
