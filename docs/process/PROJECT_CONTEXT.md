# data_classifier — Project Context

> **Last updated:** 2026-04-10 (Sprint 1 bootstrap)

## Status

| Metric | Value |
|---|---|
| Current sprint | 1 (bootstrap) |
| Tests passing | 0 (skeleton phase) |
| CI | Not yet configured |
| Package installable | Pending verification |

## Architecture Summary

**data_classifier** is a standalone, stateless Python library for classifying sensitive data in structured database columns.

- **Input:** `ColumnInput` (column name + optional sample values + optional stats)
- **Processing:** Engine cascade (orchestrator selects engines by mode + profile)
- **Output:** `ClassificationFinding` (entity type, sensitivity, confidence, evidence, sample analysis)
- **Rollups:** Aggregate findings to parent level (column→table→dataset)

### Engine Stack (Iteration 1)
- **Regex engine** — column name pattern matching + sample value scanning
- Future: column name semantics, heuristics, NER, GLiNER2, embeddings, SLM, LLM

### Key Design Decisions
- Dataclasses for library types (not Pydantic)
- Confidence = "entity exists in column" (not prevalence)
- Prevalence = `SampleAnalysis.match_ratio` (separate from confidence)
- Library scans ALL provided samples; caller controls volume
- Events + telemetry from day 1
- Full engine base class even though only regex is implemented

## Consumers
- BigQuery connector (Sprint 27 migration planned)
- Snowflake connector (future)
- Postgres connector (future)

## Client Integration Guide
`docs/CLIENT_INTEGRATION_GUIDE.md` — shared with BQ team on 2026-04-10

## Specification Documents
`classification-library-docs/` — full spec. Relevant for iteration 1:
- `01-architecture.md` — system architecture
- `02-api-reference.md` — HTTP API (secondary)
- `04-engines.md` — engine interface
- `05-pipelines.md` — pipeline cascade logic
