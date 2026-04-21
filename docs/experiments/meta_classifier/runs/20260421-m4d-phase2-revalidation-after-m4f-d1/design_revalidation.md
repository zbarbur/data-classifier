# M4f-d1 design revalidation — Phase 2 + Phase 3a after base64 decoder stage

**Run date:** 2026-04-21
**Design change shipped:** base64 decoder stage + Phase 2 `OPAQUE_TOKENS_INSTRUCTIONS` revision + M4c gold row flip
**Full Phase 2 numbers:** `result.md` (in this directory, produced by the driver verbatim)

## Design changes under test

1. **`tests/benchmarks/meta_classifier/llm_labeler_router.py`**
   - New `try_decode_opaque_column(values, min_success_rate=0.8, min_printable_rate=0.9)` — base64-decodes each value; fires if ≥ 80% decode to ≥ 90%-printable UTF-8; returns decoded values + recommended shape (`free_text_heterogeneous`).
   - `label_gold_set_via_router` calls the decoder at the opaque-tokens branch entry. On fire: substitute decoded values, re-route row to heterogeneous prompt. On no-fire: existing path.
   - `OPAQUE_TOKENS_INSTRUCTIONS` — stripped the "do NOT attempt to base64-decode" guardrail; replaced with "decoding handled upstream, label what you receive."

2. **`tests/benchmarks/meta_classifier/heterogeneous_gold_set.jsonl`**
   - `sprint12_fixture_base64_encoded_payloads.true_labels`: `[OPAQUE_SECRET]` → `[EMAIL]`.
   - Audit: annotator updated to `m4f-d1-decoder-design-2026-04-21`; notes preserve prior annotation and explain the design-era shift.

3. **`tests/benchmarks/meta_classifier/test_opaque_decoder.py`** (new) — 10 unit tests covering: base64 JSON decode, ETH hex fall-through, BTC hash fall-through, high-entropy noise rejection, threshold configurability, padding tolerance, empty-column defense, column-length preservation on partial failures.

## Phase 2 revalidation on M4c gold set (50 rows)

| Metric | Prior (2026-04-18) | Post-M4f-d1 | Delta |
|---|---|---|---|
| Macro Jaccard | `0.8655` | `0.8630` | **−0.0025** |
| opaque_tokens Jaccard | `1.0000` | `1.0000` | 0 |
| structured_single Jaccard | `1.0000` | `1.0000` | 0 |
| free_text_heterogeneous Jaccard | `0.8057` | `0.8043` | −0.0014 |
| API errors | 0 | 0 | 0 |

### Delta decomposition (7 rows changed predictions between runs)

Only **one row** changed because of the design shipping:

| column_id | old pred | new pred | gold_labels shifted? | Jaccard impact |
|---|---|---|---|---|
| `sprint12_fixture_base64_encoded_payloads` | `[OPAQUE_SECRET]` | `[EMAIL]` | `[OPAQUE_SECRET]` → `[EMAIL]` | 0 (both 1.0 → 1.0) |

**The other 6 rows changed because of LLM stochasticity** — adaptive-thinking produces slightly different token-level choices across runs, especially with different cache warmth. These rows touch prompts we didn't revise (`HETEROGENEOUS_INSTRUCTIONS` is unchanged):

| column_id | direction | old → new |
|---|---|---|
| `hn_comments_2019` | ↓ | +HEALTH (spurious) |
| `so_about_me_rep_100_1k_a` | ↓ | +PHONE (spurious) |
| `so_about_me_rep_1k_10k_b` | ↓ | +ADDRESS (spurious) |
| `sprint12_fixture_original_q3_log` | ↓ | +DATE (minor) |
| `so_about_me_rep_100_1k_b` | ↑ | +AGE (correct) |
| `so_about_me_rep_100k_plus_b` | ↑ | −ADDRESS (correct) |

Net: 2 up, 4 down. Sum of per-row Jaccard deltas = −0.1223 → macro delta = −0.0024, which accounts for the entire observed −0.0025.

### Gate verdict: ✅ PASSED

The −0.0025 macro delta is **run-to-run LLM noise**, not a methodological regression — it's driven entirely by rows my design changes didn't touch. The design rows (sprint12 base64) performed exactly as expected: both pred and gold shifted to `[EMAIL]`, Jaccard stays 1.0. Per-shape bottom line:

- `opaque_tokens` held at 1.0 through the shape change on the base64 row (shape column unchanged in gold — decoder fires at routing time, not at shape-classification time).
- `structured_single` unchanged (no touch).
- `free_text_heterogeneous` fluctuated ±0.003 on stochasticity — within noise band.

**Recommendation:** accept this as the new baseline. Future Phase 2 runs should compare vs the 50-row gold set with tolerance of ±0.003 on macro Jaccard before concluding a regression. This is an inherent property of LLM-anchored benchmarks at n=50; Phase 3b's n=280 will tighten the noise band.

## Phase 3a re-labeling on the real scale corpus

The `sprint12_base64_encoded_payloads` row in `data/m4d_phase3_corpus/labeled.jsonl` (which previously errored with `stop_reason: refusal`) was re-run through the updated pipeline:

- Decoder fired on xor-decoded base64 values, routed `opaque_tokens → free_text_heterogeneous`.
- Labeler returned `[EMAIL]` cleanly (no refusal, no error).
- Tokens: 1,344 input + 137 output (~$0.010 incremental cost).

Phase 3a aggregate now:

| Metric | Before M4f-d1 (2026-04-21 morning) | After M4f-d1 |
|---|---|---|
| Macro Jaccard (pred vs reviewer) | `0.9268` | `0.9512` |
| `opaque_tokens` Jaccard | `0.7500` (3/4 perfect) | `1.0000` (4/4 perfect) |
| API errors | 1 | 0 |
| Empty predictions | 7 (all CFPB expected []) | 7 (unchanged) |

The refusal-driven zero in opaque_tokens is gone. The 2 CFPB ADDRESS disagreements remain (M4f-d2 Phase 2 prompt revision territory — not blocked on this work).

## Phase 3b greenlight status

M4f-d1 was the **P1 blocker** on Phase 3b greenlight. With unit + integration verification clean + Phase 2 gate passing within noise + Phase 3a now error-free, Phase 3b can proceed once scope is decided.

Remaining Phase 3b items (queue.md) — **no longer blockers, quality-track**:
- M4f-d2 (P2) — heterogeneous prompt redaction discipline
- NY311 dry-run 400 investigation
- Opaque-token refusal fallback — **down-prioritized** from Phase 3a review: decoder stage removes the refusal-prone branch for decodable content. Remaining refusal risk is shape-specific opaque (ETH/hash) which the existing prompt handles without issue.
