# GLiNER context injection — S1 smoke test (first session, 2026-04-13 14:30)

> **Status:** INCONCLUSIVE (shakeout only — no F1 yet)
>
> **Branch:** `research/gliner-context` @ first session
>
> **Worktree:** `/Users/guyguzner/Projects/data_classifier-gliner-context`

## Goal

Prove the engineering pipeline for measuring context-injection strategies on
GLiNER2 before committing to a full corpus-wide measurement. Specifically:

1. Confirm `fastino/gliner2-base-v1` loads from the local HF cache with zero
   network traffic (cache at `~/.cache/huggingface/hub/models--fastino--gliner2-base-v1/`,
   804 MB, `refs/main` → `283f4af5`).
2. Confirm the production code path — `extract_entities(text, dict)` where
   dict values are descriptions — actually reaches the model's internal
   schema and is not silently ignored.
3. Map the full GLiNER2 API surface for descriptions so the research plan
   uses the right method.
4. Compare three variants on a trivial easy case (5 clean emails) to
   establish that the measurement pipeline can distinguish them at all.

## Hypothesis

Natural-language context prompts (S1), per-column label descriptions (S2),
and label narrowing (S3) each inject some signal that GLiNER can use. S1
and S3 work on both v1 and v2; S2 requires v2 because v1 labels are a flat
list of strings with no description field.

## Method

### 1. API probing

Read `gliner2/inference/engine.py` directly (installed at
`/Users/guyguzner/Projects/data_classifier/.venv/lib/python3.14/site-packages/gliner2/inference/engine.py`).
Key findings:

- `extract_entities(text, entity_types)` at line 1361 is a **thin wrapper**
  that calls `self.create_schema().entities(entity_types)` and delegates to
  `extract(text, schema)`.
- `Schema.entities()` at line 205 accepts `Union[str, List[str], Dict[str, Union[str, Dict]]]`
  via `_parse_entity_input`. A dict of `{label: description_str}` is
  interpreted as `{label: {"description": description}}` and stored in
  `schema["entity_descriptions"]` at line 230.
- Therefore the production code at `data_classifier/engines/gliner_engine.py:200-202`
  (`_gliner_labels_v2: dict[str, str]`) **does** flow descriptions into the
  model's internal schema. My initial suspicion that the Sprint 8 GLiNER2 ORG
  over-fire was caused by silently dropped descriptions is **refuted**.

### 2. Strategy-to-API mapping

| Strategy | Method | v1 OK? | v2 OK? | Notes |
|---|---|---|---|---|
| **S1** NL prompt (context sentence before/around values) | `extract_entities(nl_text, labels)` | ✓ | ✓ | Changes only the `text` argument; labels unchanged. |
| **S2** Per-column label descriptions | `extract_entities(text, {label: ctx_desc})` | ✗ (v1 labels are flat list) | ✓ | Rebuilds the dict per column to inject column/table/description context into each label's description string. |
| **S3** Label narrowing by column-name hint | `extract_entities(text, narrowed_labels)` | ✓ | ✓ | Filters labels dict to hinted types + small safety net. |
| **S4** `data_type` pre-filter | (not a GLiNER call) | — | — | Pulled into main Sprint 9 backlog, not measured here. |
| **S5** Description tokens as additional labels | `extract_entities(text, labels + desc_tokens)` | ✓ | ✓ | Deferred — highest variance, lowest priority. |

All four measurable strategies call the same `extract_entities` entry point —
only the `text` and `entity_types` arguments change. That means a pluggable
`(prompt_builder, label_builder) -> (text, labels)` pair is a clean harness
contract.

### 3. Smoke input

Synthetic column:
- `column_name="email_address"`, `table_name="users"`
- `description="user's primary contact email, required, unique"`
- 5 clean email values: `alice@example.com`, `bob.smith@acme.co.uk`,
  `charlie+filter@test.org`, `david.jones@data.gov`, `eve@university.edu`

Three variant calls against `fastino/gliner2-base-v1`:

| Variant | `text` | `entity_types` |
|---|---|---|
| **A** Flat-list labels (urchade-style baseline) | `" ; ".join(values)` | `["person", "email", "street address", "organization", "phone number"]` |
| **B** Dict + static descriptions (fastino production) | `" ; ".join(values)` | `{"email": "Email addresses including international domains and subdomains", ...}` (5 labels, descriptions copied from production) |
| **C** S1 NL prompt + dict descriptions | `f"Column '{col}' from table '{tbl}'. Description: {desc}. Sample values: {', '.join(values)}"` | same dict as B |

Script: `scripts/research/gliner_context_smoke.py`.

## Results

### Latency

| Variant | Latency (first call, cold) |
|---|---:|
| A Flat list | 152 ms |
| B Dict + descriptions | 95 ms |
| C S1 NL prompt + dict | 106 ms |

The 152ms of Call A includes model-warmup cost. Calls B and C are within
noise of each other. **S1 adds no measurable latency penalty vs the dict baseline.**

### Predictions (all three variants)

All 5 emails correctly detected as `email` in all 3 variants. Zero false
positives on `person`, `street address`, `organization`, `phone number`.
**Top-1 entity set is identical across variants.**

### Confidence shift (per-value)

| Value | A flat | B dict+desc | C S1 prompt |
|---|---:|---:|---:|
| `alice@example.com` | 0.9996 | 0.9999 | **0.99999** |
| `bob.smith@acme.co.uk` | 0.9987 | 0.9995 | **0.99980** |
| `charlie+filter@test.org` | 0.9963 | 0.9988 | **0.99955** |
| `david.jones@data.gov` | 0.9991 | 0.9998 | **0.99986** |
| `eve@university.edu` | 0.9990 | 0.9995 | **0.99974** |

Monotone lift A → B → C across all 5 values. Each layer of context
(descriptions, then NL prompt) pushes the model's internal confidence up,
even when the top-1 label doesn't change.

## Verdict

**INCONCLUSIVE — methodology only, no F1 number yet.**

This run is not a SHIP/DO NOT SHIP decision. It is a pipeline-readiness
check. The pipeline is ready:

- Model loads from local cache, zero network. ✓
- `extract_entities(text, dict)` is a live description-aware path. ✓
- Production code does NOT silently drop descriptions. ✓
- S1 prompts add no latency penalty. ✓
- Three variants produce *different internal confidences* even when entities
  don't flip, so the measurement instrument has resolution. ✓

What is explicitly NOT proven here:

- No F1 number — the easy email case is a no-op for top-1 decisions. Need
  hard cases (ORG/numeric-dash, ambiguous names, SSN↔ABA collisions).
- No statistical significance — n=5 sample.
- No corpus measurement — single synthetic column.

## Recommendation

**DO NOT SHIP.** This memo exists to document pipeline readiness, not to
promote anything. The next step is a real measurement run on a corpus of
100+ columns, with entity-type breakdown and McNemar significance testing.

## Open questions blocking a real result memo

1. **Corpus choice.** Gretel-EN (the designated primary blind corpus) is
   not yet ingested locally. Options:
   - (a) Reuse existing Ai4Privacy column-synthesis pipeline if one exists
     under `tests/benchmarks/` — Sprint 7 ships Ai4Privacy phone/credential
     numbers, so a pipeline probably exists; not yet located.
   - (b) Synthesize 50-100 hand-spec'd columns for this research, with
     values sampled from the Ai4Privacy datasets cache.
   - (c) Wait for Sprint 9 `ingest-gretel-pii-masking-en-v1` to land.
   Option (a) is fastest if the pipeline exists. Option (c) is cleanest but
   blocks progress. User preference: proceed now with (a) or (b), flag that
   the final SHIP/DO NOT SHIP must re-measure on Gretel-EN.

2. **Which entity types to prioritize.** ORGANIZATION over-fire and
   PERSON_NAME/ADDRESS collisions are the Sprint 8 known-pain. Should the
   harness weight those in the macro F1, or report unweighted only?

3. **Baseline anchor.** Should the "baseline" be production's current live
   code path (urchade v1, `predict_entities(text, flat_list, threshold=0.5)`),
   or the Sprint 9 promotion target (fastino v2,
   `extract_entities(text, dict_with_descriptions, threshold=0.80)`)?
   Memoryfile `project_active_research.md` says cite +0.191 against the
   honest 5-engine baseline — the analogous baseline for this research
   would be fastino+dict+threshold=0.80 (Sprint 9's winning config).

## Session notes

- Worktree created on `research/gliner-context` branch, off `main` at
  `65b6000`.
- `queue.md` committed as first action: `d0e1ba9`.
- Smoke test script at `scripts/research/gliner_context_smoke.py` — runnable
  standalone via `.venv/bin/python scripts/research/gliner_context_smoke.py`.
- Local ML asset inventory persisted as
  `~/.claude/projects/-Users-guyguzner-Projects-data-classifier/memory/reference_local_ml_assets.md`.
- Feedback memory saved: `feedback_reuse_local_models.md` — stop
  re-downloading locally cached models.
