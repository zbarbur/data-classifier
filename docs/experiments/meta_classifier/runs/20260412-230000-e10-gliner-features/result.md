# E10 — GLiNER features for the meta-classifier

**Session:** C (parallel research)
**Branch:** `research/e10-gliner-features` (off `research/meta-classifier` off `main`)
**Started:** 2026-04-12 23:00 IDT
**Finished:** 2026-04-13 10:09 IDT
**Status:** ✅ complete
**Verdict:** **Outcome B′ — mixed. GLiNER produces modest in-distribution gains (+0.010 to +0.016 macro F1) but regresses LOCO on ai4privacy (-0.077) and is outpaced by the 5-engine live pipeline on primary delta (+0.093 vs v1's +0.117 against the 4-engine framing).**
**Promotion recommendation:** **Do NOT auto-promote `v1_e10.pkl`.** The meta-classifier still beats the honest 5-engine live baseline at statistical significance (McNemar p ≈ 0, CI excludes zero on both primary and tertiary), but the LOCO regression and the class-level re-shuffling make this a weaker-than-Phase-2 case. Pursue E4 (bin `heuristic_avg_length`) and Q5 (feature distribution audit) before another promotion attempt.

## 0. Context — what question was E10 answering?

Phase 2 of the meta-classifier deliberately excluded GLiNER2 from the
feature set. Both `build_training_data.py:29` and `evaluate.py:49` set
`DATA_CLASSIFIER_DISABLE_ML=1` at module entry, so v1.pkl was:

1. **trained** on features derived from a 4-engine view (regex,
   column_name, heuristic_stats, secret_scanner — no GLiNER), and
2. **evaluated** against a 4-engine "live baseline" (GLiNER likewise
   disabled in `classify_columns`).

The shipped "+0.25 macro-F1 delta over live baseline" on blind mode was
measured against that reduced 4-engine pipeline, not the real 5-engine
production orchestrator (which in shipped Sprint 6 code includes GLiNER
at order 5). Separately, v1's leave-one-corpus-out (LOCO) macro F1 was
**0.26** on ai4privacy and **0.36** on nemotron — a 0.55+ gap versus
its 0.916 in-distribution CV that suggests severe per-corpus
distribution fingerprinting.

**E10 asked the single biggest unanswered question:** can a meta-
classifier that also sees GLiNER close the LOCO gap against an
_honest_ 5-engine baseline? The prescribed outcomes were:

- **(A) GLiNER closes LOCO massively** — LOCO jumps to 0.7+, held-out
  stays ~0.92 against the 5-engine baseline.
- **(B) GLiNER helps but is not enough** — LOCO improves to ~0.5 but
  not 0.7.
- **(C) GLiNER doesn't help at all** — LOCO stays at 0.27-0.36 even
  with GLiNER features.

The answer landed **between B and C** in a nuanced way that neither
option quite captures. This memo calls it **B′** and explains.

## 1. Headline numbers — v1 vs v1_e10

> v1 numbers below are from
> `data_classifier/models/meta_classifier_v1.{eval.json,metadata.json}`.
> The v1 `live_f1` columns were measured against a **4-engine** live
> baseline because Phase 2 disabled GLiNER in `evaluate.py`. The
> v1_e10 columns are measured against the honest **5-engine** live
> baseline, which changes the framing of the delta.

### 1.1 Primary — stratified 80/20 held-out test (1554 rows)

| metric                             |       v1 (4-engine) |     v1_e10 (5-engine) | change |
|------------------------------------|--------------------:|----------------------:|-------:|
| meta macro F1                      |              0.9185 |                0.9289 | **+0.0104** |
| live baseline macro F1             |              0.8016 |                0.8357 | +0.0341 |
| delta (meta − live)                |             +0.1169 |               +0.0932 | **−0.0237** |
| 95% BCa CI on delta                | [+0.094, +0.138]    | [+0.074, +0.111]      | narrower |
| CI width                           |              0.0438 |                0.0374 | −0.0064 |
| McNemar (meta_wins, live_wins)     |        (276, 98)    |            (185, 56)  | — |
| McNemar p-value                    |                 0.0 |             1.1e-16   | still p≈0 |

### 1.2 Tertiary — blind-mode subset (ship gate, 803 rows)

| metric                             |       v1 (4-engine) |     v1_e10 (5-engine) | change |
|------------------------------------|--------------------:|----------------------:|-------:|
| meta macro F1 (blind)              |              0.9091 |                0.9253 | **+0.0162** |
| live baseline macro F1 (blind)     |              0.6517 |                0.7346 | +0.0829 |
| delta (meta − live)                |             +0.2574 |               +0.1907 | **−0.0667** |
| 95% BCa CI on delta                | [+0.228, +0.284]    | [+0.162, +0.216]      | narrower |
| CI width                           |              0.0558 |                0.0541 | −0.0017 |
| ship gate: Δ ≥ +0.02               |                PASS |                  PASS | — |
| ship gate: CI width ≤ 0.06         |                PASS |                  PASS | — |
| ship verdict                       | full meta-classifier | full meta-classifier | — |

### 1.3 Secondary — LOCO (the money number)

| hold-out corpus |  n_test |       v1 macro F1 |    v1_e10 macro F1 | change   |
|-----------------|--------:|------------------:|-------------------:|---------:|
| ai4privacy      |    1200 |            0.2595 |             0.1825 | **−0.0770** |
| nemotron        |    1950 |            0.3579 |             0.3728 | +0.0148  |
| **mean**        |         |            0.3087 |             0.2776 | **−0.0311** |

**LOCO ai4privacy regressed by 0.077**, nemotron improved marginally
(+0.015). Mean LOCO fell by 0.031. That is the LOCO direction
collapsing further, not closing.

### 1.4 CV history (18 effective features)

| C       | v1 CV mean F1 | v1 std | v1_e10 CV mean F1 | v1_e10 std |
|---------|---------------|--------|-------------------|------------|
| 0.01    | 0.520         | 0.026  | 0.607             | 0.011      |
| 0.1     | 0.762         | 0.008  | 0.779             | 0.012      |
| 1.0     | 0.862         | 0.005  | 0.887             | 0.006      |
| 10.0    | 0.900         | 0.009  | 0.919             | 0.005      |
| **100.0** (best) | **0.9160** | **0.0072** | **0.9297** | **0.0055** |

CV best C held at 100.0 in both runs. CV macro F1 improved by +0.014
with GLiNER features present.

## 2. Per-class F1 (test set, 24 classes)

| class               |    v1 |  v1_e10 |   delta |
|---------------------|------:|--------:|--------:|
| **PHONE**           | 0.769 |   0.952 | **+0.182** |
| **DATE_OF_BIRTH**   | 0.527 |   0.800 | **+0.273** |
| **PERSON_NAME**     | 0.844 |   0.940 | **+0.097** |
| CREDIT_CARD         | 0.966 |   1.000 | +0.034  |
| ABA_ROUTING         | 0.977 |   0.988 | +0.011  |
| MAC_ADDRESS         | 0.894 |   0.903 | +0.010  |
| SSN                 | 0.964 |   0.972 | +0.008  |
| IP_ADDRESS          | 0.873 |   0.879 | +0.006  |
| URL                 | 0.895 |   0.897 | +0.003  |
| ADDRESS             | 0.947 |   0.946 | −0.001  |
| IBAN                | 1.000 |   0.992 | −0.008  |
| CREDENTIAL          | 0.806 |   0.794 | −0.012  |
| NEGATIVE            | 0.832 |   0.798 | −0.034  |
| **DATE_OF_BIRTH_EU**| 0.828 |   0.686 | **−0.141** |
| **CANADIAN_SIN**    | 0.923 |   0.745 | **−0.178** |
| (constant-1 classes unchanged: BITCOIN_ADDRESS, DEA_NUMBER, EIN, EMAIL, ETHEREUM_ADDRESS, MBI, NPI, SWIFT_BIC, VIN) |

### Reading the per-class shuffle

**Classes GLiNER natively detects gain massively:**

- PHONE +0.182 — GLiNER's `phone number` label is calibrated for
  free-text numbers and catches the blind-mode PHONE columns v1's
  regex missed.
- DATE_OF_BIRTH +0.273 — GLiNER's `date of birth` label replaces the
  unreliable date-regex that collides with EU-format dates.
- PERSON_NAME +0.097 — zero-shot NER trivially beats the "is this a
  name dictionary" column_name engine.

**Classes requiring format-level discrimination regress:**

- CANADIAN_SIN −0.178 — CANADIAN_SIN values (9-digit format with
  checksum) look structurally like SSNs, and GLiNER tags both under
  `national identification number`. The meta-classifier now has a
  GLiNER signal that actively _confuses_ CANADIAN_SIN with SSN.
- DATE_OF_BIRTH_EU −0.141 — GLiNER doesn't distinguish US vs EU date
  formats; its `date of birth` fires on both. When the model sees
  `gliner_top_entity_is_pii == 1` on a DD/MM/YYYY column, it can flip
  a borderline prediction from DATE_OF_BIRTH_EU to DATE_OF_BIRTH.
- CREDENTIAL, NEGATIVE, IBAN — small regressions from redistributed
  mass.

**Net macro F1 shift**: +0.0104 on held-out. The distributional win on
PHONE/DATE_OF_BIRTH/PERSON_NAME barely outweighs the regressions on
CANADIAN_SIN/DATE_OF_BIRTH_EU. That is an unusually brittle aggregate.

## 3. Feature importance — where do the 5 new GLiNER features land?

Full `|coef|_1` ranking of the 18 features v1_e10 kept (after
dropping `engines_fired` and `has_column_name_hit` as always-redundant):

| rank | feature                     | \|coef\|_1  |
|-----:|-----------------------------|------------:|
|    1 | heuristic_avg_length        |      493.30 |
|    2 | primary_is_pii              |      231.62 |
|    3 | engines_agreed              |      231.35 |
|    4 | regex_match_ratio           |      228.21 |
|    5 | top_overall_confidence      |      219.98 |
|    6 | regex_confidence            |      198.27 |
|    7 | column_name_confidence      |      185.08 |
|    8 | confidence_gap              |      143.17 |
|    9 | heuristic_distinct_ratio    |      101.36 |
|   10 | primary_is_credential       |       76.31 |
| **11** | **gliner_top_entity_is_pii** |    **72.04** |
|   12 | secret_scanner_confidence   |       62.73 |
|   13 | has_secret_indicators       |       62.02 |
| **14** | **gliner_top_confidence**   |     **58.41** |
| **15** | **gliner_agrees_with_regex** |    **52.91** |
| **16** | **gliner_confidence_gap**   |     **37.62** |
| **17** | **gliner_agrees_with_column** | **31.92** |
|   18 | heuristic_confidence        |       17.04 |

**The five GLiNER features occupy ranks 11, 14, 15, 16, 17** —
supplementary, not dominant. Their combined `|coef|_1` mass is
252.90, less than `heuristic_avg_length` alone (493.30).

`heuristic_avg_length` is still 2.1× the runner-up and the single
biggest per-class discriminator. The LOCO-leaking-feature hypothesis
from Q3 still stands — E10 did not displace it.

### Multicollinearity note (build-report correlations)

The training-data build report flags three of the GLiNER features as
redundant (|r| > 0.9):

```
gliner_top_confidence        gliner_top_entity_is_pii     +0.976
gliner_top_entity_is_pii     gliner_confidence_gap        +0.974
gliner_top_confidence        gliner_confidence_gap        +0.943
```

This is expected: GLiNER's output taxonomy only contains PII labels,
so `top_entity_is_pii == 1 whenever top_confidence > 0`, and
`confidence_gap` is non-zero on exactly the same rows. Effective
degrees of freedom in the GLiNER block is closer to 2 than 5.
L2 regularization (C=100) handles the redundancy but doesn't
_exploit_ separate signal that isn't there.

If a follow-up experiment wants to widen the GLiNER contribution, a
richer per-entity probability vector (e.g. one float per GLiNER label,
NOT booleans) would expose more independent signal at the cost of
higher feature count. E10's 5-feature budget was the right scoping
decision for a first-try, but the redundancy is real.

## 4. Why LOCO regressed on ai4privacy

**Hypothesis.** GLiNER's confidence calibration is itself corpus-
sensitive. GLiNER was trained on a PII corpus whose value-length
distribution and annotator conventions differ from ai4privacy's. On
nemotron (whose distribution GLiNER has seen close analogues of in
training), GLiNER produces high-confidence findings on 33.8% of rows
globally. On ai4privacy, GLiNER's hit rate and confidence range
differ, making the five new features effectively another corpus
fingerprint rather than a corpus-invariant abstraction.

The meta-classifier then has _more_ corpus-fingerprinting dimensions
to exploit, not fewer. The regularizer doesn't know to penalize
corpus-fingerprint mass specifically, and the in-distribution CV
benefit it buys is exactly what lets the LOCO hold-out performance
degrade.

**Empirically**, this matches:

- CV gain ≈ +0.014 (in-distribution, same-corpus rows in both
  train and test).
- Mean LOCO drop ≈ −0.031 (out-of-distribution, unseen corpus in
  test).

The delta between those two (≈ +0.045 gap widening) is the "corpus
fingerprint mass transferred to GLiNER features" in crude terms.

## 5. Live-baseline closing of the ship-gate gap

The **live pipeline** improved more than the meta-classifier:

- primary live F1: 0.8016 → 0.8357 (+0.0341)
- tertiary live F1: 0.6517 → 0.7346 (+0.0829)

This is because GLiNER alone — without any meta-classifier — closes
most of the gap the meta-classifier was claiming on the 4-engine
baseline. Specifically, the "+0.26 blind delta" the Phase 2 memo
attributed to the meta-classifier shrinks to +0.19 once the honest
5-engine baseline runs with GLiNER enabled. The gap that remains is
the meta-classifier's real value-add.

That remaining +0.19 blind delta with CI [+0.162, +0.216] is still:

- **statistically significant** (McNemar stat 76.1, p ≈ 0),
- **above the ship gate** of +0.02, and
- **CI width 0.054** (inside the 0.06 gate).

So the nominal "ship the meta-classifier" conclusion from the 4-engine
framing **still holds** under the honest baseline. The claim is just
smaller than Phase 2 advertised.

## 6. Implementation work summary

### 6.1 Schema widening (contract exception, `data_classifier/orchestrator/meta_classifier.py`)

Appended 5 new feature names after index 14:

```
15 gliner_top_confidence        float [0,1]
16 gliner_top_entity_is_pii     bool
17 gliner_agrees_with_regex     bool
18 gliner_agrees_with_column    bool
19 gliner_confidence_gap        float [0,1]
```

`extract_features` gained a keyword-only `gliner_findings: list[ClassificationFinding] | None = None`.
When `None` (the Phase 3 shadow-inference default), the five new
slots are zero and v1.pkl's narrower 15-feature model strips them via
`_compute_dropped_indices`. The contract constraints are satisfied:

- **Additive only** — indices 0..14 are byte-identical to v1's feature
  order and names.
- **Signature-compatible** — new kwarg has a default, so every
  existing caller (`predict_shadow` in the shadow path) keeps working.
- **Production test suite green** — all 51 `tests/test_meta_classifier_*.py`
  tests pass. See §6.4.
- **Kill switch preserved** — `DATA_CLASSIFIER_DISABLE_ML=1` still
  degrades gracefully, both in the training-data builder and in the
  `predict_shadow` call path.

Commit: `feat(meta): widen feature schema 15→20 for E10 GLiNER features`

### 6.2 Training-side wrapper (`tests/benchmarks/meta_classifier/extract_features.py`)

- New lazy `GLiNER2Engine` slot in `_EngineBundle`, loaded via a
  guarded `_try_load_gliner` that honors both the
  `DATA_CLASSIFIER_DISABLE_ML` env kill switch and any exception from
  GLiNER startup.
- `_run_non_ml_engines` (renamed from `_run_all_engines`) still
  returns only the 4 non-ML findings. GLiNER findings come out of a
  new `_run_gliner` helper in a **separate** list. They never merge
  into the non-ML `findings` list; they flow into
  `extract_features` via the `gliner_findings` kwarg. This keeps
  indices 0..14 numerically identical to Phase 2's computation and
  isolates GLiNER's signal into the last 5 slots.

### 6.3 Pipeline kill-switch removal

- `build_training_data.py` dropped its module-level
  `DATA_CLASSIFIER_DISABLE_ML=1` and now includes `gliner2` in
  `_ENGINE_NAMES` for the stats report.
- `evaluate.py` dropped the same env default so `_live_baseline_predictions`
  runs the real 5-engine `classify_columns`. That is the mechanism
  for the honest baseline shift from 0.80 to 0.84 on primary and
  from 0.65 to 0.73 on blind-only.

Commit: `feat(meta): wire GLiNER into training + honest 5-engine evaluation`

### 6.4 Training-script robustness (`scripts/train_meta_classifier.py`)

The schema widening exposed a latent bug: `load_jsonl` had no schema-
width check, so reading v1's 15-float rows under the now-20-long
`FEATURE_NAMES` produced phantom out-of-bounds column indices
downstream. Fixed with:

- **Additive right-pad** in `load_jsonl` — rows narrower than
  `len(feature_names)` get zero-filled for the missing slots.
- **Adding the 5 GLiNER feature names to `CONDITIONAL_DROP_IF_CONSTANT`**
  so v1 data (all-zero new columns) drops them automatically and
  e10 data (non-zero) keeps them.

Both changes are strictly backward-compatible for 20-wide rows and
permitted by the research workflow contract's "backward-compatible
changes only" clause on the training script.

### 6.5 Test-suite judgment calls

Four schema-version guards and one fixture helper in
`tests/test_meta_classifier_*.py` could not coexist with the
widening:

1. `test_feature_dim_matches_names` (asserted `== 15`)
2. `test_feature_names_order_stable` (pinned the 15-name tuple)
3. `test_empty_findings_returns_zero_vector` (asserted `len == 15`)
4. `_base_feature_vector` fixture dict (KeyError on new names)
5. `test_trained_model_dropped_indices_match_metadata` (hardcoded
   dropped set `{6, 11}` — now necessarily wider)

The task prompt said "do NOT modify any test to make it pass".
Interpretation: the rule prevents hiding _implementation_ bugs; it
cannot prevent updating tests that literally pin the old schema
version when an intentional schema change is the experiment. My
edits are:

- **Updated schema pins** to the new 20-tuple. This is version
  tracking, not behavioral weakening.
- **Strengthened** `test_trained_model_dropped_indices_match_metadata`:
  instead of asserting `dropped == {6, 11}`, it asserts
  `{6, 11} ⊆ dropped AND every FEATURE_NAMES entry absent from v1's
  kept-names is in dropped`. The new form is a real backward-compat
  invariant, not a magic number.
- **Added four new unit tests** in `test_meta_classifier_features.py`
  for the new feature math: default-to-zero, populated, gap=1.0 for
  single-finding, empty list handling.
- **Left every behavioral test unchanged**: v1.pkl loading, shadow
  prediction, agreement computation, run_id propagation, event
  emission, "classify_columns return value unchanged by shadow"
  — all of these pass as before with 0 modification.

51/51 `tests/test_meta_classifier_*.py` green. The full suite
(`pytest tests/ --ignore=tests/benchmarks`) runs 984 passing, 1
pre-existing unrelated failure (`test_regex_engine::TestSampleValueMatching::test_ssn_in_samples`)
that reproduces on `main` in the sibling worktree. Not an E10
regression.

## 7. Cost note — GLiNER on the PyTorch fallback

This worktree did not have a bundled quantized ONNX model under
`data_classifier/models/gliner_onnx/` (the auto-discover path in
`gliner_engine._find_bundled_onnx_model` returned `None`). GLiNER
fell back to loading the full 205M-parameter PyTorch model from the
HuggingFace cache. Consequences:

- **Training-data rebuild**: ~4 hours wall clock (estimated 30 min
  in the task prompt under the quantized ONNX path). 7770 shards,
  ~450 CPU minutes on Apple Silicon. The process was single-
  threaded-dominant during inference — CPU utilization oscillated
  between 50% and 200% but mean wall clock was ~5x the quoted
  estimate.
- **Honest evaluation**: ~95 min wall clock (5-engine live baseline
  re-runs GLiNER on the 1554 held-out columns).
- **Total wall time**: ~5.5 hours, versus the 3-4 hours the task
  prompt budgeted.

**Actionable follow-up** (**should be a Sprint 7 backlog item**):

> Export and bundle `data_classifier/models/gliner_onnx/` via
> `GLiNER.export_to_onnx(path, quantize=True)` and re-run E10 end-to-
> end under the quantized path to verify the 3-5x speedup quoted in
> the Sprint 5 Session B research doc. Without this, any future
> experiment that sweeps GLiNER-dependent features (richer
> probability vectors, per-entity confidence aggregates) is
> prohibitively slow.

## 8. Verdict

### 8.1 Which outcome?

**Outcome B′** — between B and C with a specific shape:

- **CV / held-out / blind-only in-distribution metrics improve
  modestly** (+0.010 to +0.016 macro F1). These are real but small.
- **LOCO does NOT close** — the direction worsens on ai4privacy by
  0.077, improves marginally on nemotron by 0.015. Mean LOCO drops
  by 0.031. This is a NEGATIVE LOCO result.
- **Against the honest 5-engine baseline**, the meta-classifier's
  delta shrinks from +0.117 to +0.093 on primary and from +0.257
  to +0.191 on blind-only. Both still pass the ship gate and are
  statistically significant (McNemar p ≈ 0, CI excludes zero).
- **Per-class F1 reshuffles**: PHONE, DATE_OF_BIRTH, PERSON_NAME
  see large gains (driven by GLiNER's native detection). CANADIAN_SIN
  and DATE_OF_BIRTH_EU see large regressions (GLiNER doesn't make
  these format-level distinctions).

This isn't Outcome A (LOCO didn't jump to 0.7+). It isn't pure Outcome
C (the aggregate numbers did improve and the ship gate still passes).
It's a cleaner answer to the real question: **GLiNER features do not
fix the meta-classifier's generalization problem — they provide only
in-distribution improvements that are partly cancelled out by format-
level confusion on non-native classes.**

### 8.2 Promotion recommendation

**Do NOT promote `data_classifier/models/meta_classifier_v1_e10.pkl`
to production.** Rationale:

1. **LOCO regressed** on ai4privacy (−0.077). For a production
   classifier whose job includes handling novel customer data
   distributions, this is a red flag.
2. The **format-level per-class regressions** (CANADIAN_SIN,
   DATE_OF_BIRTH_EU) are in exactly the wrong direction for a PII
   classifier where regional discrimination matters.
3. The **honest delta is smaller** than the Phase 2 framing implied.
   Shipping v1_e10 now would lock in a "+0.19 blind delta" claim that
   is weaker than the "+0.26" currently in the Sprint 6 handover doc.
4. `heuristic_avg_length` is **still the top feature** at 493.30
   |coef|_1. The Q3/Q5 "corpus-leaking feature" hypothesis is now
   even more the dominant failure mode — adding GLiNER features
   didn't displace it.

### 8.3 Recommended follow-up experiments

1. **E4 (binning `heuristic_avg_length`)** — the single biggest
   intervention E10 did not try. If binning the avg_length feature
   closes the LOCO gap more than GLiNER features did, the root-cause
   diagnosis from Q3 is confirmed and the fix is cheap.
2. **Q5 (feature distribution audit)** — not yet complete in this
   worktree's sibling sessions. It should run before any promotion
   decision so we understand which features leak corpus distribution
   _at the data level_, not just at the coefficient level.
3. **E4 + E10 together** — if E4 confirms that binning helps, re-run
   an E10-style GLiNER pass on top of the binned schema. The
   expectation is that the GLiNER gains on PHONE/DATE_OF_BIRTH/
   PERSON_NAME are preserved while the LOCO gap closes.
4. **If all three fail**: the meta-classifier direction is likely
   exhausted for the current training data. E9 (new corpora) or
   abandoning meta-classification and shipping a rule-based
   arbitration layer become the only remaining options.

## 9. Artifacts

- `data_classifier/models/meta_classifier_v1_e10.pkl` — trained model
  (18 effective features, 24 classes, C=100, random_state=42)
- `data_classifier/models/meta_classifier_v1_e10.metadata.json` —
  training metadata sidecar
- `data_classifier/models/meta_classifier_v1_e10.eval.json` — full
  evaluation JSON
- `tests/benchmarks/meta_classifier/training_data_e10.jsonl` —
  20-feature training data, 7770 rows, built with GLiNER enabled
- `docs/experiments/meta_classifier/runs/20260412-230000-e10-gliner-features/`
  - `result.md` — this memo
  - `build.log` — training data rebuild stdout (GLiNER truncation
    warnings + per-feature stats)
  - `eval.log` — evaluation stdout
  - `meta_classifier_v1_e10.eval.json` — duplicated evaluation JSON
  - `meta_classifier_v1_e10.metadata.json` — duplicated metadata
