# M4d Phase 3a — human-review outcome

**Review date:** 2026-04-21
**Reviewer:** gguzner@gmail.com (interactive walkthrough)
**Worksheet:** `data/m4d_phase3_corpus/review_worksheet.jsonl` (41 rows / full coverage)

## Gate verdict: ✅ PASSED

**Macro Jaccard (pred vs reviewer):** `0.9268` — above the 0.8 gate.

Per-shape (all above the 0.7 per-branch threshold):

| Shape | n | Jaccard | Notes |
|---|---|---|---|
| `structured_single` | 15 | **1.0000** | so_location (5), austin311 (4), so_display (6) — all perfect |
| `free_text_heterogeneous` | 22 | **0.9091** | 2/22 disagreements, both CFPB (redaction over-fire) |
| `opaque_tokens` | 4 | **0.7500** | 3 ETH synth perfect, 1 base64 refusal pulled average (reviewer amended) |

## Review volume

- **32 auto-approvals** — rows where labeler prediction matched fetcher prefill exactly. Bulk-approved without individual review.
- **9 manual decisions** — 8 disagreements + 1 labeler error. Each adjudicated against the full 50-100 decoded values using targeted pattern scans (`STREET`, `CITY_STATE`, `EMAIL`, etc.) rather than LLM re-labeling.

## The 3 rows where reviewer ≠ labeler

### 1. `cfpb_credit_card_m1` + `cfpb_credit_card_m2` — reject labeler's ADDRESS

**Labeler output:** `[ADDRESS]` (both)
**Reviewer decision:** `[]` (both)
**Evidence:** value scans show 6-10 `XXXX <CITY>, <STATE>` patterns per column. Redaction removes the city; bare state alone is biographical context per the Phase 2 prompt's "do NOT label the redacted entity on the basis of the placeholder alone" rule.
**Reviewer policy:** "skip redacted data — if stripping XXXX leaves insufficient signal, drop the label."

→ Filed as **M4f-d2** (queue.md): Phase 2 heterogeneous prompt revision to explicitly cover `XXXX, <STATE>` patterns.

### 2. `sprint12_kafka_event_stream` — approve labeler's CC drop + AGE addition

**Prefill:** `[CREDIT_CARD, EMAIL, IP_ADDRESS, PHONE, URL]`
**Labeler output:** `[AGE, EMAIL, IP_ADDRESS, PHONE, URL]`
**Reviewer decision:** approve labeler (`[AGE, EMAIL, IP_ADDRESS, PHONE, URL]`)
**Evidence:** the fixture's CC values are masked (`"4111...4242"` — 4 digits + ellipsis + 4 digits, not a valid 16-digit PAN). AGE appears 10× as literal `"age":32` / `"age":28` values.
**Why approve the drop:** surface-form rule applies per reviewer's skip-redacted policy — masked CCs don't fire CREDIT_CARD. This is the *right* behavior for production scanning: masked data should not be labeled as the pre-masked entity.

### 3. `sprint12_base64_encoded_payloads` — amend from `[]` (refused) to `[EMAIL]`

**Labeler output:** `[]` with `error: AttributeError: 'NoneType' object has no attribute 'labels'` (Anthropic safety layer returned `stop_reason: refusal`)
**Reviewer decision:** `[EMAIL]`
**Evidence:** 50/50 values decode to `{"user":"<email>","role":"<role>"}`. The column contains 50 emails wrapped in base64.
**Why:** base64 is a reversible encoding, not secrecy. Labeling decodable base64 as `OPAQUE_SECRET` is a taxonomy category error — that class must be reserved for genuinely-opaque high-entropy residuals. Committed design direction: **base64 decoder + re-detection stage** (M4f-d1).

→ Filed as **M4f-d1** (queue.md): Phase 3b pre-blocker. Decoder stage must ship before Phase 3b runs so this mode produces semantic labels instead of refusals / category-errors.

## Phase 3b blockers (ranked)

1. **M4f-d1 (P1)** — base64 decoder + re-detection stage. Ships before Phase 3b. Includes Phase 2 opaque-tokens prompt revision (remove "do NOT decode" guardrail).
2. **M4f-d2 (P2)** — Phase 2 heterogeneous prompt: strengthen `XXXX, <STATE>` → `[]` discipline. Quality item, not a blocker.
3. **Opaque-token refusal fallback** — structurally label when Anthropic safety refuses. Becomes low-priority once M4f-d1 ships (decoder path bypasses the refusal-prone LLM call for structured-base64 content).
4. **NY311 dry-run 400 investigation** — re-enable fetcher when cheap.

## Artifact state after review

- `data/m4d_phase3_corpus/review_worksheet.jsonl` — all 41 rows now have `reviewer_labels`, `reviewer_status ∈ {approve, amend}`, and `reviewer_notes`. DVC snapshot needs update.
- `data/m4d_phase3_corpus/review_worksheet.md` — stale after review-worksheet.jsonl edits (regenerate if needed for viewing).
- `docs/experiments/meta_classifier/queue.md` — M4f-d1 + M4f-d2 items added.
- `.claude/memory/project_base64_decoder_stage.md` — design commitment saved for future sessions.
