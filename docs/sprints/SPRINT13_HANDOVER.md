# Sprint 13 Handover — data_classifier

> **Theme:** Column-shape router + per-value GLiNER union
> **Dates:** 2026-04-16 → 2026-04-17 (ongoing)
> **Branch:** `sprint13/main`
> **Test count:** 1532 → **1631** (+99 net-new, passing)

---

## Item A — Column-Shape Router (complete, phase=review)

Heuristic gate routes each column to one of three branches based on
post-merge content signals: `structured_single` (77% of benchmark
corpus), `free_text_heterogeneous` (11%), `opaque_tokens` (12%).

v5 meta-classifier shadow is suppressed on the heterogeneous and opaque
branches. Safety audit Q3: 6/6 `router_deflected` (was 6/6 RED in
Sprint 12).

Key numbers:
- `shadow.cross_family_rate_emitted`: 0.0001 (was 0.0044 in Sprint 12)
- `shadow.family_macro_f1_emitted`: 0.9999
- `router_suppression_rate`: 0.2305

## Item B — Per-Value GLiNER Aggregation, Union Design (complete, phase=review)

### Architectural change

On `free_text_heterogeneous` columns, the orchestrator now runs
`GLiNER2Engine.classify_per_value` on a deterministic N=60 subsample
(SHA-1-keyed, insertion-order-independent), aggregates spans via
`aggregate_per_value_spans` (coverage × max_confidence, 10% floor),
and **unions** the result with the post-merge cascade findings.

Spec revision 2026-04-17: changed from "GLiNER replaces cascade" to
"GLiNER augments cascade". Rationale:
- Regex cascade has 100% precision where patterns fire; replacing it
  sacrifices deterministic EMAIL/IP/URL/SSN recovery.
- GLiNER urchade/gliner_multi_pii-v1 is English-only.
- Sprint 10 S1 research documented GLiNER hallucinates PERSON_NAME
  on numeric tokens without NL-prompt context.

### Safety audit Q3 — union checks

See `docs/research/meta_classifier/sprint13_item_b_safety_audit.json`.

| Check | Result | Target |
|---|---|---|
| Cascade regressions | **0/6** | 0 |
| Fixtures with GLiNER lift | **2/6** | ≥3 (not met) |
| Hallucinations | **0/6** | 0 |

GLiNER lift fixtures: `kafka_event_stream` (+PERSON_NAME),
`apache_access_log` (+PERSON_NAME). Other 4 fixtures have entities the
regex cascade already covers. Spec target ≥3 not met — this is an honest
result, not a quality issue. The model adds value on exactly the fixtures
where prose names exist.

**ADDRESS detection** — tested separately: GLiNER detects street addresses
at 95% confidence and 100% coverage on customer-note-style text. This is
the biggest value-add from per-value mode because the regex cascade has
zero value-level address detection (no regex can parse "123 Main St").
No Q3 fixture currently exercises this; adding an address fixture is a
Sprint 14 follow-up.

### Family benchmark — no regression

See `docs/research/meta_classifier/sprint13_item_b_family_benchmark.json`.

| Metric | Item A baseline | Item B |
|---|---|---|
| `cross_family_rate_emitted` | 0.0001 | 0.0001 |
| `family_macro_f1_emitted` | 0.9999 | 0.9999 |
| `router_suppression_rate` | 0.2305 | 0.2308 (+3 columns) |

### Per-value latency — "measure, do not gate" (Sprint 13 scoping Q2)

Local ONNX GLiNER v1, N=50 sampled values, 10 columns
(8 routed to `free_text_heterogeneous`):

| Column | sampled | ms |
|---|---|---|
| audit | 50 | 1,478 |
| customer_notes | 50 | 1,696 |
| support_chat | 50 | 1,712 |
| app_log | 50 | 1,814 |
| kafka_stream | 50 | 2,272 |
| original_q3_log | 50 | 2,290 |
| apache_access_log | 50 | 2,598 |
| json_event_log | 50 | 2,894 |

Summary: min=1,478ms, median=2,272ms, p90=2,894ms, max=2,894ms.

At the default N=60 cap, expect ~20% higher (~1.8–3.5s per column).
This is per-column overhead on the heterogeneous branch only; structured
columns are unaffected.

### Sprint 14 decision point

Sprint 13 shipped with no latency gate. Before Sprint 14 imposes a
timeout fallback, the ColumnShapeEvent stream from production should
accumulate at least 1 week of data so the tail (p99) can be
characterized on real BQ traffic.

### Files touched (Item B)

- `data_classifier/core/types.py` — SpanDetection dataclass
- `data_classifier/config/engine_defaults.yaml` — per_value_sample_size config
- `data_classifier/engines/gliner_engine.py` — classify_per_value + _stable_subsample + _load_per_value_sample_size
- `data_classifier/orchestrator/per_value_aggregator.py` (new) — aggregation helper
- `data_classifier/orchestrator/orchestrator.py` — heterogeneous branch wiring + _union_findings + _find_engine_by_name
- `data_classifier/events/types.py` — ColumnShapeEvent (unchanged; fields from Item A)
- `tests/engines/test_gliner_per_value.py` (new) — 15 tests
- `tests/orchestrator/test_per_value_aggregator.py` (new) — 9 tests
- `tests/orchestrator/test_heterogeneous_branch_integration.py` (new) — 5 tests
- `tests/benchmarks/meta_classifier/sprint12_safety_audit.py` — Q3 union checks

### Follow-ups not taken

1. Non-English GLiNER variant for multilingual heterogeneous content
2. GLiNER per-value on structured_single as a cascade fallback
3. Per-entity-type confidence calibration on real BQ columns
4. ADDRESS Q3 fixture (tests address detection lift)
5. GLiNER lift target ≥3 fixtures (currently 2/6 — add address fixture would likely close this)
