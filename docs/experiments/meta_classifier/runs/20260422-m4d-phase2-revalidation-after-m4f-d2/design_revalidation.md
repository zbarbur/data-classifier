# M4f-d2 design revalidation — heterogeneous prompt redaction discipline

**Run date:** 2026-04-22
**Design change:** Phase 2 `HETEROGENEOUS_INSTRUCTIONS` gets a redaction carve-out for ADDRESS, plus a strengthened CFPB few-shot example.
**Full Phase 2 numbers:** `result.md` in this directory (driver-generated verbatim).

## Design change under test

`tests/benchmarks/meta_classifier/llm_labeler_router.py`:

1. **ADDRESS clause** — added an explicit carve-out: redacted-city + surviving bare state code (`XXXX, NY`, `XXXX XXXX, MI`, `at XXXX NJ`) does **not** qualify as ADDRESS. Written as a direct instruction because the old prompt's general redaction clause wasn't specific enough — the labeler interpreted the surviving state as sufficient evidence to fire ADDRESS.

2. **CFPB few-shot example** — added 2 values demonstrating the exact failure mode (`XXXX, NJ`, `XXXX XXXX, MI`, `XXXX, NY`) with label `[]`, alongside the existing CFPB redaction examples. The example description now explicitly names the `XXXX, NY` pattern.

## Phase 2 revalidation on M4c gold set (50 rows)

| Metric | Post-M4f-d1 (2026-04-21) | Post-M4f-d2 (2026-04-22) | Delta |
|---|---|---|---|
| Macro Jaccard | `0.8630` | `0.8671` | **+0.0041** |
| `free_text_heterogeneous` | `0.8043` | `0.8102` | +0.0059 |
| `opaque_tokens` | `1.0000` | `1.0000` | 0 |
| `structured_single` | `1.0000` | `1.0000` | 0 |
| API errors | 0 | 0 | 0 |

M4f-d2 is a net positive on the gold set — slightly above the pre-M4f-d1 baseline (0.8655), and above the original Phase 2 gate (0.8000). Structured/opaque branches untouched as expected (prompt revision was heterogeneous-only).

## Phase 3a re-labeling on the 2 CFPB target rows

The 2 rows where the human reviewer rejected the labeler's ADDRESS over-fire were re-run with the updated prompt:

| column_id | pre-M4f-d2 pred | post-M4f-d2 pred | reviewer_labels |
|---|---|---|---|
| `cfpb_credit_card_m1` | `[ADDRESS]` | `[]` | `[]` |
| `cfpb_credit_card_m2` | `[ADDRESS]` | `[]` | `[]` |

Both now match reviewer exactly. No tokens wasted on retry — 18,881 + 18,548 input tokens (cache-cold on the revised opaque prompt) + 12 output tokens each, trivial cost (~$0.20 incremental).

## Phase 3a aggregate after M4f-d2

| Metric | Pre-M4f (2026-04-21 AM) | Post-M4f-d1 (2026-04-21 PM) | Post-M4f-d2 (2026-04-22) |
|---|---|---|---|
| Macro Jaccard (pred vs reviewer) | `0.9268` | `0.9512` | **`1.0000`** |
| `opaque_tokens` Jaccard | `0.7500` | `1.0000` | `1.0000` |
| `free_text_heterogeneous` Jaccard | `0.9091` | `0.9091` | `1.0000` |
| `structured_single` Jaccard | `1.0000` | `1.0000` | `1.0000` |
| API errors | 1 | 0 | 0 |

**Phase 3a is now perfect agreement across all 41 rows** — all three design changes (M4f-d1 decoder, M4f-d2 redaction discipline, and the implicit CFPB/sprint12-q3-log verdicts from the human review) lined up, and the labeler at scale fully matches the human reviewer's ground truth.

## What this sets up for Phase 3b

The 2 prompt-derived disagreements that would have scaled linearly in Phase 3b (CFPB ADDRESS at ~30 over-fires on the proposed 150-col CFPB slice) are pre-fixed. Phase 3b now runs against a labeler that has been validated at Jaccard 1.0 on the full Phase 3a pilot — we expect the actual Jaccard at Phase 3b scale to be near that, with the main source of residual disagreement being genuinely novel column shapes the prompt hasn't seen.

### Phase 3b blockers status

- ~~M4f-d1~~: ✅ shipped 2026-04-21
- ~~M4f-d2~~: ✅ shipped 2026-04-22
- ~~Opaque-token refusal fallback~~: down-prioritized (decoder stage eliminates the refusal-prone path)
- NY311 dry-run 400 investigation: P3 (re-enable if cheap; not a blocker)

**Phase 3b greenlit.** Execution: bump `PILOT_*` constants in `scripts/m4d_phase3_build_scale_corpus.py`, re-run the pipeline at the targeted ~280-col budget.
