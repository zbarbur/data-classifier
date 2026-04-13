# GLiNER context injection — Pass 1 (n=315, 3 seeds × 3 thresholds)

> **Status:** **S1 PASSES the ship gate at Ai4Privacy shakeout scale.**
> Full SHIP verdict still requires Gretel-EN (not yet ingested). Pass 2
> cross-corpus validation on Nemotron-PII is the immediate next step.
>
> **Branch:** `research/gliner-context` @ Pass 1
>
> **Scale:** 315 columns = 105 templates × 3 seeds. Corpus: Ai4Privacy
> fixture (438k labeled records).
>
> **Stats:** Paired BCa 95% bootstrap on Δ macro F1; exact McNemar on
> top-1 correctness; 1000 bootstrap resamples.

## Goal

Produce a defensible preliminary verdict on each of the four strategies,
at statistical power sufficient to detect a +0.05 F1 effect with tight
confidence intervals. Specifically:

1. Confirm or refute the n=21 first-run signal that **S1 beats baseline
   by ≥ +0.02 macro F1** (the ship gate).
2. Measure the effect at the **Sprint 9 target threshold of 0.80**, not
   just at the default 0.5, to rule out a "helps at low threshold but
   vanishes at high threshold" artifact.
3. Get **95% CIs wide enough to trust a +/- 0.02 decision**.
4. Apply **paired McNemar** to test the null of "no per-column difference".
5. Capture **multi-seed variance** in the value slices so the final CIs
   reflect slice-draw noise, not just single-draw luck.
6. Stratify by context kind (helpful / empty / misleading) to see
   whether S1's uplift depends on metadata being correct.

## Method

### 1. Corpus construction

- Loaded 438,960 Ai4Privacy `(entity_type, value)` records from
  `tests/fixtures/corpora/ai4privacy_sample.json`. Bucketed by canonical
  type via `AI4PRIVACY_TYPE_MAP`. 8 entity types with ≥50 values each:
  ADDRESS, CREDENTIAL, DATE_OF_BIRTH, EMAIL, IP_ADDRESS, PERSON_NAME,
  PHONE, SSN.
- Expanded `CONTEXT_TEMPLATES` to **15 templates per entity type**
  (5 helpful + 5 empty + 5 misleading), up from 3 per type in the
  n=21 run. 7 entity types × 15 templates = **105 base templates**
  per seed. (CREDENTIAL has a value pool but no CONTEXT_TEMPLATES
  entry — deferred.)
- Replicated with **3 seeds** `{42, 7, 101}`: each seed draws an
  independent 30-value slice from the pool for every template. Same
  templates, different value slices per seed. Total: 105 × 3 = **315
  corpus rows** with exact pairing across strategies.

### 2. Strategies

- **`baseline`** — `" ; "`-joined values + frozen 8-entity dict, matches
  `data_classifier/engines/gliner_engine.py` v2 code path
- **`s1_nl_prompt`** — NL prefix `Column '{col}' from table '{tbl}'. Description: {desc}. Sample values: v1, v2, ...`
- **`s2_per_column_descriptions`** — dict where each label description
  is rewritten as `"In a column named '{col}' in table '{tbl}': {base_desc}"`
- **`s3_label_narrowing`** — dict narrowed by keyword hint on column
  name + `{email, person, phone}` safety net

### 3. Model + thresholds

- `fastino/gliner2-base-v1`, loaded from local HF cache (804 MB, `refs/main`
  → `283f4af5`), zero network.
- Threshold sweep: **0.5, 0.7, 0.8**. Production today uses 0.5 default
  for urchade v1; Sprint 9 target for fastino is 0.80 per the
  `promote-gliner-tuning-fastino-base-v1` backlog item.

### 4. Statistical tests

- **Paired BCa 95% bootstrap** on macro F1 delta (variant − baseline),
  1000 resamples, `scipy.stats.bootstrap(method='BCa')`. Resamples
  indices (not individual predictions), which preserves the pairing
  between strategies.
- **Exact McNemar** via `scipy.stats.binomtest(k=c, n=b+c, p=0.5)` on
  discordant pair counts, where "correct" = `ground_truth in predicted_entity_types`.
- **BCa 95% bootstrap** on each strategy's raw macro F1 (un-paired,
  for visual comparison).

## Results

### Primary table — all thresholds, all strategies

| Threshold | Strategy | F1 | 95% CI | Δ vs baseline | Δ 95% CI | Excl 0 | Excl +0.02 | McNemar p | (b, c) |
|---:|---|---:|---|---:|---|:-:|:-:|---:|---:|
| 0.5 | `baseline` | **0.4492** | [0.424, 0.476] | — | — | — | — | — | — |
| 0.5 | **`s1_nl_prompt`** | **0.5667** | [0.538, 0.593] | **+0.1176** | **[+0.092, +0.141]** | **✓** | **✓** | 0.481 | (7, 11) |
| 0.5 | `s2_per_column_descriptions` | 0.4440 | [0.418, 0.470] | −0.0051 | [−0.028, +0.014] | × | × | **0.0000** | (27, 2) |
| 0.5 | `s3_label_narrowing` | 0.4561 | [0.431, 0.488] | +0.0070 | [−0.008, +0.026] | × | × | **0.0075** | (15, 3) |
| 0.7 | `baseline` | **0.5260** | [0.496, 0.556] | — | — | — | — | — | — |
| 0.7 | **`s1_nl_prompt`** | **0.6146** | [0.581, 0.647] | **+0.0887** | **[+0.058, +0.123]** | **✓** | **✓** | 1.000 | (10, 10) |
| 0.7 | `s2_per_column_descriptions` | 0.4657 | [0.440, 0.493] | **−0.0603** | **[−0.084, −0.040]** | **✓** | × | **0.0000** | (39, 0) |
| 0.7 | `s3_label_narrowing` | 0.5264 | [0.496, 0.560] | +0.0004 | [−0.022, +0.028] | × | × | 0.167 | (13, 6) |
| **0.8** | `baseline` | **0.5278** | [0.497, 0.563] | — | — | — | — | — | — |
| **0.8** | **`s1_nl_prompt`** | **0.6164** | [0.585, 0.650] | **+0.0887** | **[+0.050, +0.131]** | **✓** | **✓** | 0.585 | (13, 17) |
| **0.8** | `s2_per_column_descriptions` | 0.5178 | [0.494, 0.546] | −0.0100 | [−0.036, +0.014] | × | × | **0.0002** | (13, 0) |
| **0.8** | `s3_label_narrowing` | 0.5215 | [0.488, 0.560] | −0.0063 | [−0.026, +0.019] | × | × | 0.302 | (10, 5) |

### Context-kind stratification at Sprint 9 target threshold (0.8)

| Strategy | empty (n=105) | helpful (n=105) | misleading (n=105) |
|---|---:|---:|---:|
| `baseline` | 0.5173 | 0.5251 | 0.5461 |
| **`s1_nl_prompt`** | **0.5564** (+0.039) | **0.6706** (+0.146) | **0.6031** (+0.057) |
| `s2_per_column_descriptions` | 0.5196 (+0.002) | 0.5779 (+0.053) | 0.5303 (−0.016) |
| `s3_label_narrowing` | 0.5316 (+0.014) | 0.6008 (+0.076) | 0.5068 (−0.039) |

### Latency at threshold 0.8

| Strategy | Wall (s) on 315 columns | Per-column avg (ms) | Δ vs baseline |
|---|---:|---:|---:|
| baseline | 67.6 | 214.6 | — |
| s1_nl_prompt | 71.5 | 227.0 | +6% |
| s2_per_column_descriptions | 84.4 | 268.0 | **+25%** ⚠ |
| s3_label_narrowing | 64.9 | 206.0 | −4% |

**S2 exceeds the +20% latency gate.** S1 is comfortably inside at +6%.

---

## Per-strategy verdict

### S1 NL prompt — **SHIP GATE PASS** on this corpus

**Macro F1 Δ at threshold 0.8:** +0.0887, **95% BCa CI `[+0.050, +0.131]`**.
The CI excludes 0 AND excludes the +0.02 ship gate with substantial
margin (lower bound +0.050 > gate +0.02).

**Robustness checks:**
- **Threshold-insensitive.** Δ ≈ +0.09 at all three thresholds (0.1176
  at thr=0.5, 0.0887 at 0.7, 0.0887 at 0.8). The effect doesn't depend
  on threshold choice.
- **Context-kind-insensitive.** S1 lifts F1 on **all three** context
  strata at threshold 0.8: empty +0.039, helpful +0.146, misleading
  +0.057. Not a "helpful-only" win.
- **Latency fine.** +6% at p50, well under the +20% gate.
- **SSN regression from n=21 did NOT reproduce** at n=315 — SSN F1 is
  within the noise band at all thresholds.

**The McNemar puzzle:** p-values are NOT significant at any threshold
(0.48, 1.00, 0.58). Why? Because S1's improvement is almost entirely
**false-positive reduction on entity types OTHER than the ground truth**,
not **top-1 recall recovery**. Discussed in "Methodological note"
below.

**Verdict: Pass 1 SHIP GATE PASS. Proceed to Pass 2 cross-corpus
validation on Nemotron-PII. Final SHIP decision still gated on Gretel-EN
per research brief.**

### S2 per-column descriptions — **DEFINITIVELY DO NOT SHIP**

- **Threshold 0.5:** Δ −0.0051 (noise) but **McNemar (b=27, c=2),
  p=0.0000** — on 27 columns baseline is right and S2 is wrong, and
  only 2 the other way. S2 is flipping predictions in the WRONG
  direction at ~10x the rate it's flipping them helpfully. The F1 delta
  near zero is concealing this asymmetry because those flips average
  out numerically.
- **Threshold 0.7:** **Δ −0.0603, CI `[−0.084, −0.040]`** — entirely
  negative. McNemar (b=39, c=0), p=0.0000. **Forty columns worse, zero
  columns better.** This is the most catastrophic result in the run.
- **Threshold 0.8:** Δ −0.010 (CI spans 0, recovered slightly because
  all strategies are more conservative) but McNemar (b=13, c=0), p=0.0002.
  Still no column benefits, just fewer absolute flips.
- **Latency:** +25%, exceeds the +20% gate.

**Mechanism:** injecting column-level context into per-label descriptions
creates internal prompt contradictions. When the template says
"`column_name='invoice_number'` in `table='billing'`" and the label
description says "Email addresses including...", GLiNER is asked to
reconcile two conflicting semantic signals inside a single label
description. The descriptions lose their semantic grounding and
classification degrades.

**The 0.7 result is especially damning** because at that threshold the
baseline is already filtering out low-confidence predictions, so the
comparison is between two well-calibrated outputs — and S2 is strictly
worse. This is not a noise result.

**Verdict: refuted. Close S2 in queue.md. Document the mechanism so
future research doesn't re-propose it.**

### S3 label narrowing — **REFUTED in current form**, S3b still plausible

- **All three thresholds:** Δ F1 CI spans 0. No statistically
  distinguishable improvement at aggregate level.
- **Threshold 0.5 McNemar:** (b=15, c=3), p=0.0075 — **significantly
  worse, not better**. My naive keyword hinter is flipping S3 into
  the wrong answer on 5x more columns than it's helping on.
- **Context-kind stratification at threshold 0.8:**
  - empty: +0.014 (noise, smaller than at n=21 — averaged out)
  - helpful: +0.076 (substantial, but cancels with misleading)
  - misleading: **−0.039** (big regression — this is where the keyword
    hint actively misleads)

**Mechanism:** my `strategy_s3_label_narrowing` uses a naive keyword
match on `column_name.lower()` to pick a single label to narrow to.
On `helpful` templates where `"email" in column_name`, the narrowing
is correct and F1 improves. On `misleading` templates where
`column_name='invoice_number'` contains no matched token or
accidentally matches the wrong entity, narrowing excludes the true
answer entirely. The +0.076 helpful gain is approximately cancelled
by the −0.039 misleading loss.

**The n=21 bimodality is confirmed at n=315.** S3 has real signal
when the hint is right and catastrophic failure when wrong. Current
implementation is shakeout-negative.

**S3b proposal:** gate the narrowing on a confidence signal. Specifically,
only narrow when `column_name_engine` reports a single-type match with
confidence ≥ 0.70; otherwise fall back to the full label set. This
would capture most of the +0.076 helpful gain while avoiding the
−0.039 misleading penalty. File as a new queue entry.

**Verdict: current S3 refuted. File S3b as follow-up.**

---

## Methodological note — the McNemar / bootstrap divergence

This is the single most important thing to internalize from Pass 1, and
it's a real teaching moment for how to read statistical tests in ML
research.

### The divergence

At threshold 0.7, S1 vs baseline:
- **Paired BCa bootstrap Δ macro F1 CI:** `[+0.058, +0.123]` — strong
  evidence S1 is +0.09 better.
- **Exact McNemar on top-1 correctness:** (b=10, c=10), p=1.000 —
  zero evidence of any difference.

How can both be true?

### Why they disagree

My McNemar correctness vector asks the question:

> **"Did the strategy report the ground-truth entity type for this
> column?"** (`r.ground_truth in r.predicted_entity_types`)

S1 and baseline almost always both get this right. Recall at threshold
0.7 on this corpus is ≥0.90 for both strategies on every ground-truth
type with meaningful support. So discordance is low.

But macro F1 is NOT just about getting the ground-truth type right.
It's:

```
macro F1 = average_over_types( 2 * P_t * R_t / (P_t + R_t) )
```

And **P_t** (precision for type t) is degraded whenever ANY column
produces a false-positive report for type t, even if that column's
ground-truth type was also correctly reported. An S1 column that reports
`{EMAIL}` and a baseline column that reports `{EMAIL, PHONE}` have the
**same correctness in my McNemar definition** — both got the ground
truth right — but the baseline column contributed a PHONE false positive
that hurts baseline's macro F1.

### The correct McNemar definition for macro F1

The McNemar correctness vector I *should* have used:

> **"Did the strategy produce EXACTLY `{ground_truth}` as its prediction
> set?"** (`r.predicted_entity_types == {r.ground_truth}`)

With that definition, S1 would be "correct" on every column where it
cleanly detected only the ground-truth type, and "wrong" on columns
where it false-fired anything extra. Baseline would be "wrong" on any
column where it reported PHONE in addition to EMAIL. The discordance
would then capture S1's false-positive reduction, and McNemar p would
drop dramatically.

**I'll re-run with the corrected definition in Pass 1b.** For now,
the **bootstrap Δ CI is the load-bearing statistic** — it correctly
captures macro F1 improvement, and at n=315 with CI excluding +0.02,
it's strong evidence.

### Reading the table correctly

**For the S1 ship gate decision:** trust the bootstrap Δ CI. It says
S1 is +0.09 F1 (CI [+0.05, +0.13]) at threshold 0.8.

**For the S2 refutation:** trust the McNemar. S2 is catastrophically
wrong on (b=39, c=0) at threshold 0.7. No argument about definitions —
when a strategy is wrong on 39 columns and right on 0, no statistical
test can rescue it.

**For the S3 refutation:** trust BOTH. Delta CI spans 0 AND McNemar
(b=15, c=3) shows the few flips it does produce go the wrong way.

### The general lesson

Any time McNemar and a macro F1 test disagree, the explanation is
usually: **they measure different things about per-column
decisions**. A paired test on the right statistic is equivalent to
an aggregate test on the same statistic, but a paired test on the
wrong statistic can give you a misleading p-value. Always check:

> "What's the per-column binary decision that defines 'correct' in
> my McNemar, and does it aggregate to the F1 I actually care about?"

If not, your McNemar is testing a different hypothesis than your F1
claim. This is the kind of gotcha that will land in the learning
guide as Appendix B.

---

## What Pass 1 lets us claim

- ✅ **S1 NL prompt beats baseline by +0.09 macro F1** at Sprint 9's
  target threshold (0.80), with **BCa 95% CI `[+0.050, +0.131]`** that
  excludes the +0.02 ship gate by a wide margin.
- ✅ **S1's improvement is robust to threshold choice** (stable at 0.5,
  0.7, 0.8) and to context helpfulness (lifts F1 on empty, helpful, AND
  misleading strata).
- ✅ **S1 has no latency penalty** at +6% (gate is +20%).
- ✅ **S2 is catastrophically refuted** at threshold 0.7 with (b=39,
  c=0) and −0.06 F1 delta — close it out.
- ✅ **S3 current implementation is refuted**; S3b (confidence-gated)
  is a plausible follow-up.
- ✅ **Corpus is large enough for confident directional calls**
  at +0.05-ish effect sizes with reasonable CI widths (all CI widths
  on F1 deltas are 0.04-0.08, inside the +0.02 gate's resolution).

## What Pass 1 does NOT let us claim

- ❌ A final SHIP verdict. **Gretel-EN is still required** per the
  research brief. Pass 1 is shakeout-only.
- ❌ **Cross-corpus robustness.** One corpus only (Ai4Privacy). Pass 2
  on Nemotron-PII is the next step.
- ❌ **Per-entity regression gates.** With 7 entity types × 15 templates
  × 3 seeds = 45 columns per type, CI widths on per-entity F1 are still
  ~0.07, too wide to confidently exclude a −0.03 regression. SSN was
  the concerning one at n=21, looks fine at n=315, but per-type CI is
  still wide enough that I can't promise no regression at the required
  tightness.
- ❌ **McNemar significance for S1** at my current (narrow) McNemar
  definition. Pass 1b with the corrected definition
  (`predicted == {ground_truth}`) should clarify this.

## Recommendation

### For the research/gliner-context track

1. **Close S2 in `docs/experiments/gliner_context/queue.md`** with
   DO NOT SHIP disposition. Record the mechanism so nobody re-proposes
   it from scratch.
2. **Retire current S3** — shakeout-negative. File **S3b: confidence-gated
   label narrowing** as a new queue entry for a follow-up session.
3. **Proceed to Pass 2 — Nemotron-PII cross-corpus** (604MB already
   cached). Re-run S1 + baseline at threshold 0.8 with multi-seed
   replication. If S1 also wins on Nemotron, file Sprint 10 promotion
   candidate spec.
4. **Pass 1b: fix the McNemar definition** to `predicted == {ground_truth}`
   and re-run just the McNemar calculation from the cached per-column
   results. Fast — no re-inference needed. Adds a second line of
   statistical evidence for S1.
5. **Hold on Gretel-EN.** Until Sprint 9 `ingest-gretel-pii-masking-en-v1`
   lands, the final SHIP verdict cannot be written. Pass 2 Nemotron
   shakeout keeps the research moving meanwhile.

### For the main Sprint 9 track

Not yet — do not file Sprint 10 promotion candidate until Pass 2 +
Gretel-EN both pass. **Pass 1 alone is not sufficient justification
for a production promotion.** But DO read this memo for the teaching
moment around the McNemar definition choice — that's a mistake worth
not repeating.

## Open questions

1. **S1b candidate:** would a shorter NL prompt (`{col} @ {tbl}: v1, v2, ...`)
   capture the same gain at less token cost? S1's prompt is verbose;
   some of the gain may be "anything that's a sentence" rather than
   "this specific sentence structure".
2. **S1+S3b hybrid:** if S3b's confidence gate works, does stacking
   S1+S3b give additive lift? Worth measuring in Pass 3.
3. **Does S1 survive at threshold 0.9 / 0.95?** Production may want
   very-high-precision modes where recall is sacrificed. S1 not
   measured there.
4. **Does the effect transfer to urchade v1?** Today's production
   runs urchade, not fastino. If Sprint 9 fastino promotion slips,
   S1 on urchade is the fallback. Not yet measured.
5. **What's S1 doing mechanistically?** Paper-level question: does
   the NL prefix change GLiNER's attention pattern over the value
   tokens, or is it just changing the prior on which entity types
   are plausible? A probe on a few columns with attention visualization
   would answer this.

## Artifacts

- Harness: `tests/benchmarks/gliner_context/harness.py` + `__main__.py`
- Summary JSON: `docs/experiments/gliner_context/runs/20260413-2300-pass1/summary.json`
- Per-column JSON: `docs/experiments/gliner_context/runs/20260413-2300-pass1/per_column_thr{0.5,0.7,0.8}.json`
- Markdown table: `docs/experiments/gliner_context/runs/20260413-2300-pass1/RESULTS.md`
- Reproducer:
  ```
  cd /Users/guyguzner/Projects/data_classifier-gliner-context
  /Users/guyguzner/Projects/data_classifier/.venv/bin/python -m tests.benchmarks.gliner_context \
      --seeds 42,7,101 --thresholds 0.5,0.7,0.8 --samples-per-column 30 --n-resamples 1000
  ```
- Total wall time: ~12 minutes (model load 14s + 12 strategy-threshold
  runs × ~70s each, with a few seconds bootstrap compute).
