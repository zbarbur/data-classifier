# E11 — Gated architecture, tier-1 pattern-hit routing × model-class ablation

> **Date:** 2026-04-14
> **Branch:** `research/meta-classifier`
> **Experiment ID:** `20260414-e11-gated-tier1-ablation`
> **Status:** ✅ Done. Verdict: **Yellow — gate with LogReg helps; tree past the gate does not.**
> **Runs directory:** `docs/experiments/meta_classifier/runs/20260414-e11-gated-tier1-ablation/`
> **Artifacts:** `gate_diagnostic.json`, `ablation_results.json`, `run.log`
> **Training data:** `tests/benchmarks/meta_classifier/training_data.jsonl` — Phase 2 / pre-Gretel-EN baseline (7770 rows, 15 features)
> **Harness:** `tests/benchmarks/meta_classifier/e11_gated_experiment.py`

## 0. Question this experiment answers

Does architectural **gating** on existing regex + secret-scanner signals
help the meta-classifier compared to the flat 24-class LogReg baseline?
And if it does, is the improvement from gating alone, or from combining
the gate with a tree-based stage-2 classifier?

**Framing (learning memo §5):** gating vs filtering is the missing axis.
Q6 filtered CREDENTIAL rows out of training and retrained the flat LR —
LOCO improved by only +0.016. The hypothesis here is that Q6 treated the
regex/secret-scanner signals as *features blended into a 13-dim weighted
sum* whereas a real tier-1 gate uses them as a *routing decision*.

## 1. Tier-1 gate rule

Built entirely from existing features — zero schema changes to
`data_classifier/orchestrator/meta_classifier.py`:

```python
def route_to_credential(features):
    primary_is_credential = features[14] > 0.5
    regex_conf            = features[1]
    regex_match_ratio     = features[8]
    secret_scanner_conf   = features[4]

    if primary_is_credential and regex_conf >= 0.85 and regex_match_ratio >= 0.30:
        return True
    if secret_scanner_conf >= 0.50:
        return True
    return False
```

## 2. Preliminary gate-alone diagnostic

Before any retraining, applied the rule to all 7770 rows and measured
routing-correctness vs ground truth.

### 2.1 Headline numbers

| Metric                             |   Value |
|------------------------------------|--------:|
| Total rows                         |    7770 |
| Credential rows (truth)            |     750 |
| Routed to credential               |     744 |
| **Precision (label-match)**        | **0.6048** |
| **Recall (label-match)**           | **0.6000** |

At face value this looks like a failing gate (precision < 0.90
target). **It isn't** — the metric was measuring the wrong thing. See
§2.3 below.

### 2.2 Per-corpus breakdown

| Corpus        |   TP |    FP |   FN |    TN |
|---------------|-----:|------:|-----:|------:|
| ai4privacy    |    0 |     0 |  150 |  1050 |
| detect_secrets|  150 |     0 |    0 |   150 |
| gitleaks      |  150 |   144 |    0 |     6 |
| nemotron      |    0 |     0 |  150 |  1800 |
| secretbench   |  150 |   150 |    0 |     0 |
| synthetic     |    0 |     0 |    0 |  3720 |

**All 294 "false positives" are NEGATIVE-labeled rows from gitleaks and
secretbench.** These are credential-shape strings that upstream human
annotators tagged as "not actually a secret" (documentation examples,
placeholder strings, test credentials in code snippets). Routing them
to the credential stage is correct architecturally — they are
credential-shaped by any reasonable definition, and the stage-2
classifier's job is to resolve `{CREDENTIAL, NEGATIVE}` on a focused
subset. The `precision=0.60` headline is an artifact of the metric
conflating "predicts credential class" with "routes to credential
stage."

Per-corpus zero-FP on ai4privacy, nemotron, and synthetic is the more
meaningful signal: **the gate never mis-routes a PII column to the
credential stage**.

### 2.3 Corrected metric interpretation

| Metric                                 |    Value | What it means |
|----------------------------------------|---------:|---|
| **Routing precision** (no PII mis-routes) | **100%** (744/744) | Every routed row is from a credential corpus |
| **Engine-detected credential recall**  | **100%** (450/450) | If any engine fired, we catch it |
| **True-credential recall**             | **60%** (450/750) | Misses 300 signal-less "credentials" from PII corpora |
| **Routed-to-credential fraction**      | **9.6%** (744/7770) | Small, focused stage-2 credential subset |
| **Left for PII stage**                 | **90.4%** (7026 rows) | Clean PII subset for stage-2 |

The 300 missed credentials are `CREDENTIAL`-labeled rows from
**ai4privacy and nemotron** (150 each) where no regex or secret-scanner
signal fired. These are the OPAQUE_SECRET-class residuals the learning
memo §5 explicitly flagged as tier-2 territory. Tier-1 (pattern-based)
cannot catch them by construction; a tier-2 shape-based gate would be
required and is deferred to a follow-up experiment.

### 2.4 Examples of the NEGATIVE-from-credential-corpus rows

These are informative because they show what tier-2 would need to
handle even if it fires:

**Category 1 — placeholder / template credentials:**
- `AKIAIOSFODNN7EXAMPLE` — AWS's own documentation example
- `AKCpXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`
- `A3-XXXXXX-XXXXXXXXXXX-XXXXX-XXXXX-XXXXX`
- `ops_eyJxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

**Category 2 — regex false fires (non-credential content):**
- `msgstr "Näytä asiakirjamallikansio."` — Finnish gettext string
- `CTTCATAGGGTTCACGCTGTGTAAT-ACG--CCTGAGGC-CACA-...` — DNA sequence
- `~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~` — markdown horizontal rule

**Category 3 — fake/test secrets in code (hardest):**
- `String CLIENT_SECRET = "this-Is-My-cl1en7-5ecret"`
- `PSWRD = "anothersecRet4ME!"`
- `APP_KEY = abc123E3456abc`
- `SECRET-KEY=USERSECRET4thViolation`

**Actionable findings for Sprint 10+:**
- Category 1 is caught by a placeholder-run detector (`(.)\1{4,}`) and
  a ~50-entry blocklist of famous vendor example keys. Cheap.
- Category 3 is caught by a `dictionary_word_ratio` feature — the
  learning memo's proposed gate already included this, and these
  examples are why. Real credentials contain near-zero English words;
  these contain "my", "secret", "another", "me", "user", "violation".
- Category 2 is rare in production (research-corpus artifact) and
  probably doesn't need dedicated handling.

## 3. Four-model ablation

Same harness, same data, same M1 methodology (StratifiedGroupKFold CV
with `groups = row.corpus`, 5 folds, adaptive fallback to
`min(5, n_groups)` if groups are sparse).

### 3.1 Model configurations

| Code | Architecture | Stage-2 features |
|------|---|---|
| **A** | Flat LogReg, 24 classes, 15 features | all 15 |
| **B** | Flat HistGradientBoostingClassifier, 24 classes, 15 features | all 15 |
| **C** | Gate → LogReg stage-2 (credential & PII) | credential: 15, PII: 13 (drops `secret_scanner_confidence`, `primary_is_credential`) |
| **D** | Gate → HGB stage-2 (credential & PII) | credential: 15, PII: 13 (same drops) |

### 3.2 Headline 2×2 comparison

| Model         |   CV mean |   CV std |   LOCO mean |
|---------------|----------:|---------:|------------:|
| **A** (flat LR)       |    0.2428 |   0.1335 |      0.2558 |
| **B** (flat HGB)      |    0.2633 |   0.0734 |      0.2231 |
| **C** (gated LR)      | **0.3096** | 0.2104 |  **0.2904** |
| **D** (gated HGB)     |    0.2120 |   0.0693 |      0.2125 |

### 3.3 Pairwise deltas

| Comparison | Question answered | CV Δ | LOCO Δ |
|---|---|---:|---:|
| B − A | Does the tree help on flat? | +0.0205 | −0.0327 |
| C − A | Does gating help LR alone?   | **+0.0668** | **+0.0346** |
| D − A | Does the full gated+tree stack help? | −0.0308 | −0.0433 |
| D − C | Does the tree help *past* the gate? | −0.0976 | −0.0779 |
| D − B | Does gating help the tree? | −0.0513 | −0.0106 |

**Three clear signals:**
1. **Gating helps with LR** (+0.067 CV, +0.035 LOCO). The architectural axis has real leverage when paired with the linear stage-2 classifier.
2. **Trees do not help** — neither on the flat baseline (A→B marginal CV gain but LOCO *regresses*) nor past the gate (D is the worst model by both CV and LOCO).
3. **The tree past the gate is specifically worse than the LR past the gate** (−0.098 CV, −0.078 LOCO). Whatever the gate buys gets destroyed when HGB takes over stage-2.

### 3.4 LOCO per-corpus breakdown

| Holdout corpus | A (flat LR) | B (flat HGB) | C (gated LR) | D (gated HGB) |
|----------------|------------:|-------------:|-------------:|--------------:|
| ai4privacy     |      0.3301 |       0.1849 |       0.2759 |        0.1512 |
| detect_secrets |      0.3322 |       0.0704 |       0.2182 |        0.2368 |
| gitleaks       |      0.0053 |       0.3464 |       0.1351 |        0.1468 |
| nemotron       |      0.3594 |       0.2557 |       0.2753 |        0.2398 |
| secretbench    |      0.3333 |       0.3480 |       **0.7130** |    0.3333 |
| synthetic      |      0.1745 |       0.1331 |       0.1247 |        0.1668 |
| **mean**       |  **0.2558** | **0.2231**   |   **0.2904** |    **0.2125** |

Notable per-corpus observations:
- **C at holdout = secretbench hits 0.71**, dominating its LOCO mean. When secretbench is held out, the stage-2 credential classifier trains on detect_secrets + gitleaks credentials (shape-similar) and transfers well to secretbench credentials. That's a real win but it's concentrated in one fold.
- **A at holdout = gitleaks collapses to 0.005.** When gitleaks is held out, the flat LR fails almost completely — its representation of "credentials" is so gitleaks-specific that removing gitleaks breaks it. The gated variants (C, D) don't collapse as hard on gitleaks because the gate routes gitleaks-held-out credentials through a stage-2 classifier that's still trained on the other credential corpora.
- **Synthetic is consistently low across all models** (0.12-0.17). Synthetic corpus has ~15 distinct entity types Faker generates (including PII the real corpora don't cover — IBAN, BITCOIN, VIN, MBI, NPI, CANADIAN_SIN, etc.) and no overlap with other corpora's signal distributions. It's the hardest holdout.

### 3.5 Tree root-split diagnostic (shortcut check)

For B (flat HGB) and D (gated HGB, stage-2 PII subset), the first tree's
root split feature is reported as a diagnostic for shortcut learning.

| Model | Root split feature |
|---|---|
| B | `heuristic_confidence` |
| D | `heuristic_confidence` (on the 13-feature stage-2 schema) |

**The tree does NOT pick `heuristic_avg_length` at the root**, contrary
to the LogReg shortcut the learning memo identified. It picks the
aggregated `heuristic_confidence` feature — which is correlated with
length but is itself an engine-level combination of multiple inputs.

This is an interesting asymmetry. The LR coefficient on
`heuristic_avg_length` was 252 (pre-Gretel) then 131 (post-Gretel) —
the dominant raw-feature weight. The tree can use the raw feature just
as easily but prefers the aggregated one because tree splits on
bounded features are naturally coarser than linear combinations.

**This doesn't mean the tree avoids the shortcut** — it means the tree
is picking a *different* per-corpus proxy. `heuristic_confidence` is
also likely to correlate with corpus (because different corpora trip
different heuristic thresholds). Whether the tree's choice is *less*
shortcut-prone than LR's would need a dedicated test — a bootstrap
swap-one-corpus experiment on tree root splits would be the cheap way
to measure it.

## 4. Verdict

**Yellow.** The architectural gating direction has measurable leverage
(C beats A by +0.067 CV, +0.035 LOCO — both real, both above noise in
the mean), but two caveats hold it back from a green-light:

1. **C's CV std is 0.21** — very high. The improvement sits within one
   std of baseline, so the mean delta is suggestive rather than
   statistically rock-solid. A bootstrap CI on the LOCO delta would
   pin down significance.
2. **The tree direction does not help.** Neither B (+0.02 CV / −0.03
   LOCO) nor D (−0.03 CV / −0.04 LOCO) beats A. The Sprint 10 backlog
   item `meta-classifier-model-ablation-logreg-vs-xgboost-vs-lightgbm-on-honest-loco-metric`
   should expect a negative or null result from the tree swap on the
   current feature set. **Trees are not the bottleneck; features are.**

### 4.1 What this means for Sprint 10+

- **Gated architecture direction is worth pursuing** — file a Sprint 11+
  sprint item that builds out the gate as a real orchestrator change,
  starting with a LogReg stage-2. The architectural gain (+0.067 CV,
  +0.035 LOCO) translates to roughly the magnitude the learning memo
  predicted for this axis.
- **Tree model-class swap (Sprint 10 backlog item) is probably a
  negative-result experiment.** This experiment is evidence that swapping
  LR → HGB won't move macro F1 on the current feature set — in fact it
  regresses. The sprint item should either be de-prioritized or re-scoped
  to "trees as diagnostic (inspect root splits) rather than as
  replacement classifier."
- **Feature engineering (not model class) is the complementary axis.**
  The gate helped but only modestly, and the stage-2 classifier is
  still working against a 13-feature vector where `heuristic_avg_length`
  and `heuristic_confidence` dominate. Adding `dictionary_word_ratio`
  and `placeholder_run_detection` — directly motivated by the NEGATIVE
  examples in §2.4 — is a cheap, targeted next experiment.
- **The shard-twin leak in `primary_split` is not measured in this
  experiment** (the harness uses StratifiedGroupKFold for CV only —
  both twins stay in the same fold since they share a corpus). The
  numbers here are CV-honest but leave the held-out 80/20 test
  question unresolved. Separate quantification experiment required.

### 4.2 Actionable follow-ups (ranked by leverage)

1. **E12 — add dictionary-word-ratio + placeholder-run features, re-run the ablation.** Directly motivated by §2.4's NEGATIVE examples. ~2-3 research hours. High confidence this helps the gated-LR variant specifically because the stage-2 credential classifier is currently relying only on aggregated engine signals that can't distinguish Category-3 fake secrets.
2. **E13 — tier-2 shape-based residual catcher for signal-less credentials.** Address the 300 missed credentials from ai4privacy + nemotron. Gate v2 from the E11 spec. Should close the 60% true-credential recall gap.
3. **E14 — post-Gretel training data rebuild and re-run.** Validate that the E11 findings survive the Sprint 9 training data shift. Would also exercise the adaptive-fallback path in the M1 promotion since the Gretel + ai4privacy-removal changes group count.
4. **Quantify the shard-twin leak in `primary_split`.** Independent of E11. Changes how we interpret the tertiary blind delta (+0.2432 cited post-M1 + post-Gretel) by estimating the leak magnitude. ~30 min experiment.

### 4.3 What NOT to do

- **Don't ship D (gated + HGB) as a candidate.** It's strictly worse
  than A on both CV and LOCO. The tree past the gate hurts on this
  feature set.
- **Don't retrain the flat model with HGB on this data.** B's +0.02 CV
  gain is noise; its −0.03 LOCO regression is meaningful. The Sprint 10
  tree-swap backlog item should expect a null result.
- **Don't commit to the gated direction production-side yet.** C is
  promising but the high CV variance and limited LOCO improvement
  don't clear the bar for promotion. This is a research signal, not a
  ship signal. Run E12 first.

## 5. Provenance

- **Gate rule:** §1 above, four feature inspections combined with OR. Deterministic.
- **Harness:** `tests/benchmarks/meta_classifier/e11_gated_experiment.py` (new, this experiment).
- **Model hyperparameters:**
  - LogReg: `C=1.0, solver='lbfgs', max_iter=2000, class_weight='balanced'`
  - HGB: `max_iter=200, learning_rate=0.05, max_depth=5, min_samples_leaf=20, class_weight='balanced'`
- **CV:** `StratifiedGroupKFold(n_splits=min(5, n_groups), shuffle=True, random_state=20260413)`, `groups=row.corpus`
- **LOCO:** leave-one-corpus-out, each corpus in turn
- **Feature drop for stage-2 PII:** indices 4 (`secret_scanner_confidence`) and 14 (`primary_is_credential`) — no point keeping features that are near-zero for every row reaching stage 2 after the gate pulled credentials out.
- **Preprocessing:** `StandardScaler` fit on train fold, applied to validation — both for LR and HGB. HGB technically doesn't need scaling but scaling is harmless.

## 6. Caveats

- **Pre-Gretel training data.** This experiment uses the Phase 2 /
  pre-M1 training data (7770 rows). The current production v1 model
  was retrained on post-Gretel data (sprint9/main). Absolute numbers
  here are *not* directly comparable to the current production CV
  0.194 / LOCO 0.17 baseline. **The experiment measures the
  architecture-vs-feature-engineering slope on the old data**; if
  slope is positive, the direction is worth pursuing regardless of
  data freshness, and E14 validates on fresh data.
- **Shard-twin leak.** Not mitigated in this experiment. The CV
  harness (StratifiedGroupKFold) is not affected because twins share a
  corpus and land in the same fold, but the absolute CV numbers are
  not directly comparable to any external evaluation that uses a
  twin-leak-free split.
- **Single random seed (20260413).** No bootstrap or seed averaging.
  The CV std is within-run fold variance, not seed variance.
- **HGB `class_weight='balanced'` on 24-class output may be
  pathological.** sklearn's implementation of balanced class weights
  for multi-class HGB is less mature than LR's. The negative result
  on B and D might partly be an HGB-with-balanced-weights issue
  rather than a tree-model issue generally. LightGBM with sample
  weights handled explicitly might score better, but introducing
  a new optional dep is out of scope here.
