# Sprint 12 Item #4 — Directive Promotion Investigation

**Date:** 2026-04-16
**Branch:** `sprint12/main`
**Scope:** Investigation trajectory from "promote meta-classifier v3 to
directive" to "discover train/serve wiring bug" to "measure true
baseline" to "directive A/B spike" to "scope the prereq chain for
Item #4 acceptance criteria." Establishes Rule A (pure shadow as
directive) as the validated dispatch design and identifies Items #1
and #2 as the remaining gap for **in-distribution** AC, and flags the
Sprint 12 safety audit as the gating decision point for
**out-of-distribution** AC.

---

## Post-merge amendment (2026-04-16)

This memo was initially drafted before the `sprint12/safety-audit-prep`
branch merged into main (PR #14, merge commit `1b9a557`). That branch
added three items the original draft did not account for:

1. **LOCO macro F1 ≥ 0.30** as a new hard acceptance criterion on
   Item #4 (commit `2d71627`). This is a 2x improvement over the
   honest v3 LOCO estimate of ~0.17 and is the primary
   out-of-distribution safety check.
2. **Heterogeneous column regression test** as a new acceptance
   criterion on Item #4 (same commit). Directive must not emit
   degenerate constant-entity predictions on mixed-content columns.
3. **New dependency: `sprint12-shadow-directive-promotion-gate-safety-analysis-memo`**
   (commit `9faab99`). This is a 3-experiment spike (LR-vs-MLP
   capacity audit, hard-gating architecture audit, heterogeneous
   log-column fixture) that produces a GREEN / YELLOW / RED verdict
   consumed by the promotion-gate item as a go/no-go input.

The revised sections below (§6, §7, §11) reflect this expanded
scope. The original draft's investigation narrative (§1–§5, §8–§10)
is unchanged and remains accurate.

---

## TL;DR

1. **Bug fix first.** Sprint 11 Phase 7 added the
   `heuristic_dictionary_word_ratio` feature to the meta-classifier
   training path but never wired it into `predict_shadow`. The model was
   trained with the feature meaningful and deployed with it silently
   zeroed at inference — a textbook train/serve skew. Fixed in commit
   `43740e4` with a 4-line addition to `MetaClassifier.predict_shadow`
   and pinned by 3 parity tests in
   `tests/test_meta_classifier_inference_parity.py`.
2. **True corrected-v3 baseline (post-fix).** Shadow
   `cross_family_rate` 0.0663, `family_macro_f1` 0.9242,
   within-family mislabels 133 (down from 322, −58%). The headline
   fused metric regressed slightly (0.0585 → 0.0663) because the bug
   was *helping* v3 on the combined classification + abstention
   question: with the feature zeroed, the model was less confident on
   credential-shaped NEGATIVE columns and abstained more.
3. **Classification quality is better than the fused metric says.**
   Option B split scoring (classification-only on PII rows,
   abstention separately as a binary question) shows corrected-v3
   classification macro-F1 = 0.9712 and cross-family rate = 0.0337 on
   PII rows alone. The fused metric conflates "picked the wrong
   family" with "correctly said nothing is here" and penalizes the
   latter.
4. **Live cascade is structurally worse at NEGATIVE than meta-classifier.**
   Live over-flags on NEGATIVE columns at 83% (regex fires on 98% of
   NEGATIVE columns), meta-classifier at 40%. 37.5% of live
   cross-family errors are structurally unrecoverable because the
   live path has no way to emit NEGATIVE.
5. **Directive A/B spike validates Rule A.** Pure-shadow-as-directive
   (Rule A: meta-classifier's top family becomes the answer, ignore
   live cascade findings when they disagree) dominates live on 8 of
   9 families; only CREDENTIAL regresses (−0.0232). Rule A hits
   `family_macro_f1` 0.9242 (> 0.92 ✓) and `cross_family_rate`
   0.0663 (target < 0.040 ✗).
6. **Item #4 in-distribution AC needs the prereq chain.** Rule A
   alone closes ~80% of the gap to the original in-distribution
   acceptance targets. The last 20% requires Item #1
   (`validator_rejected_credential` feature) and Item #2
   (`has_dictionary_name_match` feature). Ai4privacy openpii-1m
   ingest is **deferred** to reduce Sprint 12 scope.
7. **Item #4 out-of-distribution AC is a separate question.** The
   new LOCO ≥ 0.30 bar (vs v3's honest ~0.17 baseline) is not
   addressed by Items #1 and #2 — those features add
   *in-distribution* discrimination. Whether a flat LR classifier
   can reach LOCO 0.30 with two new features is the central
   question the safety audit answers. If the safety audit returns
   RED, Sprint 12 ships v0.12.0 with shadow-only (including Items
   #1/#2 as shadow improvements) and the directive flip defers to
   Sprint 13.
8. **Dispatch design: Rule A, not Rule B.** Rule B (live first,
   shadow fallback on low-confidence or conflict) was considered and
   rejected — it inherits live cascade's structural NEGATIVE blind
   spot because the fallback only triggers when live emits
   *something*, and for NEGATIVE columns live emits confidently
   wrong findings from the regex authority=5 engine.

---

## 1. The bug fix — train/serve skew on `heuristic_dictionary_word_ratio`

### Diagnosis

Sprint 11 Phase 7 (commit `86a10e3`) added
`heuristic_dictionary_word_ratio` as feature index 46 in the v3
feature schema. The training-time row builder at
`tests/benchmarks/meta_classifier/extract_features.py:178` computes
the ratio from `column.sample_values` and passes it through
`extract_features(..., heuristic_dictionary_word_ratio=dict_ratio)`.
The shadow inference path in
`data_classifier/orchestrator/meta_classifier.py` did not —
`predict_shadow` computed `_distinct_ratio` and `_avg_length_normalized`
but never called `compute_dictionary_word_ratio`, so the feature
reached the model as a silent zero.

Verified with:

```
git log -S "heuristic_dictionary_word_ratio" -- \
    data_classifier/orchestrator/
# (zero commits — the feature was never wired into the orchestrator)

git show 86a10e3 --stat
# Only meta_classifier.py, extract_features.py, content_words.json,
# and test files touched. predict_shadow was not.
```

The feature was meaningful in training and zeroed in serving — a
textbook train/serve skew. Because v3 was still shadow-only, the
bug was invisible until we started treating shadow predictions as
ground truth for the Item #4 promotion spike.

### Fix

Commit `43740e4` adds the missing 4 lines to `predict_shadow` in
`data_classifier/orchestrator/meta_classifier.py:308-325`:

```python
values = sample_values or []
distinct = _distinct_ratio(values)
avg_len = _avg_length_normalized(values)
# Sprint 11 Phase 7 feature, wired into shadow inference here
# so the training row ... and the live predict_shadow path compute
# the same index-46 value for the same column.
from data_classifier.engines.heuristic_engine import compute_dictionary_word_ratio
dict_ratio = compute_dictionary_word_ratio(values)
full_vec = extract_features(
    findings,
    heuristic_distinct_ratio=distinct,
    heuristic_avg_length=avg_len,
    heuristic_dictionary_word_ratio=dict_ratio,
)
```

The local import mirrors the existing `_distinct_ratio` pattern and
avoids an import cycle between `orchestrator` and `engines`.

### Parity tests

Three tests in `tests/test_meta_classifier_inference_parity.py` pin
the contract: every column-level statistic the training path threads
must also be threaded through `predict_shadow`, computed from the
same `sample_values` list. The tests spy on the module-level
`extract_features` via `monkeypatch.setattr` and assert that each
expected kwarg is present in the captured call. This gives us a
regression guard against symmetric bugs where a future column stat
is added to training and forgotten at inference.

---

## 2. Corrected-v3 baseline (post-fix)

Full benchmark output in
`docs/research/meta_classifier/bug_investigations/sprint12_dict_word_ratio_bugfix_benchmark.json`.

| Metric | Pre-fix (stale, shipped) | Post-fix (true v3) | Delta |
|---|---|---|---|
| shadow `cross_family_rate` | 0.0585 | 0.0663 | **+0.0078** (worse) |
| shadow `family_macro_f1` | 0.9286 | 0.9242 | **−0.0044** (worse) |
| within-family mislabels | 322 | 133 | **−189** (better) |

The headline metrics *regressed* but the within-family mislabel count
collapsed. Reading: with the feature zeroed, v3 was less confident on
credential-shaped NEGATIVE columns and defaulted to abstention
(emitting NEGATIVE-family instead of CREDENTIAL/PAYMENT_CARD/etc.),
which happened to look good under the fused metric because the
fused metric treats empty findings on NEGATIVE-truth as a correct
no-op. With the feature restored, v3 is more confident and commits
to family assignments — some of which are wrong, driving the fused
metric down even as the underlying classification quality improved.

This is why we stopped trusting the fused metric alone and went to
split scoring.

---

## 3. Option B split scoring

The fused Sprint 11 metric answers two questions at once:
**classification** ("when the model emits a finding, did it pick the
right family?") and **abstention** ("for NEGATIVE-truth columns, did
the model correctly say nothing?"). These are independent capabilities
and should be measured independently.

Read-only spike script at `/tmp/option_b_spike.py` re-scores the
committed predictions JSONL with:

- **Classification metrics:** computed only on PII rows
  (`ground_truth != "NEGATIVE"`) and only on predictions where the
  model did not abstain. The question: "Of the real PII columns the
  model committed to, how often did it land in the right family?"
- **Abstention metrics:** computed on all rows, binary. The question:
  "Does the model correctly say 'this is nothing' for NEGATIVE
  columns, and correctly *not* say that for PII?"

For shadow, abstention was operationalized two ways: **legacy**
(`shadow_predicted == "NEGATIVE"`) and **proposed**
(`shadow_confidence < threshold`, swept 0.30–0.80).

**Results on corrected-v3:**

| Path | classification macro-F1 | cross_family_rate (PII only) | notes |
|---|---|---|---|
| Live (directive) | 0.8733 | 0.1104 | over-emits everywhere |
| Shadow (legacy abstention) | 0.9712 | 0.0337 | — |
| Shadow (threshold 0.60) | 0.9712 | 0.0337 | no change; legacy ≈ confidence |

Shadow classification quality is substantially better than the fused
metric suggested: **0.9712 macro-F1**, **0.0337 cross-family rate on
PII rows only**. The Sprint 12 target of `cross_family_rate < 0.030`
is within reach on classification alone — the gap is in abstention
quality (NEGATIVE F1).

---

## 4. Live cascade vs meta-classifier on NEGATIVE

Direct count from the bugfix benchmark JSONL:

| Path | % of NEGATIVE columns over-flagged | % of NEGATIVE columns correctly abstained |
|---|---|---|
| Live (directive) | 83% | 17% |
| Shadow (meta v3 corrected) | 40% | 60% |

**Why live is structurally worse.** The live cascade has no mechanism
to emit NEGATIVE. The regex engine (authority=5) fires on 98% of
NEGATIVE columns because real-world NEGATIVE corpora (names,
addresses, text, numbers) contain many regex-matching substrings. The
live path's 7-pass merge pipeline can down-rank and suppress, but it
cannot *abstain* — once any engine emits a finding, the pipeline will
produce *some* family as the answer. 37.5% of live's cross-family
errors are in this unrecoverable category: a NEGATIVE column where
live emits a confidently-wrong PII finding and has no way to retract.

Only the shadow meta-classifier can emit NEGATIVE, because it is
trained with NEGATIVE as a family in the 13-family taxonomy. This is
the architectural reason Item #4 exists at all: the directive path
needs access to the shadow's NEGATIVE capability.

---

## 5. Directive A/B spike — Rule A vs Live

Spike script at `/tmp/directive_ab_spike.py`. Reads the bugfix
benchmark JSONL and re-scores under three dispatch rules:

- **Live:** current production dispatch; live findings are the answer.
- **Rule B:** live first, shadow fallback when live confidence < 0.80
  OR live and shadow disagree on family.
- **Rule A:** pure shadow as directive; meta-classifier's top family
  becomes the answer regardless of live findings.

Scoring matches the canonical `_compute_family_metrics` in
`tests/benchmarks/family_accuracy_benchmark.py:135-191` byte-for-byte
(including the `and gt_fam` clause that excludes the both-empty case
from TP counting).

### Aggregate results

| Rule | cross_family_rate | family_macro_f1 | NEGATIVE F1 | notes |
|---|---|---|---|---|
| Live | 0.1352 | 0.8461 | 0.0000 | live cannot emit NEGATIVE |
| Rule B | 0.1093 | 0.8721 | 0.2814 | falls back too rarely |
| **Rule A** | **0.0663** | **0.9242** | **0.6105** | validated |

### Per-family delta (Rule A − Live)

| Family | Live F1 | Rule A F1 | Δ |
|---|---|---|---|
| CONTACT | 0.8533 | 0.9120 | +0.0587 |
| CREDENTIAL | 0.9401 | 0.9169 | **−0.0232** |
| CRYPTO | 0.9302 | 0.9630 | +0.0328 |
| DATE | 0.9655 | 0.9825 | +0.0170 |
| FINANCIAL | 0.8947 | 0.9375 | +0.0428 |
| GOVERNMENT_ID | 0.9697 | 0.9811 | +0.0114 |
| HEALTHCARE | 0.9333 | 0.9697 | +0.0364 |
| NETWORK | 0.9524 | 0.9756 | +0.0232 |
| PAYMENT_CARD | 1.0000 | 1.0000 | 0.0000 |
| NEGATIVE | 0.0000 | 0.6105 | **+0.6105** |

Rule A wins 8 of 9 families with comparable or better F1, unlocks
NEGATIVE entirely, and loses only CREDENTIAL (−0.023). The CREDENTIAL
regression is directly addressed by Item #1 (`validator_rejected_credential`),
which gives the model a positive signal to defer to NEGATIVE on
placeholder-heavy credential columns.

---

## 6. Item #4 acceptance criteria — gap analysis

Item #4 has **seven** acceptance criteria after the PR #14 merge: the
original four in-distribution family-metric bars plus three new
out-of-distribution and architecture bars. Rule A status against
each is below.

### In-distribution bars (original)

| AC | Target | Rule A actual | Status |
|---|---|---|---|
| `cross_family_rate` | < 0.040 | 0.0663 | **gap −0.026** |
| `family_macro_f1` | ≥ 0.92 | 0.9242 | ✓ |
| NEGATIVE F1 | ≥ 0.70 | 0.6105 | **gap −0.09** |
| CONTACT precision | ≥ 0.93 | 0.882 | **gap −0.05** |

Rule A passes 1 of 4 in-distribution bars. The other three fail by
5–15% of their target range. The prereq items address these gaps
directly:

- **Item #1 (`validator_rejected_credential`)** — projected NEGATIVE
  recall 0.478 → 0.75, shadow `cross_family_rate` ~0.059 → ~0.045
  (per Sprint 11 Phase 10 memo projection; see caveat below).
- **Item #2 (`has_dictionary_name_match`)** — projected CONTACT
  precision 0.882 → 0.95, shadow `cross_family_rate` ~0.059 → ~0.035.
- **Combined projection:** `cross_family_rate` ~0.030, NEGATIVE F1
  ≥ 0.70, CONTACT precision ≥ 0.93 — right at the Sprint 12
  in-distribution targets.

**Projection caveat.** The Sprint 11 projections were computed on
pre-bug-fix v3 (feature 46 zeroed). With the bug fixed, the baseline
is 0.0663 not 0.059, so the absolute deltas shift. The *relative*
contribution of the new features should hold — each feature addresses
a different failure class (placeholder-credential false positives for
Item #1, PERSON_NAME catch-all drain for Item #2) — but we should
re-measure rather than trust the projection.

### Out-of-distribution and architecture bars (new, PR #14)

| AC | Target | Current baseline | Status |
|---|---|---|---|
| LOCO macro F1 (M1 StratifiedGroupKFold) | ≥ 0.30 | ~0.17 (v3) | **gap −0.13 (~2x)** |
| Heterogeneous column regression | no single-high-confidence collapse on 50-row log-line fixture | not measured | unknown |
| Safety audit verdict | GREEN or YELLOW-with-mitigations | not run | unknown |

**LOCO gap is not addressed by the feature additions.** Items #1 and
#2 add column-level signals that should improve in-distribution
discrimination on placeholder credentials and name-heavy columns.
Neither addresses shortcut learning on corpus-specific priors — which
is what the LOCO methodology measures (train on N−1 corpora, test on
held-out corpus). The Sprint 9 learning memo at
`docs/learning/sprint9-cv-shortcut-and-gated-architecture.md` §5
argued that a flat classifier has an information ceiling on LOCO
because it cannot distinguish "this column is a credential" from
"this column is from the bigbase-corpus shard twin of a credential
training example." The 3-branch gated architecture in Sprint 13 is
designed to close exactly this gap.

**Working hypothesis (to be tested by the safety audit):** Items #1
and #2 move the in-distribution metric into range, but LOCO stays
at ~0.17 ± 0.03. If that hypothesis holds, the safety audit returns
RED, and Sprint 12 directive flip defers to Sprint 13.

**Counter-hypothesis (also plausible):** the validator-rejection
signal is strongly *corpus-invariant* (a placeholder credential
looks the same in any corpus), and the dictionary-name-match signal
is also *corpus-invariant* (a first name is a first name). If the
new features shift LOCO substantially — say to 0.22–0.25 — the
safety audit could return YELLOW with mitigations (e.g.,
confidence-threshold fallback to live cascade for low-confidence
predictions) and Sprint 12 ships directive with a narrower scope.

The safety audit is the measurement that decides between these
hypotheses. It is not optional — it is the single gating experiment
for the directive flip.

### Heterogeneous column gap

The heterogeneous AC is orthogonal to LOCO. A flat classifier cannot
represent "this log column contains emails AND API keys AND phone
numbers" because `ClassificationFinding` is single-valued and the
meta-classifier emits one top-family label. A log column with 20%
emails, 30% API keys, 50% free text will collapse to whichever class
has the highest softmax — and that collapse is silent.

The synthetic 50-row log-line fixture in the safety audit tests
whether v3 collapses with high confidence (>0.8) across the fixture.
If yes, the flat architecture is silently broken on this case and
the safety audit is at minimum YELLOW with a mitigation requirement.
The Sprint 13 gated architecture's `HeterogeneousColumnFinding` type
is designed to represent mixed-content columns properly.

This AC is **not addressed by Items #1 and #2 at all** — they add
column-level features, which make the single-valued collapse *more
confident*, not less.

---

## 7. Decision

### Chosen: Option 1 — follow the prereq chain, then safety audit, then decide

Ship Items #1 and #2 as feature additions (schema bump v3 → v4 → v5),
retrain on the existing 9870-row corpus, run the directive A/B spike
for in-distribution AC, **then run the safety audit for
out-of-distribution AC**, then land Item #4 only if the safety audit
returns GREEN or YELLOW-with-mitigations. Two decision gates, not
one. If either gate fails, Sprint 12 ships v0.12.0 with shadow-only
(Items #1/#2 as shadow improvements) and the directive flip defers
to Sprint 13.

### Why two gates, not one

The original four in-distribution AC and the new LOCO / heterogeneous
/ safety-audit AC measure **different things**. Items #1 and #2 are
targeted at the in-distribution gaps and are expected to move those
metrics substantially. Neither is expected to move LOCO or the
heterogeneous case — see §6 for why. Conflating the two gates would
risk:

- Shipping directive after passing in-distribution AC while LOCO
  silently stays at 0.17, giving BQ customers catastrophic
  out-of-distribution quality on new data sources
- Wasting the Phase 6 orchestrator-wiring and shadow-deletion effort
  if the safety audit returns RED — the orchestrator change is
  irreversible within a sprint, so running it speculatively before
  the safety verdict is poor sequencing

Separating the gates lets Items #1 and #2 ship as shadow-only
improvements regardless of the audit outcome, and defers the
architectural decision to a measurement.

### Rejected alternatives

- **Ship Rule A immediately with known AC failures.** Would land a
  regression on CREDENTIAL (−0.023 F1) without the compensating
  features, fails 3 of 4 in-distribution AC on paper, and does
  nothing about the LOCO / heterogeneous / safety-audit bars. Not
  acceptable for a quality gate migration.
- **Corrected-v3 as-is, skip the features.** Same problem — AC fail
  on both in-dist and out-of-dist bars.
- **C-retrain candidates (C=1, C=10, C=100).** None dominated
  corrected-v3 on classification quality. Regularization sweep is
  not the lever; the missing feature signal is.
- **Ai4privacy openpii-1m ingest in Sprint 12.** 4.61GB download, 19
  labels with 5 unscoped, scope risk high. Deferred to Sprint 13. If
  the Phase 5 safety audit returns RED on the current corpus and
  ai4privacy would plausibly close the LOCO gap (multilingual
  training signal, 1.4M rows of corpus diversity), we can reconsider
  — but that reconsideration is itself a Sprint 13 decision, not a
  mid-Sprint-12 pivot.
- **Rule B (live-first with shadow fallback).** Inherits live's
  structural NEGATIVE blind spot because fallback only fires when
  live emits *something*, and NEGATIVE columns are exactly where
  live emits confidently wrong findings. Measured
  `cross_family_rate` 0.1093 is mid-way between Live and Rule A —
  Rule A is the dominating design.
- **Run the safety audit before Items #1/#2 land.** Considered, but
  the safety audit is specified to run on the post-Sprint-12 v4/v5
  model, not on the pre-Sprint-12 v3 baseline. Running it on v3
  tells us nothing about whether the new features close the LOCO
  gap; running it on v5 is the only useful measurement. Items #1
  and #2 land first.
- **Skip the safety audit and ship on in-distribution AC alone.**
  Would inherit the LOCO gap silently and expose BQ customers to
  out-of-distribution regressions. The safety audit explicitly
  exists to prevent this — skipping it would undo PR #14's whole
  purpose.

### Revised Sprint 12 scope (~9–12 days)

- **Phase 1** (0.5 day, this memo) — investigation record, validator
  code audit, dictionary loader pattern audit
- **Phase 2** (2–3 days) — Item #1 `validator_rejected_credential`
- **Phase 3** (2–3 days) — Item #2 `has_dictionary_name_match`
- **Phase 4** (0.5 day) — regenerate training data, train v5
- **Phase 5a** (0.5 day) — directive A/B spike on v5 + in-distribution
  AC verification (original gate)
- **Phase 5b** (2–3 days) — **safety audit** (new gate; 3 experiments:
  capacity / architecture / heterogeneous, per
  `backlog/sprint12-shadow-directive-promotion-gate-safety-analysis-memo.yaml`)
- **Phase 6** (1 day, conditional) — Item #4 orchestrator wiring +
  shadow deletion. Only runs if Phase 5a passes in-distribution AC
  AND Phase 5b returns GREEN or YELLOW-with-mitigations.
- **Phase 7** (0.5 day) — re-baseline, CLAUDE.md ship gate migration
  OR Sprint 12 handover documenting the shadow-only v0.12.0 path if
  the gates failed

**Phase 5a is an in-distribution decision gate.** If v5 fails the
four in-dist AC, reconvene to decide between (a) adding ai4privacy
after all, (b) deeper feature engineering, (c) partial Item #4
promotion with a carve-out.

**Phase 5b is the architectural decision gate.** GREEN → proceed to
Phase 6. YELLOW → Phase 6 proceeds with explicit mitigations (e.g.,
confidence-threshold fallback). RED → Phase 6 is skipped entirely,
Sprint 12 ships v0.12.0 with shadow-only including Items #1/#2, and
the directive flip defers to Sprint 13 where the gated architecture
lands.

**The honest planning posture is that RED is plausible.** LOCO 0.17
→ 0.30 is a 2x improvement, and the features in Items #1 and #2 are
designed to improve in-distribution discrimination, not
out-of-distribution generalization. The Sprint 9 learning memo
argued the flat architecture has an information ceiling on LOCO;
that argument has not been refuted. Sprint 12 may correctly return
RED and defer the flip — that is not a failure, it is the gate
working as intended.

---

## 8. Phase 2 design question — train/serve symmetry for Item #1

**This is the Phase 2 pause point.** Before writing any Item #1 code
I want to confirm the design direction, because this is exactly
where today's bug lived.

### The problem

Item #1 wants a feature "was a credential-shaped value rejected by
the `not_placeholder_credential` validator on this column?" But
`not_placeholder_credential` runs inside the regex engine as a
per-value filter via the VALIDATOR_REGISTRY dispatch in
`data_classifier/engines/validators.py:531`. When a value is
rejected, the finding is **never emitted**. By the time
`predict_shadow` runs, the orchestrator's merged findings contain
no trace of the rejection.

- Training path (`tests/benchmarks/meta_classifier/extract_features.py`)
  invokes engines directly — can observe validator decisions by
  instrumenting the regex engine's emit call.
- Inference path (`MetaClassifier.predict_shadow`) receives the
  post-validator, post-merge findings list — cannot observe what
  was rejected, only what survived.

Same shape as today's bug: training sees a signal, inference sees
a zero, model trains on the signal, production silently degrades.

### Two options

**Option A — symmetric by construction (recommended).** Reframe the
feature as column-level "placeholder-credential density":

```python
def compute_placeholder_credential_rejection_ratio(
    sample_values: list[str],
) -> float:
    """Fraction of sample values that not_placeholder_credential would
    reject. Computed identically in training and inference from the
    same sample_values list."""
    if not sample_values:
        return 0.0
    rejected = sum(
        1 for v in sample_values
        if v and not not_placeholder_credential(v)
    )
    return rejected / len(sample_values)
```

- **Pro:** Same function called from both paths, same `sample_values`
  input, zero train/serve skew possible by construction. Mirrors the
  pattern used for `compute_dictionary_word_ratio` after today's fix.
- **Pro:** Pure function of `sample_values`; cheap, cacheable, no
  engine re-runs, no new orchestrator surface area.
- **Con (semantic):** Feature fires on any column full of
  placeholder-shaped strings, not just columns where a credential
  regex *matched*. For a column of `your_api_key_here` repeated 100
  times with no credential regex match, the feature still flags. This
  may over-flag on some NEGATIVE text columns that happen to contain
  placeholder-like tokens.
- **Con (signal strength):** The backlog yaml projected the feature
  as "was rejected during regex match", which is strictly more
  informative than "looks rejectable." Signal strength may drop.

**Option B — semantically precise, intrusive.** Thread validator
decisions through the orchestrator as sidecar metadata (a new
`validator_decisions: dict[str, int]` on `ClassificationResult` or
equivalent), populated by the regex engine at emit/reject time,
consumed by `predict_shadow` at feature-extraction time.

- **Pro:** Signal matches the backlog description exactly. Tight
  correlation with the original failure class.
- **Con:** New surface area on `ClassificationResult`. Orchestrator
  and engine-interface changes. Training harness needs the same
  instrumentation to keep symmetry. Invasive.
- **Con:** Asymmetry risk remains nonzero — if the training
  instrumentation drifts from the orchestrator's emit path, we're
  back to today's bug.

### Recommendation

**Option A.** Sprint 11's dictionary-word-ratio bug was the second
train/serve skew in three sprints (the first was `primary_split`
shard-twin leakage). The marginal signal-strength loss from Option A
is a worthwhile trade against another skew incident. If the Option A
feature underperforms the projection in Phase 5, we can revisit —
Option B is a strictly additive change we can layer on later.

**Open for the user to override.** If there's a reason to prefer
Option B (e.g., Sprint 11 projection needs to hold, or the
orchestrator refactor is cheap), flag now and I'll spec it differently
before Phase 2 starts.

---

## 9. Phase 3 reference — dictionary loader pattern

Item #2 (`has_dictionary_name_match`) mirrors the existing
`compute_dictionary_word_ratio` pattern in
`data_classifier/engines/heuristic_engine.py:226-316`:

- Lazy-loaded module-level `frozenset`, cached on first call
- Loader handles missing/malformed file by returning empty frozenset
  (degrades to 0.0 ratio instead of raising)
- Tokenization via compiled `re.compile(r"[a-z]+")`, `min_token_length`
  configurable from the JSON file
- Ratio computation: `hits / len(values)`

New helper `compute_dictionary_name_match_ratio` can copy this
structure byte-for-byte. The only new work is:

1. **Sourcing `name_lists.json`.** US Census public-domain first
   names + surnames is the obvious starting point. International
   names need license review — defer to Sprint 13. Commit under
   `data_classifier/patterns/name_lists.json`.
2. **Tokenization subtlety.** Names are case-sensitive in
   presentation (`Smith`, not `smith`) but real-world DB columns
   often store them all-lowercase or all-uppercase. Lowercasing
   before matching (like `compute_dictionary_word_ratio` does) is
   the right call.
3. **Min token length.** 4 or 5 characters is reasonable. Below 4,
   too many English words collide with short names (`al`, `jo`,
   `ed`). The Census name list can be filtered at load time.

No design risk; mostly sourcing work.

---

## 10. Artifact pointers

### Code
- `data_classifier/orchestrator/meta_classifier.py:308-325` — post-fix
  `predict_shadow` with the dictionary-word-ratio wiring
- `tests/test_meta_classifier_inference_parity.py` — parity tests
  (3 tests, 2 classes)
- `data_classifier/engines/validators.py:445-484` — `not_placeholder_credential`
  and the `_load_placeholder_values_once` loader pattern
- `data_classifier/engines/heuristic_engine.py:226-316` — dictionary
  loader reference pattern for Item #2
- `scripts/train_meta_classifier.py` — training script,
  `ALWAYS_DROP_REDUNDANT = ("has_column_name_hit", "engines_fired")`
  at module top

### Data
- `docs/research/meta_classifier/bug_investigations/sprint12_dict_word_ratio_bugfix_benchmark.json`
  — post-fix v3 baseline
- `docs/research/meta_classifier/bug_investigations/retrain_candidate_{c1,c10,c100}.json`
  — C-sweep candidates (rejected, for reference)

### Throwaway spike scripts (not in repo)
- `/tmp/option_b_spike.py` — split classification/abstention scorer
- `/tmp/directive_ab_spike.py` — three-rule dispatch scorer
- `/tmp/meta_candidates/train_fixed_c.py` — C-override trainer

### Backlog
- `backlog/sprint12-shadow-directive-promotion-gate.yaml` — Item #4
- `backlog/sprint12-validator-rejected-credential-feature.yaml` — Item #1
- `backlog/sprint12-has-dictionary-name-match-feature.yaml` — Item #2
- `backlog/review-ai4privacy-dataset-family-and-ingest-best-cc-by-4-0-variant-re-open-sprint-9-removal-decision.yaml`
  — deferred 2026-04-16

---

## 11. What's next

Phase 1 complete with this memo. Phase 2 starts after the user
confirms the Option A / Option B design question in §8 above. Order
of operations:

1. **Phase 2:** Item #1 `validator_rejected_credential` feature
   (design confirmed → implement → unit tests → commit → bump schema
   v3 → v4 in a separate commit so the schema change is reviewable).
2. **Phase 3:** Item #2 `has_dictionary_name_match` feature
   (source name list → implement helper → extract_features wiring →
   unit tests → commit → schema v4 → v5 if sequential, else v3 → v4
   combined in Phase 4).
3. **Phase 4:** rebuild `training_data.jsonl`, train v5, per-class
   diagnostic, commit artifacts.
4. **Phase 5a (in-dist gate):** rerun directive A/B spike on v5,
   verify the four original in-distribution AC. If pass → Phase 5b.
   If fail → reconvene.
5. **Phase 5b (safety audit):** run the 3-experiment safety audit
   per `backlog/sprint12-shadow-directive-promotion-gate-safety-analysis-memo.yaml`.
   Produces GREEN / YELLOW / RED verdict. This is a new spike
   harness at `tests/benchmarks/meta_classifier/sprint12_safety_audit.py`
   writing `/tmp/sprint12_safety_audit.json` and a memo at
   `docs/research/meta_classifier/sprint12_safety_audit.md`.
6. **Phase 6 (conditional):** If Phase 5a passed AND Phase 5b
   returned GREEN or YELLOW-with-mitigations, do the orchestrator
   wiring for Rule A dispatch, delete shadow codepath, update tests,
   commit. If Phase 5b returned RED, **skip Phase 6 entirely** and
   proceed to a modified Phase 7 that ships v0.12.0 as shadow-only.
7. **Phase 7:** Two paths depending on Phase 6 outcome.
   - **If Phase 6 ran:** re-baseline family benchmark on directive
     output, migrate CLAUDE.md Sprint Completion Gate to reference
     the new directive metrics, update sprint handover doc.
   - **If Phase 6 skipped (RED path):** update Sprint 12 handover
     doc with the safety audit verdict, file a Sprint 13 follow-up
     to revisit directive flip after the gated architecture lands,
     ship v0.12.0 as shadow-only with Items #1/#2 as shadow
     improvements, and keep the existing ship gate in CLAUDE.md
     unchanged.

In either Phase 7 path, Items #1 and #2 ship. They are useful as
shadow improvements even if the directive flip defers to Sprint 13.
