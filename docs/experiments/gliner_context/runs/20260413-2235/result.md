# GLiNER context injection — first real F1 run (2026-04-13 22:35)

> **Status:** INCONCLUSIVE per SHIP gate (n too small), but S1 is a **promising** candidate.
>
> **Branch:** `research/gliner-context`
>
> **Scale:** 21 columns, 30 values each, single seed.
>
> **Corpus:** Ai4Privacy fixture (shakeout only — NOT a valid headline F1
> source per research brief; must re-measure on Gretel-EN before ship).

## Goal

Run the first end-to-end measurement of all four strategies against
`fastino/gliner2-base-v1`, on a controlled synthetic corpus that varies
**context helpfulness** while holding **value content** fixed. Decide
which strategies are worth scaling up.

## Method

1. **Corpus.** Loaded 438,960 Ai4Privacy `(entity_type, value)` records
   from `tests/fixtures/corpora/ai4privacy_sample.json` (despite the
   "sample" name). Bucketed by canonical type via
   `AI4PRIVACY_TYPE_MAP`, kept 8 types with ≥50 values each: ADDRESS,
   CREDENTIAL, DATE_OF_BIRTH, EMAIL, IP_ADDRESS, PERSON_NAME, PHONE,
   SSN. (CREDENTIAL was excluded from the corpus build because the
   label is not in this research's `CONTEXT_TEMPLATES` — it needs
   a separate treatment and is tracked in Sprint 9 items
   `credential-corpus-*`.)
2. **Context templates.** Authored 3 templates per entity type
   (7 types × 3 = 21 columns):
   - **helpful** — metadata strongly implies the ground-truth type
     (e.g. `column_name="email_address"`, `table_name="users"`,
     `description="user's primary contact email..."`)
   - **empty** — metadata is generic (`column_name="col_17"`,
     `table_name="t"`, `description=""`)
   - **misleading** — metadata implies a different type
     (e.g. `column_name="invoice_number"` on a column of emails)
3. **Values.** Each column carries 30 values, sampled from the pool
   for its ground-truth type using a stable per-`(type, kind)` offset
   so the three templates for the same type have distinct slices.
4. **Strategies.** Four pluggable `(ColumnInput) -> (text, entity_types)`
   functions:
   - `baseline`: `" ; ".join(values)` + frozen description dict (matches
     production with `_is_v2=True`)
   - `s1_nl_prompt`: NL prefix `Column '{col}' from table '{tbl}'. Description: {desc}. Sample values: v1, v2, …`
   - `s2_per_column_descriptions`: `" ; ".join(values)` + dict where each
     label description is rewritten as `"In a column named '{col}' in table '{tbl}': {base_desc}"`
   - `s3_label_narrowing`: `" ; ".join(values)` + dict narrowed by keyword
     hints on `column_name` plus an `{email, person, phone}` safety net
5. **Model.** `GLiNER2.from_pretrained("fastino/gliner2-base-v1")` from
   the local HF cache (804 MB, `refs/main` → `283f4af5`). Zero network.
6. **Threshold.** 0.5 (production default for urchade v1; Sprint 9
   target for fastino is 0.80 — re-run needed at 0.80).
7. **Metrics.** Per-column top-1 presence:
   - TP: ground-truth type reported
   - FN: ground-truth type NOT reported
   - FP: any OTHER type reported for that column
   - Macro F1 = average of per-entity-type F1, including types with
     zero ground-truth support if the model false-fires them

## Results

### Overall macro F1 on 21 columns

| Strategy | Macro F1 | Δ vs baseline | Latency p50 (ms) | Latency p95 (ms) |
|---|---:|---:|---:|---:|
| `baseline` | 0.4636 | — | 209.4 | 462.9 |
| **`s1_nl_prompt`** | **0.5182** | **+0.0546** | 218.6 | 415.8 |
| `s2_per_column_descriptions` | 0.4557 | −0.0079 | 251.0 | 478.3 |
| `s3_label_narrowing` | 0.4483 | −0.0153 | 198.9 | 380.9 |

### Stratified by context helpfulness

| Strategy | empty | helpful | misleading |
|---|---:|---:|---:|
| `baseline` | 0.4042 | 0.5417 | 0.4208 |
| **`s1_nl_prompt`** | **0.5476** | **0.6667** | **0.5208** |
| `s2_per_column_descriptions` | 0.4875 | 0.5208 | 0.3833 |
| `s3_label_narrowing` | 0.4042 | **0.7429** | 0.3381 |

### Per-entity F1 (baseline strategy)

| Entity | P | R | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| EMAIL | 0.750 | 1.000 | **0.857** | 3 | 1 | 0 |
| ADDRESS | 0.500 | 1.000 | 0.667 | 3 | 3 | 0 |
| IP_ADDRESS | 0.333 | 1.000 | 0.500 | 3 | 6 | 0 |
| DATE_OF_BIRTH | 0.300 | 1.000 | 0.462 | 3 | 7 | 0 |
| PERSON_NAME | 0.300 | 1.000 | 0.462 | 3 | 7 | 0 |
| PHONE | 0.273 | 1.000 | 0.429 | 3 | 8 | 0 |
| SSN | 0.333 | 0.333 | 0.333 | 1 | 2 | 2 |
| ORGANIZATION | 0.000 | 0.000 | **0.000** | 0 | 5 | 0 |

### Per-entity F1 (s1_nl_prompt strategy)

| Entity | P | R | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| EMAIL | **1.000** | 1.000 | **1.000** | 3 | 0 | 0 |
| ADDRESS | 0.600 | 1.000 | **0.750** | 3 | 2 | 0 |
| PERSON_NAME | 0.600 | 1.000 | **0.750** | 3 | 2 | 0 |
| DATE_OF_BIRTH | 0.429 | 1.000 | 0.600 | 3 | 4 | 0 |
| IP_ADDRESS | 0.375 | 1.000 | 0.545 | 3 | 5 | 0 |
| PHONE | 0.333 | 1.000 | 0.500 | 3 | 6 | 0 |
| SSN | 0.000 | 0.000 | **0.000** | 0 | 2 | 3 |
| ORGANIZATION | 0.000 | 0.000 | 0.000 | 0 | 3 | 0 |

## Per-strategy analysis

### S1 — NL prompt prefix: **PROMISING**

**Δ macro F1 +0.0546** — above the +0.02 ship gate. Positive delta on
**all three** context-kind strata:

- helpful: +0.125 (0.5417 → 0.6667)
- empty:   +0.143 (0.4042 → 0.5476)
- misleading: +0.100 (0.4208 → 0.5208)

The S1 uplift is **not just a "helpful-context win"** — it also lifts
empty and misleading cases. That is the strongest signal in this run:
giving GLiNER *any* sentence-shaped wrapper appears to reduce false
positives on the other entity types, independent of whether the
wrapper's metadata is correct. Precision lifts: EMAIL 0.75 → 1.00,
ADDRESS 0.50 → 0.60, PERSON 0.30 → 0.60. **But SSN regresses: F1 0.33 → 0.00 (TP 1→0, FP 2, FN 2→3)** — a
concerning individual-entity regression. At n=3 SSN columns, this is
noise-bounded but warrants investigation at scale.

Latency delta: +4% at p50 (209 → 219 ms), −10% at p95 (463 → 416 ms).
Within the +20% gate, effectively free.

### S2 — Per-column label descriptions: **DO NOT SHIP**

**Δ macro F1 −0.0079** and worst on the misleading stratum (−0.0375).
S2 *actively harms* performance on the very cases it was designed to
help — when metadata is misleading, injecting it into every label
description creates internal contradictions inside the prompt
("in a column named 'invoice_number' in table 'billing': Email
addresses..."). GLiNER's label-description semantics are corrupted by
adversarial column context.

Latency delta: +20% at p50 (209 → 251 ms), at the gate limit.

**Verdict: hypothesis is wrong.** Column context in the per-label
description field does not generalize. DO NOT SHIP.

### S3 — Label narrowing: **NEEDS RESEARCH, NOT SHIP-READY**

**Δ macro F1 −0.0153 overall**, but the stratified breakdown is the
most interesting of all four:

- helpful: **+0.20** (0.5417 → **0.7429**) — biggest single lift in
  the run
- empty: 0 (unchanged)
- misleading: **−0.08** (0.4208 → 0.3381) — catastrophic

The bimodal behavior is a **strategy defect, not an experimental artifact**.
When the keyword-based hint on `column_name` is correct, narrowing the
label set trivially eliminates FPs from excluded types and lifts F1
substantially. When the hint is wrong, narrowing locks in the wrong
answer. My hint extractor ("`email`" in name → hint `email`) is naive
and vulnerable to the adversarial `misleading` templates by construction.

**Follow-up research:** can S3 be gated on a confidence signal from
`column_name_engine` proper? i.e. narrow only when the column-name hint
is high-confidence, otherwise fall back to the full label set. This
would capture most of the +0.20 helpful lift while avoiding the −0.08
misleading penalty. File as `docs/experiments/gliner_context/queue.md`
S3b entry.

Latency delta: −5% at p50 (209 → 199 ms) — faster because fewer labels.

## Methodology caveats (read before quoting any number)

1. **n = 21 columns.** Tiny. No confidence intervals, no McNemar
   significance test. Differences in the ±0.02 range are not reliable.
   The S1 +0.05 delta is the only one large enough to survive most
   reasonable bootstrap resampling, but needs n ≥ 100 to confirm.

2. **ORGANIZATION has zero support.** `AI4PRIVACY_TYPE_MAP` doesn't map
   to `ORGANIZATION`, so no column in this corpus has ORG as ground
   truth. But the model still false-fires ORG (5× baseline, 3× S1, 4×
   S2, 1× S3). This makes ORG's per-entity F1 = 0.0 in every run,
   which drags the macro F1 down equally for all strategies. The
   *relative* delta between strategies is unaffected, but the absolute
   numbers are pessimistic. A cleaner macro F1 should either (a) weight
   by support, or (b) exclude zero-support types from the average.

3. **Recall ≈ 1.0 everywhere.** For every entity type with non-zero
   ground-truth support, the model detects the ground truth at
   threshold 0.5 in almost every column. We are effectively measuring
   **false-positive rate**, not recall-F1 tradeoff. At the Sprint 9
   target threshold of 0.80, recall will drop and the story may
   differ — this is a **required re-run** before any ship decision.

4. **Single corpus, single seed.** Ai4Privacy values only, `rng_seed=42`,
   single run. Results hold on at most one corpus; the research brief
   requires two distinct corpora (Gretel-EN + synthetic acceptable).
   Must re-run on Gretel-EN before writing any SHIP verdict.

5. **Value overlap between strata.** Each `(entity_type, context_kind)`
   gets a distinct 30-value slice of the value pool, so no two rows
   share values. This isolates the context effect cleanly, but means
   absolute F1 numbers vary with slice selection — the +0.05 delta
   for S1 is the stable quantity, not the 0.4636 baseline.

6. **Misleading templates are adversarial.** My misleading templates
   were authored by me specifically to contradict ground truth. Real
   production columns rarely have deliberately contradictory metadata;
   they have *absent* or *generic* metadata. The misleading stratum is
   an upper-bound stress test, not a representative production case.
   Treat misleading-stratum numbers as "worst case" — expect real
   production to sit between `empty` and `helpful`.

## Verdict

**S1 NL prompt: SHAKEOUT POSITIVE — scale to n ≥ 100 and re-measure on
Gretel-EN before any SHIP decision.**

**S2 per-column descriptions: DO NOT SHIP.** Hypothesis refuted. Close
out in the next run's memo.

**S3 label narrowing: RESEARCH required.** File S3b (confidence-gated
variant) for follow-up. Current naive keyword hinter is not shippable.

**Overall SHIP / DO NOT SHIP: NOT DECIDED.** This run is a shakeout
on shakeout data. Per the research brief, the final verdict requires:
- ≥ 100 columns
- Gretel-EN as primary blind corpus
- McNemar p < 0.01
- Re-run at threshold 0.80

None of these gates are met yet.

## Recommendation

**Next session should:**

1. **Scale corpus** to 100+ columns by expanding `CONTEXT_TEMPLATES` to
   5+ templates per entity type, and/or repeating templates with
   different value slices. Target: n ≥ 100 / stratum.
2. **Add threshold sweep** (0.5, 0.70, 0.80) to match the Sprint 9 target.
3. **Add per-seed replication** (rng_seeds = [42, 7, 101]) for confidence
   intervals on the S1 delta.
4. **Add McNemar test** paired between baseline and S1 — per-column
   correct/incorrect vectors, exact McNemar p-value.
5. **File S3b research question**: confidence-gated label narrowing.
6. **Close S2** in queue.md with a DO NOT SHIP disposition.
7. **Wait for or provoke Gretel-EN ingestion.** Sprint 9 item
   `ingest-gretel-pii-masking-en-v1` is the blocker for a real SHIP
   verdict.

## Open questions

1. **Does S1 survive at threshold 0.80?** At 0.5, recall is near-perfect
   and the game is false-positive reduction. At 0.8, recall drops and
   S1's advantage may invert. Must measure.
2. **Is the S1 SSN regression (F1 0.33 → 0.00) real or n=3 noise?**
3. **Does S1 generalize across models (urchade v1 vs fastino v2)?**
   Currently only measured on fastino. If it doesn't help urchade v1,
   the finding is Sprint 9-gated.
4. **Does S1 trip any GLiNER input-length limits?** NL prompts are ~100
   characters longer than the `" ; "` variant. With chunk-size 50 × 30-
   char values ≈ 1500 chars per call, adding 200 chars of prefix is
   fine. But at chunk-size 50 × 200-char values (long addresses),
   prefixes may push over the model's max_len.

## Artifacts

- Harness: `tests/benchmarks/gliner_context/harness.py` + `__main__.py`
- Summary JSON: `docs/experiments/gliner_context/runs/20260413-2235/summary.json`
- Per-column JSON: `docs/experiments/gliner_context/runs/20260413-2235/per_column.json`
- Command to reproduce:
  ```
  cd /Users/guyguzner/Projects/data_classifier-gliner-context
  /Users/guyguzner/Projects/data_classifier/.venv/bin/python -m tests.benchmarks.gliner_context \
      --strategies baseline,s1_nl_prompt,s2_per_column_descriptions,s3_label_narrowing \
      --samples-per-column 30 --threshold 0.5 \
      --out docs/experiments/gliner_context/runs/<timestamp>
  ```
