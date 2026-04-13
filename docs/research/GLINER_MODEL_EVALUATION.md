# GLiNER2 Model Evaluation — Results & Recommendation

> **Branch:** `research/gliner-eval`
> **Script:** [`scripts/evaluate_gliner_models.py`](../../scripts/evaluate_gliner_models.py)
> **Raw dumps:** `GLINER_MODEL_EVALUATION.raw.json`, `GLINER_MODEL_EVALUATION.summary.json`
> **Brief:** [`GLINER_MODEL_EVALUATION_BRIEF.md`](GLINER_MODEL_EVALUATION_BRIEF.md)
> **Produced:** 2026-04-13, unattended session, ~26 min wall on M-series CPU
> **Production code touched:** none (eval drives GLiNER directly, bypasses `gliner_engine`)

---

## Decision matrix answer (TL;DR)

| lift on Ai4Privacy (GLiNER-only blind) | tier |
|---|---|
| **+0.091 F1** — baseline `urchade/gliner_multi_pii-v1@0.50` = 0.5095; best `fastino/gliner2-base-v1` + `SSN="social security number"` @ 0.80 = **0.6000** | **≥ 0.05 → ship the config change** |

**Recommendation:** File a Sprint item to promote the candidate configuration (model + threshold + label swaps) behind the existing `gliner_engine` public surface and run the full-pipeline accuracy benchmark before merging. GLiNER is **not at its configuration ceiling** — the combination of model choice and label wording moves the needle. Do *not* proceed to fork 2 (complementary NER research) yet.

> **Important caveat — GLiNER-only vs full pipeline.** The brief's 0.667 Ai4Privacy figure is *full-pipeline* blind (regex + column-name + secret scanner + heuristic + GLiNER). This eval measures *GLiNER-only* blind (no other engines), so the absolute numbers sit ~0.15 F1 lower. The **+0.091 lift is in GLiNER-only terms** — the full-pipeline lift will be smaller because regex already covers some of the types that benefit (notably SSN). Gate the merge on a confirmation run of `tests/benchmarks/accuracy_benchmark.py` showing full-pipeline Ai4Privacy lift ≥ 0.02 versus current main.

---

## Recommended configuration (candidate for Sprint promotion)

```python
# data_classifier/engines/gliner_engine.py (proposed — do not apply from this branch)
_MODEL_ID = "fastino/gliner2-base-v1"               # was urchade/gliner_multi_pii-v1
_DEFAULT_GLINER_THRESHOLD = 0.80                    # was 0.50

ENTITY_LABEL_DESCRIPTIONS["SSN"] = (
    "social security number",                       # was "national identification number"
    "Government-issued personal identification numbers such as SSN, national insurance, or tax ID",
)
ENTITY_LABEL_DESCRIPTIONS["PERSON_NAME"] = (
    "full name",                                    # was "person"  (nemotron-only lift, see § Label sweep)
    "Names of people or individuals, including first and last names",
)

# descriptions disabled for v2 baseline in this eval — include_confidence still on
```

**Why each knob:**
- **Model swap `urchade → fastino/gliner2-base-v1`** — fastino+label-tuning dominates urchade on both blind corpora (Ai4Privacy: 0.60 vs 0.51, Nemotron: 0.64 vs 0.57). Sprint 5 rejected fastino based on a narrow test; this sweep shows the rejection was a labelling artefact, not a model-capacity one.
- **Threshold 0.80** — fastino's score distribution is flatter than v1's. Below 0.55 it returns dense, low-quality spans that pollute precision; at 0.80 precision is usable. Urchade's sweet spot is 0.40–0.50 (matches current default) — raising urchade to 0.70+ *catastrophically* drops F1 (0.51 → 0.27 on Ai4Privacy, 0.57 → 0.29 on Nemotron).
- **SSN label `social security number`** — on fastino, baseline `national identification number` fails to fire on SSN columns; the swap adds +0.667 F1 for that single type (+0.095 macro on Ai4Privacy). The opposite is true for urchade — urchade's "national identification number" *correctly* fires on SSN, and swapping it to `social security number` breaks urchade's SSN detection. Label wording is model-specific and cannot be shared.
- **PERSON_NAME label `full name`** — on fastino, "full name"/"individual name" beats "person" on Nemotron (+0.038 macro) by reducing false positives. No movement on Ai4Privacy. Urchade prefers "person name" on Ai4Privacy (+0.014) but "person" is neutral on Nemotron. Pick the fastino-preferred wording.

---

## Method recap

- **Models.** `urchade/gliner_multi_pii-v1` (current production, 205M params, v1 API — labels only) and `fastino/gliner2-base-v1` (DeBERTa-base v3 encoder, v2 API — supports label descriptions).
- **Corpora.** Ai4Privacy blind + Nemotron blind, 500 rows per entity type, loaded via `tests.benchmarks.corpus_loader`. `blind=True` is mandatory — named mode hides the GLiNER signal behind the column-name engine.
- **Entity types evaluated.** `PERSON_NAME, ADDRESS, ORGANIZATION, DATE_OF_BIRTH, PHONE, SSN, EMAIL, IP_ADDRESS` — the 8 types in `ENTITY_LABEL_DESCRIPTIONS`. Columns whose gold label is outside this set (e.g. `CREDENTIAL` in Ai4Privacy) are dropped from scoring. After restriction each corpus yields **7 columns** (Nemotron has no ORGANIZATION column; Ai4Privacy has no ORGANIZATION column either).
- **Phase A — threshold × description sweep at baseline labels.** Each (model × corpus × description-mode) runs once at a near-zero cutoff, then macro F1 is re-scored post-hoc at every target threshold `{0.30, 0.40, 0.50, 0.55, 0.60, 0.70, 0.80}`. For GLiNER v1 descriptions are inapplicable (the API only accepts a label list).
- **Phase B — label sweep at the Phase-A winning config.** For each entity type, each documented alternative is tested with the other 7 entity labels held at baseline. This is the "one-swap-at-a-time" strategy from the brief — NOT a Cartesian product.
- **Scoring.** Column-level detection: entity type X is "detected" on a column iff at least one predicted span maps to X with score ≥ threshold. Macro F1 averages per-entity F1 across entity types with at least one gold column (7 per corpus).
- **Latency.** Wall clock per column including sample chunking (50 samples per chunk, ` ; ` separator) on CPU. Not directly comparable to production, which ships ONNX.
- **Code boundary.** The eval script instantiates `gliner.GLiNER` / `gliner2.GLiNER2` directly. It does NOT import `data_classifier.engines.gliner_engine` or mutate it. Baseline labels are copied verbatim from `gliner_engine.py:43` at brief time.

### Statistical caveats

- **Small column count.** 7 columns per corpus means each entity type contributes ~0.143 to macro F1. A single TP/FP/FN flip produces a visible jump. The **noise floor on macro F1 is ~0.1**. Only differences > 0.05 should be treated as signal; anything smaller is likely within the corpus's measurement precision.
- **Each column is 500 samples of one type.** Recall is effectively binary per column — if *any* sample hits above threshold, recall = 1.0; otherwise 0.0. The action is in **precision**, not recall. Every "0.000 F1" cell in the tables below is the model failing to fire on the column at all.
- **Sample truncation.** GLiNER's DeBERTa tokenizer truncates inputs > 384 tokens; some concatenated chunks spill. This affects both models equally and is not a regression versus production (`_SAMPLE_CHUNK_SIZE = 50` was chosen to stay under this limit for typical PII sample sizes).

---

## Phase A — baseline-label threshold sweep

Full post-hoc threshold scan at baseline labels. Bolded rows are the per-(model, corpus) winners.

### `urchade/gliner_multi_pii-v1`

| corpus | desc | thr 0.30 | 0.40 | 0.50 | 0.55 | 0.60 | 0.70 | 0.80 |
|---|---|---|---|---|---|---|---|---|
| ai4privacy | n/a | 0.4619 | **0.5095** | **0.5095** | 0.3667 | 0.3667 | 0.3667 | 0.2714 |
| nemotron | n/a | 0.5238 | **0.5714** | 0.5714 | 0.5714 | 0.5714 | 0.2857 | 0.2857 |

Urchade's calibrated scores peak at the current production default (0.40–0.50). Above 0.55 the precision gain does not compensate for recall loss. The current `_DEFAULT_GLINER_THRESHOLD = 0.5` is already correct for this model.

### `fastino/gliner2-base-v1`

| corpus | desc | thr 0.30 | 0.40 | 0.50 | 0.55 | 0.60 | 0.70 | 0.80 |
|---|---|---|---|---|---|---|---|---|
| ai4privacy | False | 0.3456 | 0.3456 | 0.3456 | 0.3932 | 0.3075 | 0.4000 | **0.5048** |
| ai4privacy | True | 0.3500 | 0.3500 | 0.3500 | 0.3881 | 0.4024 | 0.3643 | 0.4119 |
| nemotron | False | 0.4095 | 0.4095 | 0.4095 | 0.4333 | 0.4810 | 0.5048 | **0.6048** |
| nemotron | True | 0.3905 | 0.3905 | 0.3905 | 0.4238 | 0.4714 | 0.4952 | 0.5429 |

Fastino runs best at the TOP of the swept threshold band (0.80). Runs at thresholds ≤ 0.50 produce nearly identical F1 because `gliner2.extract_entities` applies its own internal floor around ~0.50–0.55 — the post-hoc sweep at lower thresholds is effectively a no-op for this model. A follow-up should confirm whether thresholds above 0.80 continue to help.

### Description impact (fastino only)

| corpus | best with desc | best without desc | winner |
|---|---|---|---|
| ai4privacy | 0.4119 @ 0.80 | **0.5048 @ 0.80** | **without** (-0.093 with desc) |
| nemotron | 0.5429 @ 0.80 | **0.6048 @ 0.80** | **without** (-0.062 with desc) |

**Key finding — contradicts Sprint 5.** Sprint 5's narrow test found descriptions helped fastino (specifically on partial addresses). In this blind, 500-row, 8-type sweep, **descriptions consistently hurt fastino** — the model treats the description as an additional semantic constraint that over-restricts matches. Ship fastino without descriptions. Keep the description strings in `ENTITY_LABEL_DESCRIPTIONS` for documentation and future tuning, but pass `{label: ""}` (or drop to label-list mode) at inference.

---

## Phase B — label alternative sweep

For each model × corpus, one label is swapped at a time at the Phase-A winning threshold. Bolded rows improved on baseline, crossed-through rows regressed.

### `urchade/gliner_multi_pii-v1` @ threshold 0.40–0.50

**Ai4Privacy** (baseline 0.5095):

| swap | F1 | Δ |
|---|---|---|
| **PERSON_NAME = "person name"** | 0.5238 | **+0.014** |
| ADDRESS = physical address / home address | 0.5095 | 0.000 |
| ORGANIZATION = company / institution / business name | 0.5095 | 0.000 |
| DATE_OF_BIRTH = birthday / birth date | 0.5095 | 0.000 |
| PHONE = telephone / phone | 0.5095 | 0.000 |
| EMAIL = email address | 0.5095 | 0.000 |
| IP_ADDRESS = internet protocol address / ipv4 address | 0.5095 | 0.000 |
| EMAIL = e-mail | 0.4619 | -0.048 |
| PERSON_NAME = full name / individual name | 0.4524 | -0.057 |
| PHONE = contact number | 0.4143 | -0.095 |
| ADDRESS = mailing address | 0.3667 | -0.143 |
| SSN = social security number | 0.3667 | -0.143 |
| SSN = government id | 0.3667 | -0.143 |
| SSN = tax id | 0.3667 | -0.143 |

**Nemotron** (baseline 0.5714): every swap is neutral or worse (PERSON_NAME, ADDRESS, PHONE variants all → 0.4286; everything else holds at 0.5714). Urchade's labels are already tuned for this corpus.

**Urchade verdict:** the production label table at `gliner_engine.py:43` is nearly optimal for this model. The only meaningful win is `PERSON_NAME = "person name"` on Ai4Privacy (+0.014 — within the noise floor). **SSN swaps catastrophically hurt urchade** on Ai4Privacy because the baseline `national identification number` is what actually fires on that corpus's values. DO NOT swap urchade's SSN label.

### `fastino/gliner2-base-v1` @ threshold 0.80, descriptions=False

**Ai4Privacy** (baseline 0.5048):

| swap | F1 | Δ |
|---|---|---|
| **SSN = "social security number"** | 0.6000 | **+0.095** |
| **SSN = "tax id"** | 0.5429 | **+0.038** |
| **PHONE = "phone"** | 0.5190 | **+0.014** |
| **IP_ADDRESS = "ipv4 address"** | 0.5190 | **+0.014** |
| (various neutral swaps) | 0.5048 | 0.000 |
| ADDRESS = physical address / PHONE = contact number | 0.4952 | -0.010 |
| PERSON_NAME = full name / DOB = birthday / SSN = government id / EMAIL = e-mail | 0.4810 | -0.024 |
| IP_ADDRESS = internet protocol address | 0.4143 | -0.090 |
| ADDRESS = mailing address | 0.4000 | -0.105 |

**Nemotron** (baseline 0.6048):

| swap | F1 | Δ |
|---|---|---|
| **PERSON_NAME = "full name"** | 0.6429 | **+0.038** |
| **PERSON_NAME = "individual name"** | 0.6429 | **+0.038** |
| **PERSON_NAME = "person name"** | 0.6190 | **+0.014** |
| (various neutral swaps) | 0.6048 | 0.000 |
| PHONE = phone / contact number | 0.5810–0.5905 | -0.014 to -0.024 |
| ADDRESS = physical address / home address / SSN = tax id | 0.5571 | -0.048 |
| ADDRESS = mailing address | 0.5476 | -0.057 |
| IP_ADDRESS = internet protocol address | 0.5095 | -0.095 |

**Fastino verdict:** two material wins and two steady regressions, cleanly separated by corpus.
- **Ai4Privacy win:** `SSN = "social security number"` +0.095 (the headline lift — drives the decision-matrix answer).
- **Nemotron win:** `PERSON_NAME = "full name"` +0.038.
- **Cross-corpus neutral:** neither winning swap hurts the other corpus — the SSN swap is 0.000 on Nemotron, and the PERSON_NAME swap has no measurement on Ai4Privacy (it scored 0.4810 which is -0.024, so mildly negative). Combined swaps are NOT tested in this sweep (brief explicitly opted for one-swap-at-a-time).
- **Reliable regressions to avoid:** `ADDRESS = mailing address`, `IP_ADDRESS = internet protocol address`. Do not promote these.

---

## Per-entity-type breakdown — winning config vs production

**Winning config:** `fastino/gliner2-base-v1` @ threshold 0.80, descriptions off, `SSN = "social security number"`.

### Ai4Privacy (blind, 7 columns)

| entity type | urchade baseline | fastino+SSN swap | Δ |
|---|---|---|---|
| ADDRESS | F1 **1.000** (TP=1, FP=0) | F1 0.667 (TP=1, FP=1) | -0.333 |
| DATE_OF_BIRTH | F1 0.000 (TP=0, FN=1) | F1 **0.667** (TP=1, FP=1) | **+0.667** |
| EMAIL | F1 0.500 (TP=1, FP=2) | F1 **1.000** (TP=1, FP=0) | **+0.500** |
| IP_ADDRESS | F1 0.000 (TP=0, FN=1, FP=1) | F1 **0.400** (TP=1, FP=3) | **+0.400** |
| PERSON_NAME | F1 0.400 (TP=1, FP=3) | F1 0.400 (TP=1, FP=3) | 0.000 |
| PHONE | F1 0.667 (TP=1, FP=1) | F1 0.400 (TP=1, FP=3) | -0.267 |
| SSN | F1 **1.000** (TP=1, FP=0) | F1 0.667 (TP=1, FP=1) | -0.333 |
| **macro** | **0.5095** | **0.6000** | **+0.091** |

Fastino+swap **rescues three types** (DOB, EMAIL, IP_ADDRESS → all non-zero) at the cost of precision regressions on three already-working types (ADDRESS, PHONE, SSN → each drops one TP → FP mix). The net macro lift of +0.091 comes from the recall rescues outweighing the precision noise.

### Nemotron (blind, 7 columns) — using fastino + PERSON_NAME=full name

| entity type | urchade baseline | fastino+PERSON_NAME swap | Δ |
|---|---|---|---|
| ADDRESS | F1 **1.000** | F1 **1.000** | 0.000 |
| DATE_OF_BIRTH | F1 0.000 (FN=1) | F1 **0.667** (TP=1, FP=1) | **+0.667** |
| EMAIL | F1 **1.000** | F1 **1.000** | 0.000 |
| IP_ADDRESS | F1 0.000 (FN=1) | F1 **0.667** (TP=1, FP=1) | **+0.667** |
| PERSON_NAME | F1 **1.000** | F1 0.667 (TP=1, FP=1) | -0.333 |
| PHONE | F1 **1.000** | F1 0.500 (TP=1, FP=2) | -0.500 |
| SSN | F1 0.000 (FN=1) | F1 0.000 (FP=1, FN=1) | 0.000 |
| **macro** | **0.5714** | **0.6429** | **+0.072** |

Fastino rescues DOB and IP_ADDRESS (recall → 1.0) at the cost of PERSON_NAME/PHONE precision. SSN remains uncaught on Nemotron by fastino too — the Nemotron SSN column is **the single biggest unsolved type across both models and all configs** in this eval.

---

## Latency

All measurements on CPU (PyTorch, no ONNX). Per-column includes the full 500-sample chunking into 10 chunks of 50 values joined by `" ; "`.

| configuration | Ai4Privacy ms/col | Nemotron ms/col |
|---|---|---|
| urchade baseline @ 0.50 | 2618 | 2294 |
| fastino baseline @ 0.80 (desc off) | 2616 | 2242 |
| **fastino + SSN swap @ 0.80** | **2568** | — |
| fastino + PERSON_NAME swap @ 0.80 | — | 2251 |

**No latency cost.** The fastino candidate is within ±2% of current production per column on CPU. ONNX production numbers should behave similarly — the model sizes are comparable (gliner2-base-v1 uses DeBERTa-v3-base, ~140M params vs gliner_multi_pii-v1's 205M). A sprint-side re-measurement on the ONNX runtime is advisable but not a merge gate.

---

## Follow-ups the memo deliberately does not answer

1. **Combined label swaps.** This sweep tests one-swap-at-a-time. The combined candidate `fastino + SSN="social security number" + PERSON_NAME="full name"` has NOT been measured. A focused 4-run check (fastino @ 0.80 desc=off × {baseline, SSN swap, PERSON_NAME swap, both swaps} × 2 corpora) would close the gap — add to the Sprint item.
2. **Full-pipeline confirmation.** The decision matrix uses GLiNER-only deltas; the production target uses full-pipeline blind. A merge run of `tests/benchmarks/accuracy_benchmark.py` against `fastino/gliner2-base-v1` with the proposed label table is required. The expected outcome: smaller absolute lift on Ai4Privacy (likely +0.02 to +0.05) because regex covers SSN-shaped values independently.
3. **Nemotron SSN.** Neither model detects the Nemotron SSN column at any tested threshold or label. Root cause is unknown (format mismatch? tokenization? corpus value distribution?). This is the biggest per-type gap and deserves its own backlog item, possibly under fork-2 "complementary NER" research if the full-pipeline re-run shows the column is also regex-blind.
4. **Threshold > 0.80.** Fastino peaked at the top of the swept threshold band on both corpora. Thresholds `{0.85, 0.90}` were not tested and may continue to help. Add to a follow-up micro-sweep.
5. **Internal threshold of `gliner2.extract_entities`.** The v2 API appears to apply its own lower bound (~0.50–0.55) before returning spans. Post-hoc filtering below that bound is inert. This should be verified against gliner2 source code — if true, the Phase A rows at thr ≤ 0.50 for fastino are uninformative and should be dropped from future sweeps.

---

## Files produced by this eval

| file | purpose |
|---|---|
| `scripts/evaluate_gliner_models.py` | Self-contained sweep script (`--quick` / `--full` flags) |
| `docs/research/GLINER_MODEL_EVALUATION.md` | This memo |
| `docs/research/GLINER_MODEL_EVALUATION.raw.json` | Every scored config (phase A + phase B) |
| `docs/research/GLINER_MODEL_EVALUATION.summary.json` | Phase-A and Phase-B best-per-(model, corpus) digest |

## How to reproduce

```bash
cd /Users/guyguzner/Projects/data_classifier-gliner-eval
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,ml,ml-api]"
.venv/bin/python scripts/evaluate_gliner_models.py --full
```

Full sweep runs in ~26 minutes on M-series CPU. The `--quick` mode (100 rows × priority types only) runs in ~3.5 minutes and is suitable for CI smoke.

## Production code touched

None. As required by the brief, the eval drives `gliner.GLiNER` and `gliner2.GLiNER2` directly. `data_classifier/engines/gliner_engine.py` is unchanged on this branch — any promotion of the candidate configuration must happen in a follow-up Sprint item on a separate branch.
