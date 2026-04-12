# Q6 — Inverted stage 1 / PII-only meta-classifier

**Date:** 2026-04-13
**Branch:** `research/q6-inverted-stage1` (off `research/meta-classifier`)
**Worktree:** `/Users/guyguzner/Projects/data_classifier-q6`
**Verdict:** **Q6-C** — label purity was **not** the dominant issue.
LOCO improves by only +0.016 vs the same-protocol v1 reference.
Recommend pivoting to E10 (GLiNER features) or E9 (new PII corpora).

## TL;DR

Filtering CREDENTIAL + NEGATIVE rows out of training and retraining on
the 6,570 PII-only rows improves held-out 80/20 macro F1 by a nominal
+0.077, but the McNemar's paired test on the same 1,314 test rows
returns p = 0.77 (q6-only-right = 6, v1-only-right = 6) — v1 and v1_q6
are statistically indistinguishable at the row level. The apparent F1
gap is a zero-support-label artifact from sklearn's macro average:
v1 still predicts CREDENTIAL / NEGATIVE on a handful of PII rows, and
those predictions drag v1's macro mean through zero-support buckets
that v1_q6 cannot emit at all.

On LOCO — the money number — Q6 moves the mean from 0.250 to 0.266
over the three PII corpora (ai4privacy, nemotron, synthetic), a
+0.016 delta that is well below the Q6-B threshold of 0.45 and
**nowhere near** the Q6-A ship threshold of 0.60. Two of three
per-corpus holdouts actually get **worse** under Q6
(nemotron −0.02, synthetic −0.02). Only ai4privacy improves
meaningfully (+0.08).

**Interpretation:** Q5's structural label-purity finding is real,
but it is not what is driving the LOCO collapse. The dominant leakage
is the per-corpus feature-distribution fingerprint (Q3's finding on
`heuristic_avg_length`), and that pathology is still present in the
PII-only training data.

## Training setup

| Item | Value |
|---|---|
| Input | `tests/benchmarks/meta_classifier/training_data_q6.jsonl` |
| Rows | 6,570 (7,770 full − 750 CREDENTIAL − 450 NEGATIVE) |
| Classes | 22 (24 full − CREDENTIAL − NEGATIVE) |
| Corpora | ai4privacy (1,200), nemotron (1,950), synthetic (3,720) |
| Model | `data_classifier/models/meta_classifier_v1_q6.pkl` |
| Metadata | `data_classifier/models/meta_classifier_v1_q6.metadata.json` |
| Best C | 100.0 (selected by 5-fold stratified CV) |
| Features kept | 11 |
| Features dropped | `has_column_name_hit` (always-drop, redundant), `engines_fired` (always-drop, redundant), `secret_scanner_confidence` (all-zero on PII rows), `has_secret_indicators` (all-zero on PII rows) |

The two secret-scanner features were automatically dropped by the
training pipeline's `CONDITIONAL_DROP_IF_CONSTANT` check — filtering
out CREDENTIAL / NEGATIVE rows collapses them to constant zero, which
confirms that Q6's "meta-classifier no longer sees credential signals"
premise is honored by the data.

## Three-tier evaluation

### 1. Primary — held-out 80/20 (PII-only)

Reproduces the same `train_test_split(test_size=0.2, random_state=42)`
the training script used, on the filtered 6,570-row data. Test set is
1,314 PII rows.

| metric | v1_q6 | v1 (on same rows) | delta |
|---|---:|---:|---:|
| macro F1 | **0.9356** | 0.8587 | +0.077 |
| 95% BCa CI | [0.9233, 0.9469] (width 0.024) | — | — |
| McNemar statistic | — | — | 0.083 |
| McNemar p-value | — | — | **0.77** |
| q6-only-right | — | — | 6 |
| v1-only-right | — | — | 6 |

The +0.077 macro-F1 delta is **not** a real accuracy improvement.
McNemar's test shows v1 and v1_q6 make per-row-different predictions
on only 12 of 1,314 rows, evenly split (6 vs 6, p = 0.77). The
apparent F1 gap comes entirely from v1's ability to emit CREDENTIAL
and NEGATIVE predictions on PII rows — those predictions are always
wrong and always contribute zero-F1 buckets to v1's macro average that
v1_q6 mechanically cannot produce. Cleaner label space, not cleaner
predictions.

#### Per-class F1 on the 1,314-row PII test set

| label | v1_q6 F1 | v1 F1 | support |
|---|---:|---:|---:|
| DATE_OF_BIRTH       | 0.492 | 0.483 | 72 |
| PHONE               | 0.763 | 0.750 | 72 |
| DATE_OF_BIRTH_EU    | 0.828 | 0.828 | 60 |
| IP_ADDRESS          | 0.895 | 0.895 | 72 |
| URL                 | 0.909 | 0.909 | 42 |
| MAC_ADDRESS         | 0.913 | 0.913 | 42 |
| SSN                 | 0.936 | 0.957 | 72 |
| CANADIAN_SIN        | 0.947 | 0.939 | 60 |
| ADDRESS             | 0.972 | 0.979 | 72 |
| PERSON_NAME         | 0.972 | 0.979 | 72 |
| CREDIT_CARD         | 0.977 | 0.977 | 42 |
| SWIFT_BIC           | 0.988 | 1.000 | 42 |
| NPI                 | 0.992 | 1.000 | 60 |
| ABA_ROUTING         | 1.000 | 1.000 | 42 |
| BITCOIN_ADDRESS     | 1.000 | 1.000 | 60 |
| DEA_NUMBER          | 1.000 | 1.000 | 60 |
| EIN                 | 1.000 | 1.000 | 60 |
| EMAIL               | 1.000 | 1.000 | 72 |
| ETHEREUM_ADDRESS    | 1.000 | 1.000 | 60 |
| IBAN                | 1.000 | 1.000 | 60 |
| MBI                 | 1.000 | 1.000 | 60 |
| VIN                 | 1.000 | 1.000 | 60 |

Every row in this table either matches or is within 0.02 F1 of v1.
Q6 is roughly equivalent to v1 on every single PII class when you
restrict v1's predictions to the PII-only test rows. DATE_OF_BIRTH
remains the hardest class (0.49) for both — confirming that Q4
(DOB/DOB-EU merge) is still an open lever independent of Q6.

### 2. Secondary — LOCO (leave-one-corpus-out) over 3 PII corpora

Trained v1_q6 from scratch on 2-of-3 PII corpora, tested on the third.
Same best C = 100, same feature subset as the full v1_q6 model.

| holdout | n_test | v1_q6 macro F1 | v1 (Q3 extended table) | delta |
|---|---:|---:|---:|---:|
| ai4privacy  | 1,050 | **0.3435** | 0.260 | **+0.084** |
| nemotron    | 1,800 | 0.3432     | 0.360 | −0.017 |
| synthetic   | 3,720 | 0.1105     | 0.130 | −0.020 |
| **mean**    | — | **0.2657** | **0.2500** | **+0.016** |

v1 reference numbers are from Q3's extended LOCO table (see
`runs/20260412-q3-loco-investigation/result.md` §5c and queue.md
§M3 discussion). They were computed under v1's training regime
(6 corpora, 13 features, full 7,770 rows) and then tested on each
corpus's PII rows.

The +0.084 improvement on ai4privacy holdout *is* a real signal —
that is the single case where removing credential-pure corpora stops
corrupting v1's within-corpus label decisions. But the two other
holdouts get slightly worse because Q6 trades away ~15–30% of the
training data per fold (2 PII corpora ≈ 2,850–5,520 rows vs v1's
~5,820–6,570 rows with credential corpora included). The net 3-corpus
mean only moves +0.016, and that is dominated by the ai4privacy gain.

**The LOCO number Q6 would need to ship (≥ 0.60) is 0.33 away.**

### 3. Tertiary — blind-mode subset

Not re-run for Q6: the blind-mode split is orthogonal to the CREDENTIAL
filter (CREDENTIAL rows exist in both named and blind modes). The
held-out 80/20 already captures the relevant comparison via the
McNemar analysis — since v1 and v1_q6 disagree on only 12 rows total,
any mode-sliced sub-analysis would show the same conclusion at even
lower statistical power. If Q6 had produced a Q6-A or Q6-B verdict we
would run the blind-mode gate before recommending promotion; it did
not, so this is moot.

## Why Q6 barely moves LOCO (the mechanism)

Q5 identified two distinct pathologies in v1's training data, and Q3's
feature ablation landed on only one of them:

1. **Structural label-corpus correlation** — three corpora (gitleaks,
   secretbench, detect_secrets) are label-pure on
   {CREDENTIAL, NEGATIVE}. Under LOCO with these corpora as the
   holdout, "predict label" collapses to "predict corpus." **Q6 fixes
   this by removing those corpora from training entirely.**
2. **Per-corpus feature-distribution fingerprinting** — Q3's feature
   ablation showed `heuristic_avg_length` carries abs-coef-sum 488
   (2× the runner-up), and the value-length distributions of the
   surviving PII corpora still differ enough to let the model
   fingerprint "which corpus is this row from?" even without the
   credential corpora in the mix. **Q6 does not touch this.**

The Q6 LOCO result (+0.016) is consistent with fixing pathology (1)
only. Pathology (2) is the dominant leakage and requires a different
intervention:
- **E4 / Q3 candidate:** bin `heuristic_avg_length` into a small number
  of buckets so the model can't fingerprint distributions.
- **E10:** add GLiNER features as a corpus-invariant signal (a
  pretrained transformer should be much less sensitive to per-corpus
  length distributions than coefficient-weighted sum-of-engines).
- **E9:** add more PII corpora so the LOCO outer loop has more domains.

## Comparison table — v1 vs v1_q6

| metric | v1 | v1_q6 | delta | note |
|---|---:|---:|---:|---|
| train rows | 7,770 | 6,570 | −1,200 | filtered CRED/NEG |
| classes | 24 | 22 | −2 | — |
| features kept | 13 | 11 | −2 | secret_scanner features go constant |
| best C | 100 | 100 | 0 | same grid |
| CV mean macro F1 | 0.9160 | 0.9310 | +0.015 | suspect per M1 — CV is not group-aware |
| held-out macro F1 | 0.9185 | 0.9356 | +0.017 | zero-support artifact; McNemar p=0.77 |
| held-out CI width | 0.024 | 0.024 | 0.000 | same |
| LOCO mean (3 PII corpora) | 0.250 | 0.266 | **+0.016** | money number — barely moves |
| LOCO ai4privacy holdout | 0.260 | 0.343 | +0.084 | real gain |
| LOCO nemotron holdout | 0.360 | 0.343 | −0.017 | smaller training set |
| LOCO synthetic holdout | 0.130 | 0.111 | −0.020 | smaller training set |

Headline numbers for v1 (CV 0.916, held-out 0.918) are from the
committed metadata sidecar at
`data_classifier/models/meta_classifier_v1.metadata.json`. The
ai4privacy / nemotron / synthetic LOCO numbers for v1 are from Q3's
extended LOCO breakdown (queue.md §M3 records these) — they are
approximately ±0.01 noisy around the ones my Q6 eval script re-runs
would produce, which is inside the evaluation noise floor.

## Verdict classification

Per the queue.md Q6 entry outcome-classification rules:

| outcome | LOCO threshold | observed | match? |
|---|---:|---:|---|
| Q6-A | ≥ 0.60 | 0.266 | ❌ |
| Q6-B | 0.45–0.60 | 0.266 | ❌ |
| **Q6-C** | < 0.45 (barely moves) | **0.266** | ✅ |

**Verdict: Q6-C.** Label purity was not the dominant issue.

## Recommendation

1. **Do not promote v1_q6 to production.** It is statistically
   indistinguishable from v1 on PII rows (McNemar p = 0.77) and
   addresses a secondary pathology at the cost of training data
   volume. Keep v1.pkl as the shipped shadow artifact.
2. **Pivot the meta-classifier research thread to E10
   (GLiNER features).** Q6 is the cheapest possible test of the
   label-purity hypothesis and it came back negative. The next
   cheapest unanswered question is whether a corpus-invariant
   pretrained signal (GLiNER) fixes the per-corpus fingerprinting —
   E10 is already queued with the feature-schema exception paperwork
   in place.
3. **Strongly consider E4 (bin `heuristic_avg_length`) as a
   lightweight pre-E10 probe.** Q3 already built the retrain harness
   and the feature is the single highest-magnitude coefficient;
   binning it is a one-line change and will isolate whether the
   distribution fingerprinting is the whole Q3 story.
4. **Keep Q4 (DOB / DOB-EU merge) queued independently of the
   meta-classifier direction.** DATE_OF_BIRTH is still the worst
   per-class F1 (0.49) for both v1 and v1_q6 on PII-only rows, and
   fixing it is orthogonal to the LOCO investigation.
5. **Do not run E9 on the basis of Q6 alone.** Q6-C means label
   purity isn't the bottleneck, but it doesn't prove the bottleneck
   is feature engineering vs. corpus scarcity. Run E10 first
   (feature-side fix); only run E9 if E10 also fails.

## Artifacts

- `data_classifier/models/meta_classifier_v1_q6.pkl` — trained model
  (11 features, 22 classes). Do **not** promote without a follow-up
  experiment showing a real LOCO improvement.
- `data_classifier/models/meta_classifier_v1_q6.metadata.json` —
  training script metadata (best C, CV history, per-class test F1,
  top-5 feature importances).
- `tests/benchmarks/meta_classifier/training_data_q6.jsonl` — the
  filtered training data (6,570 rows).
- `tests/benchmarks/meta_classifier/q6_evaluate.py` — research-side
  evaluator that runs held-out + 3-corpus LOCO + McNemar vs v1.
  Reusable by any PII-only follow-up (Q6+E10 hybrid, E4, etc).
- `q6_eval.json` — machine-readable full numbers for the evaluator run.
- `q6_eval.log` — stdout of the evaluator run (mirrors the tables
  above verbatim).

## Reproduction

```
# from repo root in the q6 worktree
python3 -c "
import json
with open('tests/benchmarks/meta_classifier/training_data.jsonl') as fin, \
     open('tests/benchmarks/meta_classifier/training_data_q6.jsonl', 'w') as fout:
    for line in fin:
        if json.loads(line)['ground_truth'] not in ('CREDENTIAL','NEGATIVE'):
            fout.write(line)
"

python3 -m scripts.train_meta_classifier \
  --input tests/benchmarks/meta_classifier/training_data_q6.jsonl \
  --output data_classifier/models/meta_classifier_v1_q6.pkl \
  --metadata data_classifier/models/meta_classifier_v1_q6.metadata.json

python3 -m tests.benchmarks.meta_classifier.q6_evaluate \
  --json docs/experiments/meta_classifier/runs/20260412-q6-inverted-stage1/q6_eval.json
```

All three steps are deterministic (seed 42, `PYTHONHASHSEED=42`) and
take well under one minute combined on an M-series Mac.
