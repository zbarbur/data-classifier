# M4d Phase 3a — pilot scale-labeler run

**Run date:** 2026-04-21
**Model:** `claude-opus-4-7`
**Corpus:** `data/m4d_phase3_corpus/unlabeled.jsonl` (41 cols / ~115 GB BQ scan)
**Labeled output:** `data/m4d_phase3_corpus/labeled.jsonl` (DVC-tracked)
**Review worksheet:** `data/m4d_phase3_corpus/review_worksheet.{jsonl,md}`

## Purpose

Exercise the full M4d pipeline (fetcher → Phase 2 router-labeler → review worksheet)
end-to-end on a small pilot before committing to Phase 3b full scale (~280 cols).
Goal: validate plumbing, cost model, and router/prompt behavior on unseen sources.

## Run stats

| Metric | Value |
|---|---|
| Columns labeled | 41 |
| API errors | 1 (Anthropic safety refusal on `sprint12_base64_encoded_payloads`) |
| Unknown labels emitted | 0 |
| Empty predictions | 7 (all CFPB, all matching prefill=[]) |
| Prefill ↔ pred agreement | 32 agree / 8 disagree / 1 error |
| Input tokens (uncached) | 332,434 |
| Output tokens | 2,952 |
| Cache read tokens | 62,436 |
| Cache creation tokens | 0 (warmed by earlier smoke test) |
| Cache hit rate on input | 15.8% |
| **Estimated cost** | **$1.77** |
| Wall-clock | ~2 minutes |

Per-shape breakdown (cols):

| Shape | n | Top labels emitted |
|---|---|---|
| `free_text_heterogeneous` | 22 | EMAIL, PERSON_NAME, URL, ADDRESS |
| `structured_single` | 15 | ADDRESS (9), PERSON_NAME (6) |
| `opaque_tokens` | 4 | ETHEREUM_ADDRESS (3) + 1 refusal |

## Disagreements (pre-review)

8 of 41 rows have prefill ≠ pred_labels. Split by likely root cause:

**Labeler probably more correct than prefill (4 rows):**
- `hn_2021q1_m0`, `hn_2021q1_m1` — +EMAIL; HN comments commonly contain email addresses the prefill conservatively omitted.
- `cfpb_credit_card_m1`, `cfpb_credit_card_m2` — +ADDRESS; some CFPB complaints carry street addresses that escaped the XXXX redaction.

**Labeler extends structurally plausible categories (2 rows):**
- `so_about_me_r100k_300k_m0`, `_m1` — +ADDRESS; high-rep SO users often include specific locations ("based in Austin, TX") beyond "work in SF" style biographical hints.

**Possible Phase 2 prompt over-firing (1 row):**
- `sprint12_original_q3_log` — +ADDRESS, +BANK_ACCOUNT, +SWIFT_BIC. These are exactly the failure modes the Phase 2 heterogeneous prompt targets; needs reviewer verification against the fixture definition.

**Fixture semantics drift (1 row):**
- `sprint12_kafka_event_stream` — +AGE, −CREDIT_CARD. Kafka fixture may carry age fields; CC may be obscured below the labeler's confidence threshold.

The 8 disagreements all fall within the expected envelope for a first-pass scale run — no pathological over-firing pattern visible in the aggregate label distribution.

## Anthropic safety refusal — `sprint12_base64_encoded_payloads`

The `opaque_tokens` fixture of base64-encoded payloads triggered `stop_reason: refusal`
(no output blocks). First value decodes to `{"user":"alice@example.com","role":"admin"}` —
individually harmless, but the content-safety classifier appears to flag the concatenation.

**Resolution for pilot:** row kept in `labeled.jsonl` with `error` set and `pred_labels=[]`.
Reviewer eyeballs against prefill (`OPAQUE_SECRET`), which is structurally guaranteed
correct for this shape.

**Action item for Phase 3b:** add a heuristic fallback for `opaque_tokens` columns that
triggers on refusal — emit `OPAQUE_SECRET` (or shape-specific label like `ETHEREUM_ADDRESS`)
without re-calling the model. Tracked under M4d Phase 3b follow-up items.

## Synthetic ETH validation

The 3 synthetic ETH shards (`eth_synth_s0..s2`) — each 100 sha256-derived `0x`+40-hex
values replacing ~354 GB of crypto_ethereum BQ scan — were all labeled `ETHEREUM_ADDRESS`
by the opaque-tokens branch. Confirms that shape-based routing is insensitive to
blockchain authenticity, so synthetic substitution is a viable cost lever for
Phase 3b opaque-token coverage.

## Phase 3a deliverables

Artifact layout:
```
data/m4d_phase3_corpus/                              (DVC-tracked)
├── unlabeled.jsonl         (41 cols / 1.9 MB)
├── labeled.jsonl           (41 cols / ~ 2 MB)
├── summary.json            (run metrics)
├── review_worksheet.jsonl  (reviewer input)
└── review_worksheet.md     (reviewer read-out)

docs/experiments/meta_classifier/runs/20260421-m4d-phase3a-pilot/
├── result.md               (this file)
└── summary.json            (copy for git-visibility)
```

## Next

1. Human reviewer processes `review_worksheet.jsonl` — for each row:
   - sets `reviewer_labels` (the authoritative ground truth)
   - sets `reviewer_status` ∈ {approve, amend, reject}
   - fills `reviewer_notes` where the decision is non-obvious

2. Score reviewer output vs labeler predictions:
   - Per-shape Jaccard
   - Confusion-matrix-like tally of extra / missing labels per branch
   - Gate: ≥ 0.8 macro Jaccard required before Phase 3b greenlight

3. If gate passes → proceed to Phase 3b (~280 cols):
   - Bump `PILOT_*` constants in `scripts/m4d_phase3_build_scale_corpus.py`
   - Add opaque-token refusal-fallback handler
   - Re-enable NY311 / GitHub author fetchers after NY311 400 investigation
   - Re-run fetcher + labeler + worksheet at scale

4. If gate fails → iterate on the Phase 2 heterogeneous prompt (analogous to M4d
   Phase 2 iteration 1→2 which moved Jaccard 0.8105 → 0.8655).
